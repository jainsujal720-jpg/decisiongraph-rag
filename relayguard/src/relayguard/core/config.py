from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://relayguard:relayguard@localhost:5440/relayguard"
    redis_url: str = "redis://localhost:6380/0"
    provider_mode: str = "mock"
    openai_api_key: str | None = None
    audit_backend: str = "memory"
    rate_limit_backend: str = "memory"
    request_max_input_chars: int = 12_000
    request_limit_per_minute: int = 60
    default_tenant_budget_usd: float = 0.05
    provider_timeout_seconds: float = 60.0
    provider_retry_attempts: int = 2
    circuit_breaker_failure_threshold: int = 2
    circuit_breaker_reset_seconds: int = 30
    circuit_breaker_backend: str = "memory"
    circuit_breaker_namespace: str = "relayguard:circuit"
    auth_mode: str = "off"
    tenant_api_keys: str = '{"demo-acme-operator-key":{"tenant_id":"acme","role":"operator"}}'
    jev_mode: str = "off"  # off, shadow, active
    typesafe_api_key: str | None = None
    jev_model: str = "jev-1.13.0"
    jev_min_confidence: float = 0.80
    jev_timeout_seconds: float = 3.0
    model_config = SettingsConfigDict(env_prefix="RELAYGUARD_", case_sensitive=False)


settings = Settings()
