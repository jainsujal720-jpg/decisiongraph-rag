import pytest
from fastapi import HTTPException

from relayguard.services.rate_limit import MemoryRateLimiter


def test_rate_limit_blocks_after_tenant_budget() -> None:
    limiter = MemoryRateLimiter(requests_per_minute=1)
    limiter.check("acme")
    with pytest.raises(HTTPException) as error:
        limiter.check("acme")
    assert error.value.status_code == 429
