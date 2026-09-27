from collections import defaultdict
from time import time

import redis
from fastapi import HTTPException, status


class MemoryRateLimiter:
    """A deterministic test implementation of the tenant rate-limit policy."""

    def __init__(self, requests_per_minute: int) -> None:
        self.requests_per_minute = requests_per_minute
        self.events: dict[str, list[float]] = defaultdict(list)

    def check(self, tenant_id: str) -> None:
        now = time()
        events = [at for at in self.events[tenant_id] if now - at < 60]
        if len(events) >= self.requests_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Tenant rate limit exceeded; try again shortly.",
            )
        events.append(now)
        self.events[tenant_id] = events


class RedisRateLimiter:
    """Shared rate-limit counter for multiple API instances."""

    def __init__(self, redis_url: str, requests_per_minute: int) -> None:
        self.client = redis.from_url(redis_url, decode_responses=True)
        self.requests_per_minute = requests_per_minute

    def check(self, tenant_id: str) -> None:
        key = f"relayguard:rate:{tenant_id}"
        count = self.client.incr(key)
        if count == 1:
            self.client.expire(key, 60)
        if count > self.requests_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Tenant rate limit exceeded; try again shortly.",
            )
