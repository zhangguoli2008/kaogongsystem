from collections import OrderedDict, deque
from time import monotonic
from threading import Lock
from typing import Callable


class RateLimiter:
    def __init__(
        self, limit: int = 10, window_seconds: int = 60, max_keys: int = 10_000
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._attempts: OrderedDict[str, deque[float]] = OrderedDict()

    def allow(self, key: str) -> bool:
        now = monotonic()
        cutoff = now - self.window_seconds
        self._prune_expired_keys(cutoff)

        attempts = self._attempts.get(key)
        if attempts is None:
            if len(self._attempts) >= self.max_keys:
                return False
            attempts = deque()
            self._attempts[key] = attempts

        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if len(attempts) >= self.limit:
            return False
        attempts.append(now)
        self._attempts.move_to_end(key)
        return True

    def _prune_expired_keys(self, cutoff: float) -> None:
        while self._attempts:
            _, attempts = next(iter(self._attempts.items()))
            if attempts and attempts[-1] > cutoff:
                return
            self._attempts.popitem(last=False)


class DualWindowRateLimiter:
    """Atomic process-local sliding windows for one minute and one hour."""

    def __init__(
        self,
        *,
        minute_limit: int = 5,
        hour_limit: int = 50,
        max_keys: int = 10_000,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if minute_limit < 1 or hour_limit < 1:
            raise ValueError("rate limits must be positive")
        self.minute_limit = minute_limit
        self.hour_limit = hour_limit
        self.max_keys = max_keys
        self._clock = clock
        self._attempts: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        minute_cutoff = now - 60.0
        hour_cutoff = now - 3600.0
        with self._lock:
            self._prune_expired_keys(hour_cutoff)
            attempts = self._attempts.get(key)
            if attempts is None:
                if len(self._attempts) >= self.max_keys:
                    return False
                attempts = deque()
                self._attempts[key] = attempts

            while attempts and attempts[0] <= hour_cutoff:
                attempts.popleft()
            minute_count = sum(timestamp > minute_cutoff for timestamp in attempts)
            if minute_count >= self.minute_limit or len(attempts) >= self.hour_limit:
                self._attempts.move_to_end(key)
                return False
            attempts.append(now)
            self._attempts.move_to_end(key)
            return True

    def _prune_expired_keys(self, cutoff: float) -> None:
        expired = [
            key
            for key, attempts in self._attempts.items()
            if not attempts or attempts[-1] <= cutoff
        ]
        for key in expired:
            self._attempts.pop(key, None)
