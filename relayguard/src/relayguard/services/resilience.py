from dataclasses import dataclass
from time import monotonic

from redis import Redis

from relayguard.services.providers import CompletionProvider, ProviderResult, ProviderUnavailable


@dataclass
class BreakerState:
    failures: int = 0
    open_until: float = 0.0


class CircuitBreaker:
    """Avoid repeatedly calling a provider that has recently failed."""

    def __init__(self, failure_threshold: int, reset_seconds: int) -> None:
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.states: dict[str, BreakerState] = {}

    def is_open(self, model: str) -> bool:
        state = self.states.get(model)
        if not state:
            return False
        if state.open_until == 0.0:
            return False
        if state.open_until <= monotonic():
            state.failures = 0
            state.open_until = 0.0
            return False
        return True

    def record_success(self, model: str) -> None:
        self.states[model] = BreakerState()

    def record_failure(self, model: str) -> None:
        state = self.states.setdefault(model, BreakerState())
        state.failures += 1
        if state.failures >= self.failure_threshold:
            state.open_until = monotonic() + self.reset_seconds

    def status(self, model: str) -> dict[str, int | str]:
        """Return a safe, dashboard-friendly view of one provider circuit."""
        state = self.states.get(model, BreakerState())
        if self.is_open(model):
            retry_after = max(1, round(state.open_until - monotonic()))
            return {"model": model, "state": "open", "failures": state.failures, "retry_after_seconds": retry_after}
        return {"model": model, "state": "closed", "failures": state.failures, "retry_after_seconds": 0}


class RedisCircuitBreaker:
    """Shared circuit state that remains active across API restarts and replicas."""

    def __init__(
        self,
        redis_url: str,
        failure_threshold: int,
        reset_seconds: int,
        namespace: str = "relayguard:circuit",
    ) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.namespace = namespace

    def _failures_key(self, model: str) -> str:
        return f"{self.namespace}:{model}:failures"

    def _open_key(self, model: str) -> str:
        return f"{self.namespace}:{model}:open"

    def is_open(self, model: str) -> bool:
        return bool(self.redis.exists(self._open_key(model)))

    def record_success(self, model: str) -> None:
        self.redis.delete(self._failures_key(model), self._open_key(model))

    def record_failure(self, model: str) -> None:
        failures_key = self._failures_key(model)
        failures = int(self.redis.incr(failures_key))
        self.redis.expire(failures_key, self.reset_seconds)
        if failures >= self.failure_threshold:
            self.redis.set(self._open_key(model), "open", ex=self.reset_seconds)

    def status(self, model: str) -> dict[str, int | str]:
        failures = int(self.redis.get(self._failures_key(model)) or 0)
        retry_after = max(0, self.redis.ttl(self._open_key(model)))
        return {
            "model": model,
            "state": "open" if retry_after > 0 else "closed",
            "failures": failures,
            "retry_after_seconds": retry_after,
        }


class ResilientProvider:
    """Retries transient provider failures and reports how many attempts were needed."""

    def __init__(
        self,
        provider: CompletionProvider,
        retry_attempts: int,
        breaker: CircuitBreaker,
    ) -> None:
        self.provider = provider
        self.retry_attempts = retry_attempts
        self.breaker = breaker

    def complete(
        self,
        model: str,
        prompt: str,
        system_prompt: str | None = None,
        response_schema: dict | None = None,
    ) -> tuple[ProviderResult, int]:
        last_error: ProviderUnavailable | None = None
        for attempt in range(self.retry_attempts + 1):
            try:
                if hasattr(self.provider, "complete_with_usage"):
                    answer = self.provider.complete_with_usage(
                        model, prompt, system_prompt, response_schema
                    )
                else:
                    answer = ProviderResult(
                        self.provider.complete(model, prompt, system_prompt, response_schema)
                    )
                self.breaker.record_success(model)
                return answer, attempt
            except ProviderUnavailable as error:
                last_error = error
        self.breaker.record_failure(model)
        raise last_error or ProviderUnavailable("Provider failed without a response.")
