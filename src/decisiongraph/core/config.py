from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "DecisionGraph RAG"
    app_env: str = "development"
    log_level: str = "INFO"

    postgres_url: str = "postgresql://decisiongraph:decisiongraph@localhost:5432/decisiongraph"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = Field(default="", repr=False)
    redis_url: str = "redis://localhost:6379/0"

    openai_api_key: str | None = Field(default=None, repr=False)
    relayguard_url: str | None = None
    relayguard_api_key: str | None = Field(default=None, repr=False)
    relayguard_timeout_seconds: float = 20.0
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    embedding_batch_size: int = 128
    extraction_model: str = "gpt-4.1-mini"
    generation_model: str = "gpt-4.1-mini"
    verification_model: str = "gpt-4.1-mini"
    graph_max_chunks_per_request: int = 50
    retrieval_candidate_limit: int = 20
    retrieval_default_limit: int = 8
    rrf_constant: int = 60
    orchestration_candidate_limit: int = 12
    context_max_tokens: int = 3000
    answer_max_claims: int = 6
    causal_draft_optimization: bool = False
    min_groundedness: float = 0.75
    review_confidence_threshold: float = 0.80
    audit_required: bool = False
    api_access_key: str | None = Field(default=None, repr=False)
    rate_limit_requests_per_minute: int = 0
    rate_limit_backend: str = "memory"
    auth_mode: str = "development"
    jwt_signing_key: str | None = Field(default=None, repr=False)
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "decisiongraph-local"
    jwt_audience: str = "decisiongraph-api"
    cors_allow_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    cloud_s3_bucket: str | None = None
    cloud_s3_region: str = "ap-south-1"

    @property
    def allowed_cors_origins(self) -> list[str]:
        """Return explicit browser origins permitted to call the local API."""
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def relayguard_enabled(self) -> bool:
        return bool(self.relayguard_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
