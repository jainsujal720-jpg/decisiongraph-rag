from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from relayguard.core.config import settings
from relayguard.core.models import ChatRequest, ChatResponse
from relayguard.services.gateway import GatewayService
from relayguard.services.providers import MockProvider, OpenAIProvider, ProviderUnavailable
from relayguard.services.jev import JevRouter
from relayguard.services.rate_limit import MemoryRateLimiter, RedisRateLimiter
from relayguard.services.resilience import CircuitBreaker, RedisCircuitBreaker
from relayguard.services.auth import TenantAuthenticator
from relayguard.storage.memory import MemoryAuditStore
from relayguard.storage.postgres import PostgresAuditStore

app = FastAPI(title="RelayGuard", version="0.6.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3100"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def build_gateway() -> GatewayService:
    if settings.jev_mode not in ("off", "shadow", "active"):
        raise ValueError("RELAYGUARD_JEV_MODE must be off, shadow, or active")
    if settings.jev_mode != "off" and not settings.typesafe_api_key:
        raise ValueError("TYPESAFE_API_KEY required when Jev routing is enabled")
    audit_store = (
        PostgresAuditStore(settings.database_url)
        if settings.audit_backend == "postgres"
        else MemoryAuditStore()
    )
    rate_limiter = (
        RedisRateLimiter(settings.redis_url, settings.request_limit_per_minute)
        if settings.rate_limit_backend == "redis"
        else MemoryRateLimiter(settings.request_limit_per_minute)
    )
    provider = (
        OpenAIProvider(settings.openai_api_key, settings.provider_timeout_seconds)
        if settings.provider_mode == "openai" and settings.openai_api_key
        else MockProvider()
    )
    breaker = (
        RedisCircuitBreaker(
            redis_url=settings.redis_url,
            failure_threshold=settings.circuit_breaker_failure_threshold,
            reset_seconds=settings.circuit_breaker_reset_seconds,
            namespace=settings.circuit_breaker_namespace,
        )
        if settings.circuit_breaker_backend == "redis"
        else CircuitBreaker(
            failure_threshold=settings.circuit_breaker_failure_threshold,
            reset_seconds=settings.circuit_breaker_reset_seconds,
        )
    )
    return GatewayService(
        audit_store=audit_store,
        provider=provider,
        rate_limiter=rate_limiter,
        max_input_chars=settings.request_max_input_chars,
        tenant_budget_usd=settings.default_tenant_budget_usd,
        retry_attempts=settings.provider_retry_attempts,
        breaker=breaker,
        jev_router=JevRouter(settings.typesafe_api_key, settings.jev_model,
                             settings.jev_timeout_seconds) if settings.jev_mode != "off" else None,
        jev_mode=settings.jev_mode,
        jev_min_confidence=settings.jev_min_confidence,
    )


gateway = build_gateway()
authenticator = TenantAuthenticator(settings.auth_mode, settings.tenant_api_keys)


@app.exception_handler(ProviderUnavailable)
def provider_unavailable(_: Request, __: ProviderUnavailable) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": "No approved model provider is currently available."},
    )


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "live"}


@app.post("/v1/chat/completions", response_model=ChatResponse)
def complete(request: ChatRequest, x_api_key: str | None = Header(default=None)) -> ChatResponse:
    principal = authenticator.authenticate(x_api_key, request.tenant_id)
    if request.requires_privileged_access:
        authenticator.require_operator(principal)
    return gateway.complete(request)


@app.get("/v1/metrics")
def metrics(tenant_id: str, x_api_key: str | None = Header(default=None)) -> dict:
    authenticator.authenticate(x_api_key, tenant_id)
    return {"tenant_id": tenant_id, **gateway.metrics(tenant_id)}


@app.get("/v1/budget")
def budget(tenant_id: str, x_api_key: str | None = Header(default=None)) -> dict:
    authenticator.authenticate(x_api_key, tenant_id)
    return gateway.budget_status(tenant_id)


@app.get("/v1/audit/integrity")
def audit_integrity(tenant_id: str, x_api_key: str | None = Header(default=None)) -> dict:
    authenticator.authenticate(x_api_key, tenant_id)
    return gateway.audit_integrity(tenant_id)


@app.get("/v1/audit/evidence")
def audit_evidence(tenant_id: str, x_api_key: str | None = Header(default=None)) -> dict:
    principal = authenticator.authenticate(x_api_key, tenant_id)
    authenticator.require_operator(principal)
    return gateway.audit_evidence(tenant_id)


@app.get("/v1/governance/signals")
def governance_signals(tenant_id: str, x_api_key: str | None = Header(default=None)) -> dict:
    principal = authenticator.authenticate(x_api_key, tenant_id)
    authenticator.require_operator(principal)
    return gateway.risk_signals(tenant_id)


@app.get("/v1/providers/health")
def provider_health(x_api_key: str | None = Header(default=None)) -> dict[str, object]:
    authenticator.authenticate(x_api_key)
    return gateway.provider_health()


@app.get("/v1/whoami")
def whoami(x_api_key: str | None = Header(default=None)) -> dict[str, str]:
    principal = authenticator.authenticate(x_api_key)
    return {"tenant_id": principal.tenant_id, "role": principal.role}
