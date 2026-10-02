import json
from datetime import UTC, datetime

from proxy.caching.cache_provider import CacheProvider
from proxy.caching.cache_provider.cache_provider import TimedCache
from proxy.caching.cache_request import CacheRequest


def _hash_request(request: CacheRequest) -> int:
    """
    Hash a request
    :param request:
    :return:
    """
    return hash(
        (request.method, request.url, request.body, json.dumps(request.headers))
    )


class InMemoryCacheProvider(CacheProvider):
    def __init__(self):
        self.cache: dict[int, TimedCache] = {}

    def _get(self, request: CacheRequest) -> TimedCache | None:
        hashed = _hash_request(request)
        return self.cache.get(hashed)

    def set(self, request: CacheRequest, response: bytes) -> None:
        hashed = _hash_request(request)
        self.cache[hashed] = (response, datetime.now(UTC))
