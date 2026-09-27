import time
from threading import Lock

import redis


class FixedWindowRateLimiter:
    """Small process-local limiter for a single API instance.

    Production multi-replica deployments should replace this adapter with a Redis atomic counter.
    Keeping the policy behind this class makes that swap explicit and testable.
    """

    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._events: dict[str, list[float]] = {}
        self._lock = Lock()

    def allow(self, identity: str) -> bool:
        if self.max_requests <= 0:
            return True
        now = time.monotonic()
        threshold = now - self.window_seconds
        with self._lock:
            active = [event for event in self._events.get(identity, []) if event > threshold]
            if len(active) >= self.max_requests:
                self._events[identity] = active
                return False
            active.append(now)
            self._events[identity] = active
            return True


class RedisFixedWindowRateLimiter:
    """Atomic Redis limiter that stays correct when API replicas scale horizontally."""

    def __init__(self, redis_url: str, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.client = redis.from_url(redis_url, decode_responses=True)

    def allow(self, identity: str) -> bool:
        if self.max_requests <= 0:
            return True
        window = int(time.time() // self.window_seconds)
        key = f"decisiongraph:rate-limit:{identity}:{window}"
        pipeline = self.client.pipeline()
        pipeline.incr(key)
        pipeline.expire(key, self.window_seconds + 1)
        count, _ = pipeline.execute()
        return int(count) <= self.max_requests
