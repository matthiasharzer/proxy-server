from abc import ABC, abstractmethod
from datetime import UTC, datetime

from proxy.caching.cache_request import CacheRequest

type TimedCache = tuple[bytes, datetime]


class CacheProvider(ABC):
    """
    A cache provider that can be used to cache requests
    """

    @abstractmethod
    def _get(self, request: CacheRequest) -> TimedCache | None:
        """
        Get the response and timestamp from the cache
        :param request: The request to get the response for
        :return:  A tuple containing the response and timestamp
        """

    def get(self, request: CacheRequest) -> bytes | None:
        """
        Get the response from the cache if it exists and is not stale
        :param request: The request to get the response for
        :return: The response if it exists and is not stale, None otherwise
        """
        cached = self._get(request)
        if not cached:
            return None

        response, timestamp = cached

        time_diff = datetime.now(UTC) - timestamp

        if request.max_age <= 0 or 0 < time_diff.seconds < request.max_age:
            return response

        return None

    @abstractmethod
    def set(self, request: CacheRequest, response: bytes) -> None:
        """
        Save the response to the cache
        :param request: The request to save the response for
        :param response: The response to save
        :return:
        """
