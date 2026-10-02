import asyncio
import os
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from fastapi import HTTPException, Request

from proxy import server
from proxy.caching.cache_handler import get_cache_provider
from proxy.caching.cache_provider.in_memory_cache_provider import InMemoryCacheProvider
from proxy.caching.cache_provider.mysql_cache_provider import MySQLCacheProvider
from proxy.caching.cache_provider.mysql_cache_provider import (
    _get_current_timestamp as mysql_timestamp,
)
from proxy.caching.cache_provider.sqlite_cache_provider import SQLiteCacheProvider
from proxy.caching.cache_provider.sqlite_cache_provider import (
    _get_current_timestamp as sqlite_timestamp,
)
from proxy.caching.cache_request import CacheRequest


def make_request(url="https://example.com"):
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "GET",
            "headers": [],
            "query_string": b"",
            "path_params": {"url": url},
        },
        receive,
    )


class CacheTimestampTests(unittest.TestCase):
    def setUp(self):
        # Exercise legacy local timestamps away from UTC without requiring tzdata.
        self.environment = patch.dict(os.environ, {"TZ": "EST5"})
        self.environment.start()
        time.tzset()
        self.addCleanup(time.tzset)
        self.addCleanup(self.environment.stop)
        self.request = CacheRequest("GET", "https://example.com", max_age=60)
        self.now = datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)

    def test_memory_timestamps_are_aware_and_expire(self):
        provider = InMemoryCacheProvider()
        with patch(
            "proxy.caching.cache_provider.in_memory_cache_provider.datetime"
        ) as clock:
            clock.now.return_value = self.now
            provider.set(self.request, b"cached")
        self.assertIsNotNone(provider._get(self.request)[1].tzinfo)
        self.assert_cache_age(provider)

    def assert_cache_age(self, provider):
        with patch("proxy.caching.cache_provider.cache_provider.datetime") as clock:
            clock.now.return_value = self.now + timedelta(seconds=10)
            self.assertEqual(provider.get(self.request), b"cached")
            clock.now.return_value = self.now + timedelta(seconds=61)
            self.assertIsNone(provider.get(self.request))
            self.request.max_age = 0
            self.assertEqual(provider.get(self.request), b"cached")

    def test_sqlite_reads_legacy_local_timestamps_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = SQLiteCacheProvider(str(Path(directory) / "cache.db"))
            for response in (b"initial", b"updated"):
                provider.set(self.request, response)
                cached, timestamp = provider._get(self.request)
                self.assertEqual(cached, response)
                self.assertLess(abs((datetime.now(UTC) - timestamp).total_seconds()), 2)
            with closing(sqlite3.connect(provider.db_file)) as connection, connection:
                connection.execute(
                    "UPDATE cache SET response = ?, timestamp = ?",
                    (b"cached", "2026-01-02 07:00:00"),
                )
            self.assert_cache_age(provider)

    def test_mysql_interprets_naive_connector_timestamps_as_local(self):
        with patch.object(MySQLCacheProvider, "_connect") as connect:
            connect.return_value.cursor.return_value.fetchone.return_value = (
                b"cached",
                self.now.astimezone().replace(tzinfo=None),
            )
            provider = MySQLCacheProvider("localhost", "user", "test", "cache")
            self.assertEqual(provider._get(self.request)[1], self.now)
            self.assert_cache_age(provider)

    def test_database_writers_preserve_local_time_format(self):
        for module, timestamp in (
            ("mysql_cache_provider", mysql_timestamp),
            ("sqlite_cache_provider", sqlite_timestamp),
        ):
            with (
                self.subTest(provider=module),
                patch(f"proxy.caching.cache_provider.{module}.datetime") as clock,
            ):
                clock.now.return_value = self.now
                self.assertEqual(timestamp(), "2026-01-02 07:00:00")

    def test_sqlite_failure_is_logged_and_treated_as_miss(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = SQLiteCacheProvider(str(Path(directory) / "cache.db"))
            with (
                patch.object(
                    provider, "_connect", side_effect=sqlite3.OperationalError
                ),
                self.assertLogs(
                    "proxy.caching.cache_provider.sqlite_cache_provider", level="ERROR"
                ) as logs,
            ):
                self.assertIsNone(provider.get(self.request))
            self.assertIsNotNone(logs.records[0].exc_info)


class ProxyRegressionTests(unittest.TestCase):
    def test_mysql_default_and_custom_port(self):
        environment = {
            "CACHE_MODE": "mysql",
            "MYSQL_HOST": "localhost",
            "MYSQL_USER": "user",
            "MYSQL_PASSWORD": "test",
            "MYSQL_DATABASE": "cache",
        }
        for port, expected in ((None, 3306), ("3307", 3307)):
            with (
                self.subTest(port=port),
                patch.dict(os.environ, environment, clear=True),
                patch("proxy.caching.cache_handler.MySQLCacheProvider") as provider,
            ):
                if port is not None:
                    os.environ["MYSQL_PORT"] = port
                get_cache_provider()
                self.assertEqual(provider.call_args.kwargs["port"], expected)

    def test_url_normalization(self):
        for url, expected in (
            ("http://example.com", "http://example.com"),
            ("https://example.com", "https://example.com"),
            ("http:/example.com", "http://example.com"),
            ("https:/example.com", "https://example.com"),
            ("example.com", "example.com"),
        ):
            with self.subTest(url=url):
                self.assertEqual(server.get_url(make_request(url)), expected)

    def test_cache_failures_still_return_upstream_response(self):
        cache = Mock()
        cache.get.side_effect = RuntimeError("read failed")
        cache.set.side_effect = RuntimeError("write failed")
        with (
            patch.object(server, "cache", cache),
            patch.object(server, "do_proxy_request", return_value=b"upstream"),
            self.assertLogs("proxy.server", level="ERROR") as logs,
        ):
            response = asyncio.run(server.handle_cache(make_request(), 60))
        self.assertEqual(response.body, b"upstream")
        self.assertEqual(len(logs.records), 2)
        self.assertTrue(all(record.exc_info for record in logs.records))

    def test_proxy_error_statuses_are_preserved(self):
        for error, status in ((requests.ConnectionError(), 404), (ValueError(), 400)):
            with (
                self.subTest(error=type(error)),
                patch.object(server.requests, "request", side_effect=error),
                patch.object(server.logger, "exception") as log,
                self.assertRaises(HTTPException) as raised,
            ):
                server.do_proxy_request("https://example.com", make_request())
            self.assertEqual(raised.exception.status_code, status)
            self.assertEqual(log.call_count, int(status == 400))


if __name__ == "__main__":
    unittest.main()
