import logging
from uuid import uuid4

from fastapi import HTTPException, status

from relayguard.core.models import (
    ChatRequest,
    ChatResponse,
    GovernanceSummary,
    RouteDecision,
    RoutingTrace,
    TaskClass,
    UsageSummary,
)
from relayguard.services.jev import JevRouter
from relayguard.services.pricing import usage_cost
from relayguard.services.providers import CompletionProvider, MockProvider, ProviderUnavailable
from relayguard.services.resilience import CircuitBreaker, RedisCircuitBreaker, ResilientProvider
from relayguard.storage.memory import MemoryAuditStore
from relayguard.storage.postgres import EventStore

logger = logging.getLogger(__name__)


class GatewayService:
    """Core policy, routing, fallback, and audit logic using deterministic local models."""

    complex_words = {"analyse", "analyze", "legal", "contract", "strategy", "reason", "compare"}
    costs = {
        "relay-basic": 0.0004,
        "relay-mid-luna": 0.0002,
        "relay-mid-terra": 0.002,
        "relay-mid-sol": 0.004,
        "relay-mini": 0.0001,
        "relay-pro": 0.002,
        "relay-backup": 0.0004,
    }

    def __init__(
        self,
        audit_store: EventStore | None = None,
        provider: CompletionProvider | None = None,
        rate_limiter: object | None = None,
        max_input_chars: int = 12_000,
        tenant_budget_usd: float = 0.05,
        retry_attempts: int = 2,
        breaker: CircuitBreaker | RedisCircuitBreaker | None = None,
        jev_router: JevRouter | None = None,
        jev_mode: str = "off",
        jev_min_confidence: float = 0.80,
    ) -> None:
        self.audit_store = audit_store or MemoryAuditStore()
        self.provider = provider or MockProvider()
        self.rate_limiter = rate_limiter
        self.max_input_chars = max_input_chars
        self.tenant_budget_usd = tenant_budget_usd
        self.breaker = breaker or CircuitBreaker(failure_threshold=2, reset_seconds=30)
        self.resilient_provider = ResilientProvider(
            provider=self.provider,
            retry_attempts=retry_attempts,
            breaker=self.breaker,
        )
        self.jev_router = jev_router
        self.jev_mode = jev_mode
        self.jev_min_confidence = jev_min_confidence

    def complete(self, request: ChatRequest) -> ChatResponse:
        self._check_policy(request, self.max_input_chars)
        if self.rate_limiter:
            self.rate_limiter.check(request.tenant_id)
        route, routing = self._choose_route(request)
        served_by = route.primary_model
        fallback_used = False
        circuit_open = self.breaker.is_open(route.primary_model)
        retry_count = 0
        tokens = max(1, len(request.prompt.split()))
        if circuit_open:
            served_by = route.fallback_model
            fallback_used = True
        elif request.simulate_primary_failure:
            self.breaker.record_failure(route.primary_model)
            served_by = route.fallback_model
            fallback_used = True
            circuit_open = self.breaker.is_open(route.primary_model)
        cost = round((tokens + 5) / 1000 * self.costs[served_by], 6)
        current_spend = self.audit_store.total_cost(request.tenant_id)
        self._check_budget(current_spend, cost)
        if fallback_used or circuit_open:
            result, retry_count = self.resilient_provider.complete(
                served_by, request.prompt, request.system_prompt, request.response_schema
            )
        else:
            try:
                result, retry_count = self.resilient_provider.complete(
                    served_by, request.prompt, request.system_prompt, request.response_schema
                )
            except ProviderUnavailable:
                served_by = route.fallback_model
                fallback_used = True
                cost = round((tokens + 5) / 1000 * self.costs[served_by], 6)
                self._check_budget(current_spend, cost)
                result, retry_count = self.resilient_provider.complete(
                    served_by, request.prompt, request.system_prompt, request.response_schema
                )
        request_id = str(uuid4())
        actual_model = getattr(self.provider, "model_aliases", {}).get(served_by, served_by)
        measured_cost = usage_cost(
            actual_model, result.input_tokens, result.cached_input_tokens, result.output_tokens
        )
        usage = UsageSummary(
            input_tokens=result.input_tokens,
            cached_input_tokens=result.cached_input_tokens,
            output_tokens=result.output_tokens,
            token_cost_usd=measured_cost,
        )
        self.audit_store.add(
            {
                "request_id": request_id,
                "tenant_id": request.tenant_id,
                "user_id": request.user_id,
                "primary_model": route.primary_model,
                "served_by": served_by,
                "fallback_used": fallback_used,
                "cost_usd": cost,
            }
        )
        if measured_cost is not None:
            try:
                self.audit_store.add_usage(
                    {
                        "request_id": request_id,
                        "tenant_id": request.tenant_id,
                        "model": actual_model,
                        "input_tokens": result.input_tokens,
                        "cached_input_tokens": result.cached_input_tokens,
                        "output_tokens": result.output_tokens,
                        "token_cost_usd": measured_cost,
                        "routing_source": routing.source,
                        "jev_mode": routing.jev_mode,
                        "jev_class": routing.jev_class,
                        "jev_cost_usd": routing.jev_cost_usd,
                    }
                )
            except Exception:
                logger.exception("Usage telemetry storage failed for request %s", request_id)
        return ChatResponse(
            answer=result.answer,
            route=route,
            served_by=served_by,
            served_model=actual_model,
            fallback_used=fallback_used,
            cost_usd=cost,
            usage=usage,
            routing=routing,
            request_id=request_id,
            governance=GovernanceSummary(
                tenant_spend_usd=current_spend,
                tenant_budget_usd=self.tenant_budget_usd,
                remaining_budget_usd=round(self.tenant_budget_usd - current_spend - cost, 6),
                retry_count=retry_count,
                circuit_open=circuit_open,
            ),
        )

    def _choose_route(self, request: ChatRequest) -> tuple[RouteDecision, RoutingTrace]:
        rule_route = self._route(request)
        trace = RoutingTrace(jev_mode=self.jev_mode, reason="Deterministic policy")
        if not self.jev_router or self.jev_mode == "off":
            return rule_route, trace
        try:
            decision = self.jev_router.decide(request.prompt)
        except RuntimeError:
            trace.reason = "Jev unavailable; deterministic policy used"
            return rule_route, trace
        trace.jev_class = decision.task_class.value
        trace.jev_confidence = decision.confidence
        trace.jev_probability = decision.probability
        trace.jev_input_tokens = decision.input_tokens
        if decision.input_tokens is not None:
            trace.jev_cost_usd = round(decision.input_tokens * 0.042 / 1_000_000, 9)
        if self.jev_mode == "shadow":
            trace.reason = "Jev recorded for comparison; deterministic policy served"
            return rule_route, trace
        if min(decision.confidence, decision.probability) < self.jev_min_confidence:
            trace.reason = "Jev uncertain; deterministic policy served"
            return rule_route, trace
        # A caller's task class is a safety floor. Verification never gets downgraded.
        rank = {
            TaskClass.SIMPLE: 0,
            TaskClass.MODERATE: 1,
            TaskClass.INVOLVED: 2,
            TaskClass.COMPLEX: 3,
            TaskClass.HEAVY: 4,
            TaskClass.LONG_CONTEXT: 3,
        }
        if request.task_class and rank[decision.task_class] < rank[request.task_class]:
            trace.reason = "Jev choice below the caller's minimum task class"
            return rule_route, trace
        chosen = self._route(request.model_copy(update={"task_class": decision.task_class}))
        trace.source = "jev"
        trace.reason = "Confident Jev class within caller policy"
        return chosen, trace

    def metrics(self, tenant_id: str) -> dict:
        return self.audit_store.metrics(tenant_id)

    def budget_status(self, tenant_id: str) -> dict:
        spend = self.audit_store.total_cost(tenant_id)
        return {
            "tenant_id": tenant_id,
            "budget_usd": self.tenant_budget_usd,
            "spent_usd": spend,
            "remaining_usd": round(max(0, self.tenant_budget_usd - spend), 6),
        }

    def audit_integrity(self, tenant_id: str) -> dict:
        return self.audit_store.verify_integrity(tenant_id)

    def audit_evidence(self, tenant_id: str) -> dict:
        integrity = self.audit_store.verify_integrity(tenant_id)
        return {
            "tenant_id": tenant_id,
            "integrity": integrity,
            "events": self.audit_store.evidence_events(tenant_id),
        }

    def risk_signals(self, tenant_id: str) -> dict:
        metrics = self.metrics(tenant_id)
        budget = self.budget_status(tenant_id)
        provider_health = self.provider_health()
        integrity = self.audit_integrity(tenant_id)
        signals: list[dict[str, str]] = []
        if metrics["requests"] and metrics["fallbacks"] / metrics["requests"] >= 0.25:
            signals.append(
                {
                    "severity": "warning",
                    "message": "Fallback rate is at least 25%; inspect provider reliability.",
                }
            )
        if budget["spent_usd"] / budget["budget_usd"] >= 0.8:
            signals.append(
                {
                    "severity": "warning",
                    "message": "Tenant has used at least 80% of its budget.",
                }
            )
        if provider_health["status"] == "degraded":
            signals.append(
                {
                    "severity": "warning",
                    "message": "A provider circuit is open; requests use the fallback.",
                }
            )
        if not integrity["verified"]:
            signals.append(
                {
                    "severity": "critical",
                    "message": "Audit hash chain verification failed; investigate the ledger.",
                }
            )
        return {
            "tenant_id": tenant_id,
            "signals": signals,
            "status": "attention" if signals else "healthy",
        }

    def provider_health(self) -> dict[str, object]:
        """Expose circuit state without exposing credentials or provider internals."""
        circuits = [self.breaker.status(model) for model in self.costs]
        return {
            "status": "degraded"
            if any(item["state"] == "open" for item in circuits)
            else "healthy",
            "circuits": circuits,
        }

    def _route(self, request: ChatRequest) -> RouteDecision:
        task = request.task_class or self._classify(request.prompt)
        routes = {
            TaskClass.SIMPLE: ("relay-basic", "relay-mid-luna", "Short, straightforward task."),
            TaskClass.MODERATE: ("relay-mid-luna", "relay-backup", "Focused middle-tier task."),
            TaskClass.INVOLVED: (
                "relay-mid-terra",
                "relay-mid-luna",
                "Multi-part middle-tier task.",
            ),
            TaskClass.COMPLEX: (
                "relay-mid-sol",
                "relay-mid-terra",
                "Complex middle-tier reasoning.",
            ),
            TaskClass.HEAVY: ("relay-pro", "relay-mid-sol", "High-demand reasoning task."),
            TaskClass.LONG_CONTEXT: ("relay-mini", "relay-mid-terra", "Long but focused input."),
        }
        primary, fallback, reason = routes[task]
        return RouteDecision(
            task_class=task, primary_model=primary, fallback_model=fallback, reason=reason
        )

    def _classify(self, prompt: str) -> TaskClass:
        words = set(prompt.lower().replace("?", " ").split())
        reasoning = bool(words & self.complex_words)
        if len(prompt) > 9000:
            return TaskClass.HEAVY if reasoning else TaskClass.LONG_CONTEXT
        if reasoning and len(prompt) > 2400:
            return TaskClass.HEAVY
        if reasoning:
            return TaskClass.COMPLEX
        if len(prompt) > 4000:
            return TaskClass.INVOLVED
        if len(prompt) > 1200:
            return TaskClass.MODERATE
        return TaskClass.SIMPLE

    @staticmethod
    def _check_policy(request: ChatRequest, max_input_chars: int) -> None:
        if len(request.prompt) > max_input_chars:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Prompt exceeds the configured input limit.",
            )
        if "-----BEGIN PRIVATE KEY-----" in request.prompt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request blocked: possible private key detected.",
            )

    def _check_budget(self, current_spend: float, estimated_cost: float) -> None:
        if current_spend + estimated_cost > self.tenant_budget_usd:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Tenant budget would be exceeded; request was not sent to a model.",
            )
