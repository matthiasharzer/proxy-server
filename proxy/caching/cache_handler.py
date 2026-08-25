import os

from proxy.caching.cache_provider import CacheProvider
from proxy.caching.cache_provider.in_memory_cache_provider import InMemoryCacheProvider
from proxy.caching.cache_provider.mysql_cache_provider import MySQLCacheProvider
from proxy.caching.cache_provider.no_cache_provider import NoCacheProvider
from proxy.caching.cache_provider.sqlite_cache_provider import SQLiteCacheProvider

CACHE_DB_FILE = "data/cache.db"


def get_cache_provider() -> CacheProvider:
    cache_type = os.environ.get("CACHE_MODE", "none")

    print("Using cache provider: " + cache_type)

    match cache_type:
        case "sqlite":
            db_file = os.environ.get("SQLITE_FILE", CACHE_DB_FILE)
            db_file_dir = os.path.dirname(db_file)
            if not os.path.exists(db_file_dir):
                os.makedirs(db_file_dir)

            return SQLiteCacheProvider(db_file)
        case "memory":
            return InMemoryCacheProvider()
        case "mysql":
            host = os.environ.get("MYSQL_HOST")
            user = os.environ.get("MYSQL_USER")
            password = os.environ.get("MYSQL_PASSWORD")
            database = os.environ.get("MYSQL_DATABASE")
            port = os.environ.get("MYSQL_PORT", "3306")

            if None in (host, user, password, database):
                print(
                    "WARNING: Missing environment variables for MySQL cache provider. "
                    "Required: MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE"
                    "\nFalling back to NoCacheProvider."
                )
                return NoCacheProvider()

            return MySQLCacheProvider(
                host=host,  # type: ignore
                user=user,  # type: ignore
                password=password,  # type: ignore
                database=database,  # type: ignore
                port=port,  # type: ignore
            )
        case "none":
            return NoCacheProvider()

    print(
        f"WARNING: No cache provider found for type {
            cache_type
        }. Using NoCacheProvider."
    )

    return NoCacheProvider()
