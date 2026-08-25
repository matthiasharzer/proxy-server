import json
import sqlite3
from datetime import UTC, datetime
from sqlite3 import Error

from proxy.caching.cache_provider import CacheProvider
from proxy.caching.cache_provider.cache_provider import TimedCache
from proxy.caching.cache_request import CacheRequest

_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method TEXT NOT NULL,
    url TEXT NOT NULL,
    response BLOB NOT NULL,
    body BLOB NULL,
    headers TEXT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (method, url, body, headers)
    );"""


def _get_current_timestamp() -> str:
    """
    Get the current timestamp as a string
    :return:
    """
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


class SQLiteCacheProvider(CacheProvider):
    """
    A cache provider that uses SQLite as the backend
    """

    def __init__(self, file_name: str):
        self.db_file = file_name
        self.initialized = False
        try:
            self._create_table()
            self.initialized = True
        except Error as e:
            print("Error while initializing cache: " + str(e))

    def _create_table(self):
        try:
            c = self._connect().cursor()
            c.execute(_TABLE_SQL)
        except Error as e:
            print("Error while creating table: " + str(e))

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_file)

    def _get(self, request: CacheRequest) -> TimedCache | None:
        """
        Get the response and timestamp from the cache
        :param request: The request to get the response for
        :return:  A tuple containing the response and timestamp
        """
        if not self.initialized:
            return None

        headers = json.dumps(request.headers) if request.headers else ""

        try:
            with self._connect() as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT response, timestamp FROM cache WHERE method = ? "
                    "AND url = ? AND body IS ? AND headers IS ?",
                    (request.method, request.url, request.body, headers),
                )
                result = c.fetchone()

                if not result:
                    return None

                time_stamp = datetime.strptime(result[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)

                return result[0], time_stamp
        except Exception as e:  # noqa: BLE001
            print("Error while fetching from cache: " + str(e))

        return None

    def set(self, request: CacheRequest, response: bytes) -> None:
        if not self.initialized:
            return

        headers = json.dumps(request.headers) if request.headers else ""

        with self._connect() as conn:
            c = conn.cursor()

            c.execute(
                "SELECT id, timestamp FROM cache WHERE method = ? "
                "AND url = ? AND body IS ? AND headers IS ?",
                (request.method, request.url, request.body, headers),
            )
            result = c.fetchone()

            if result:
                c.execute(
                    "UPDATE cache SET response = ?, timestamp = ? WHERE id = ?",
                    (response, _get_current_timestamp(), result[0]),
                )
                conn.commit()
                return
            else:
                c.execute(
                    "INSERT INTO cache (method, url, response, body, headers, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        request.method,
                        request.url,
                        response,
                        request.body,
                        headers,
                        _get_current_timestamp(),
                    ),
                )
                conn.commit()
