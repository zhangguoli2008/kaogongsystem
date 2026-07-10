from collections import OrderedDict, deque
from time import monotonic


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
