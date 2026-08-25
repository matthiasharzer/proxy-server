import json
from datetime import UTC, datetime

import mysql.connector
import mysql.connector.cursor

from proxy.caching.cache_provider import CacheProvider
from proxy.caching.cache_provider.cache_provider import TimedCache
from proxy.caching.cache_request import CacheRequest

_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS cache (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    method TEXT NOT NULL,
    url TEXT NOT NULL,
    response MEDIUMBLOB NOT NULL,
    body BLOB NULL,
    headers TEXT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );"""


def _get_current_timestamp() -> str:
    """
    Get the current timestamp as a string
    :return:
    """
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


class MySQLCacheProvider(CacheProvider):
    def __init__(
        self, host: str, user: str, password: str, database: str, port: int = 3306
    ):
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self.port = port
        self.initialized = False
        try:
            self._create_table()
            self.initialized = True
        except mysql.connector.errors.Error as e:
            print("Error while initializing cache: " + str(e))

    def _connect(self) -> mysql.connector.MySQLConnection:
        return mysql.connector.connect(
            host=self.host,
            user=self.user,
            password=self.password,
            database=self.database,
            port=self.port,
        )  # type: ignore

    def _create_table(self):
        db = self._connect()
        try:
            c = db.cursor()
            c.execute(_TABLE_SQL)
            db.commit()
        except mysql.connector.errors.Error as e:
            print(e)

    def _get(self, request: CacheRequest) -> TimedCache | None:
        """
        Get the response and timestamp from the cache
        :param request: The request to get the response for
        :return:  A tuple containing the response and timestamp
        """

        headers = json.dumps(request.headers) if request.headers else ""

        db = self._connect()
        c = db.cursor()
        c.execute(
            "SELECT response, timestamp FROM cache WHERE method = %s AND url = %s AND body <=> %s AND headers <=> %s",
            (request.method, request.url, request.body, headers),
        )

        result = c.fetchone()
        if result:
            return result[0], result[1].replace(tzinfo=UTC)
        return None

    def set(self, request: CacheRequest, response: bytes) -> None:
        """
        Save the response to the cache
        :param request: The request to save the response for
        :param response: The response to save
        :return:
        """
        headers = json.dumps(request.headers) if request.headers else ""

        db = self._connect()
        c = db.cursor()
        c.execute(
            "SELECT id FROM cache WHERE method = %s AND url = %s AND body <=> %s AND headers <=> %s",
            (request.method, request.url, request.body, headers),
        )
        existing = c.fetchone()

        if existing:
            c.execute(
                "UPDATE cache SET response = %s, timestamp = %s WHERE id = %s",
                (response, _get_current_timestamp(), existing[0]),
            )
        else:
            c.execute(
                "INSERT INTO cache (method, url, response, body, headers, timestamp) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    request.method,
                    request.url,
                    response,
                    request.body,
                    headers,
                    _get_current_timestamp(),
                ),
            )

        db.commit()
