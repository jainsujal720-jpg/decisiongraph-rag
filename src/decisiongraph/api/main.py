import secrets
import time
import uuid
from dataclasses import asdict
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from botocore.exceptions import BotoCoreError, ClientError
from neo4j.exceptions import Neo4jError
from openai import OpenAIError
from psycopg import Error as PostgresError
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from decisiongraph import __version__
from decisiongraph.cloud.s3_uploads import CloudUploadError, S3CloudUploads
from decisiongraph.core.config import get_settings
from decisiongraph.generation.service import (
    GroundedAnswerService,
    OpenAIAnswerModels,
    RelayGuardAnswerModels,
)
from decisiongraph.graph.extraction import OpenAIGraphExtractor
from decisiongraph.graph.service import GraphService
from decisiongraph.graph.store import Neo4jGraphStore
from decisiongraph.infrastructure.health import readiness_report
from decisiongraph.ingestion.chunking import StructureAwareChunker
from decisiongraph.ingestion.parsers import parse_document
from decisiongraph.knowledge.embeddings import OpenAIEmbeddingProvider
from decisiongraph.knowledge.service import KnowledgeService
from decisiongraph.knowledge.store import PostgresKnowledgeStore
from decisiongraph.operations.auth import authenticate_bearer_token, authorize_request
from decisiongraph.operations.security import FixedWindowRateLimiter, RedisFixedWindowRateLimiter
from decisiongraph.operations.service import EvaluationService
from decisiongraph.operations.store import PostgresOperationsStore
from decisiongraph.orchestration.service import RetrievalOrchestrator

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Enterprise hybrid vector, keyword and knowledge-graph RAG platform.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    tenant_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    allowed_scopes: list[str] = Field(default_factory=lambda: ["private", "team", "company"])
    limit: int = Field(default=settings.retrieval_default_limit, ge=1, le=25)


class GraphEnrichmentRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=100)
    tenant_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    allowed_scopes: list[str] = Field(default_factory=lambda: ["private", "team", "company"])


class GraphSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    tenant_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    allowed_scopes: list[str] = Field(default_factory=lambda: ["private", "team", "company"])
    limit: int = Field(default=10, ge=1, le=50)


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    tenant_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    allowed_scopes: list[str] = Field(default_factory=lambda: ["private", "team", "company"])
    limit: int = Field(default=8, ge=1, le=25)


class AnswerRequest(RetrieveRequest):
    """A question answered only with claims that pass evidence verification."""


class EvaluationCase(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    expected_decision: Literal["answered", "abstained"] = "answered"
    expected_terms: list[str] = Field(default_factory=list, max_length=10)
    expected_source: str | None = Field(default=None, max_length=300)


class EvaluationRequest(BaseModel):
    cases: list[EvaluationCase] = Field(min_length=1, max_length=50)
    tenant_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    allowed_scopes: list[str] = Field(default_factory=lambda: ["private", "team", "company"])
    limit: int = Field(default=8, ge=1, le=25)


class ReviewResolutionRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=200)
    reviewer_id: str = Field(min_length=1, max_length=200)
    outcome: Literal["approved", "rejected"]
    notes: str | None = Field(default=None, max_length=2000)


class DocumentAccessRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=200)
    actor_id: str = Field(min_length=1, max_length=200)
    access_scope: Literal["private", "team", "company"]


class CloudUploadRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=200)
    owner_id: str = Field(min_length=1, max_length=200)
    access_scope: Literal["private", "team", "company"] = "team"
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=150)
    size_bytes: int = Field(ge=1, le=20 * 1024 * 1024)
    checksum_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class CloudUploadAccess(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=200)
    owner_id: str = Field(min_length=1, max_length=200)
    enrich_graph: bool = False


@lru_cache
def get_knowledge_service() -> KnowledgeService:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    provider = OpenAIEmbeddingProvider(
        settings.openai_api_key,
        settings.embedding_model,
        settings.embedding_dimensions,
        settings.embedding_batch_size,
    )
    return KnowledgeService(
        PostgresKnowledgeStore(settings.postgres_url),
        provider,
        settings.retrieval_candidate_limit,
        settings.rrf_constant,
    )


@lru_cache
def get_cloud_uploads() -> S3CloudUploads:
    if not settings.cloud_s3_bucket:
        raise ValueError("Cloud S3 is not configured")
    return S3CloudUploads(settings.postgres_url, settings.cloud_s3_bucket,
                          settings.cloud_s3_region, get_knowledge_service())


@lru_cache
def get_graph_service() -> GraphService:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    return GraphService(
        PostgresKnowledgeStore(settings.postgres_url),
        Neo4jGraphStore(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password),
        OpenAIGraphExtractor(settings.openai_api_key, settings.extraction_model),
        settings.graph_max_chunks_per_request,
    )


@lru_cache
def get_retrieval_orchestrator() -> RetrievalOrchestrator:
    return RetrievalOrchestrator(
        get_knowledge_service(),
        get_graph_service(),
        candidate_limit=settings.orchestration_candidate_limit,
        context_max_tokens=settings.context_max_tokens,
    )


@lru_cache
def get_answer_service() -> GroundedAnswerService:
    if not settings.relayguard_enabled and not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    answer_models = (
        RelayGuardAnswerModels(
            settings.relayguard_url or "",
            settings.relayguard_api_key,
            settings.relayguard_timeout_seconds,
            settings.causal_draft_optimization,
        )
        if settings.relayguard_enabled
        else OpenAIAnswerModels(
            settings.openai_api_key or "",
            settings.generation_model,
            settings.verification_model,
        )
    )
    return GroundedAnswerService(
        get_retrieval_orchestrator(),
        answer_models,
        min_groundedness=settings.min_groundedness,
        max_claims=settings.answer_max_claims,
    )


@lru_cache
def get_operations_store() -> PostgresOperationsStore:
    return PostgresOperationsStore(settings.postgres_url)


@lru_cache
def get_evaluation_service() -> EvaluationService:
    return EvaluationService(get_answer_service())


@lru_cache
def get_rate_limiter():
    if settings.rate_limit_backend == "redis":
        return RedisFixedWindowRateLimiter(
            settings.redis_url,
            settings.rate_limit_requests_per_minute,
        )
    return FixedWindowRateLimiter(settings.rate_limit_requests_per_minute)


@app.middleware("http")
async def apply_api_guardrails(request: Request, call_next):
    # Browsers do not attach bearer credentials to CORS preflight requests.
    # Let CORSMiddleware answer OPTIONS before any API authentication check.
    if request.method == "OPTIONS":
        return await call_next(request)
    if not request.url.path.startswith("/v1/"):
        return await call_next(request)
    if settings.api_access_key:
        provided_key = request.headers.get("x-api-key", "")
        if not secrets.compare_digest(provided_key, settings.api_access_key):
            return JSONResponse({"detail": "Invalid API key"}, status_code=401)
    try:
        context = authenticate_bearer_token(request, settings)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    request.state.auth_context = context
    request_id = request.headers.get("x-request-id") or secrets.token_urlsafe(12)
    rate_identity = context.subject or (request.client.host if request.client else "unknown")
    try:
        if not get_rate_limiter().allow(rate_identity):
            return JSONResponse(
                {"detail": "Rate limit exceeded; try again shortly.", "request_id": request_id},
                status_code=429,
            )
    except Exception:
        return JSONResponse(
            {"detail": "Rate-limit service is unavailable", "request_id": request_id},
            status_code=503,
        )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "version": __version__,
        "docs": "/docs",
    }


@app.get("/health/live")
def liveness() -> dict[str, str]:
    """Confirms that the API process itself is alive."""
    return {"status": "alive", "version": __version__}


@app.get("/health/ready")
def readiness(response: Response) -> dict:
    """Confirms that all required infrastructure dependencies are reachable."""
    report = readiness_report(settings)
    if report["status"] != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report


@app.post("/v1/ingestion/preview")
async def preview_ingestion(file: Annotated[UploadFile, File()]) -> dict:
    """Parse and chunk one document without persisting or embedding it."""
    data = await file.read()
    try:
        document = parse_document(file.filename or "document", data, file.content_type)
        result = StructureAwareChunker().chunk(document)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {
        "document": {
            "filename": document.filename,
            "media_type": document.media_type,
            "checksum_sha256": document.checksum_sha256,
            "block_count": len(document.blocks),
        },
        "chunking": {
            "parent_count": len(result.parents),
            "child_count": len(result.children),
            "parents": [asdict(chunk) for chunk in result.parents],
            "children": [asdict(chunk) for chunk in result.children],
        },
    }


@app.post("/v1/documents")
async def ingest_document(
    request: Request,
    file: Annotated[UploadFile, File()],
    tenant_id: Annotated[str, Form()],
    owner_id: Annotated[str, Form()],
    access_scope: Annotated[str, Form()] = "team",
) -> dict:
    """Parse, chunk, embed and persist a versioned document."""
    try:
        authorize_request(request, tenant_id, owner_id, [access_scope], "editor")
        service = get_knowledge_service()
        data = await file.read()
        result = await run_in_threadpool(
            service.ingest,
            file.filename or "document",
            data,
            file.content_type,
            tenant_id,
            owner_id,
            access_scope,
        )
    except ValueError as exc:
        code = status.HTTP_503_SERVICE_UNAVAILABLE if "OPENAI_API_KEY" in str(exc) else 400
        raise HTTPException(code, str(exc)) from exc
    except OpenAIError as exc:
        raise HTTPException(502, "Embedding provider request failed") from exc
    except PostgresError as exc:
        raise HTTPException(503, "Knowledge database is unavailable") from exc
    return asdict(result)


@app.get("/v1/cloud/config")
def cloud_config() -> dict:
    """Report whether cloud upload is enabled without exposing a bucket or credentials."""
    return {"enabled": bool(settings.cloud_s3_bucket), "provider": "s3"}


@app.post("/v1/cloud/uploads")
def prepare_cloud_upload(payload: CloudUploadRequest, request: Request) -> dict:
    authorize_request(request, payload.tenant_id, payload.owner_id,
                      [payload.access_scope], "editor")
    try:
        return get_cloud_uploads().prepare(
            payload.tenant_id, payload.owner_id, payload.access_scope,
            payload.filename, payload.content_type, payload.size_bytes,
            payload.checksum_sha256,
        )
    except CloudUploadError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (ValueError, PostgresError, ClientError, BotoCoreError) as exc:
        raise HTTPException(503, "Cloud upload service is unavailable") from exc


@app.post("/v1/cloud/uploads/{upload_id}/complete")
async def complete_cloud_upload(
    upload_id: uuid.UUID, payload: CloudUploadAccess, request: Request,
) -> dict:
    authorize_request(request, payload.tenant_id, payload.owner_id, None, "editor")
    try:
        result = await run_in_threadpool(
            get_cloud_uploads().finish, upload_id, payload.tenant_id, payload.owner_id
        )
        if payload.enrich_graph:
            try:
                graph = await run_in_threadpool(
                    get_graph_service().enrich, result["document_id"], payload.tenant_id,
                    payload.owner_id, [result["access_scope"]],
                )
                result["graph_chunks"] = graph.processed_chunks
                result["graph_status"] = "ready"
            except (ValueError, PostgresError, OpenAIError, Neo4jError):
                # The already indexed vector document remains available.
                result["graph_status"] = "failed"
        return result
    except CloudUploadError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, PostgresError, ClientError, BotoCoreError, OpenAIError, Neo4jError) as exc:
        raise HTTPException(503, "Cloud upload verification or indexing failed") from exc


@app.get("/v1/cloud/uploads/{upload_id}")
def cloud_upload_status(
    upload_id: uuid.UUID, request: Request, tenant_id: str, owner_id: str,
) -> dict:
    authorize_request(request, tenant_id, owner_id, None, "editor")
    try:
        record = get_cloud_uploads().status(upload_id, tenant_id, owner_id)
    except (ValueError, PostgresError) as exc:
        raise HTTPException(503, "Cloud upload service is unavailable") from exc
    if not record:
        raise HTTPException(404, "Cloud upload not found")
    return record


@app.get("/v1/documents")
def list_documents(
    request: Request,
    tenant_id: str,
    user_id: str,
    allowed_scopes: str = "team",
    limit: int = 50,
) -> dict:
    """List only documents the calling user is permitted to inspect."""
    scopes = [item.strip() for item in allowed_scopes.split(",") if item.strip()]
    if not 1 <= limit <= 100:
        raise HTTPException(400, "limit must be between 1 and 100")
    try:
        authorize_request(request, tenant_id, user_id, scopes, "reader")
        documents = get_knowledge_service().store.list_documents(tenant_id, user_id, scopes, limit)
    except (PostgresError, ValueError) as exc:
        raise HTTPException(503, "Document catalog is unavailable") from exc
    return {
        "tenant_id": tenant_id,
        "count": len(documents),
        "items": [asdict(item) for item in documents],
    }


@app.get("/v1/documents/{document_id}")
def get_document(
    document_id: str, request: Request, tenant_id: str, user_id: str, allowed_scopes: str = "team"
) -> dict:
    scopes = [item.strip() for item in allowed_scopes.split(",") if item.strip()]
    try:
        authorize_request(request, tenant_id, user_id, scopes, "reader")
        document = get_knowledge_service().store.document_detail(
            document_id, tenant_id, user_id, scopes
        )
    except (PostgresError, ValueError) as exc:
        raise HTTPException(503, "Document catalog is unavailable") from exc
    if not document:
        raise HTTPException(404, "Document was not found or is not accessible")
    return asdict(document)


@app.post("/v1/documents/{document_id}/reindex")
def reindex_document(
    document_id: str, request: DocumentAccessRequest, http_request: Request
) -> dict:
    """Re-embed the latest document chunks and append an immutable audit event."""
    try:
        authorize_request(http_request, request.tenant_id, request.actor_id, None, "editor")
        child_chunks = get_knowledge_service().reindex(
            document_id, request.tenant_id, request.actor_id
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except OpenAIError as exc:
        raise HTTPException(502, "Embedding provider request failed") from exc
    except PostgresError as exc:
        raise HTTPException(503, "Document catalog is unavailable") from exc
    return {"document_id": document_id, "status": "reindexed", "child_chunks": child_chunks}


@app.post("/v1/documents/{document_id}/access")
def change_document_access(
    document_id: str, request: DocumentAccessRequest, http_request: Request
) -> dict:
    try:
        authorize_request(
            http_request, request.tenant_id, request.actor_id, [request.access_scope], "editor"
        )
        document = get_knowledge_service().store.update_access(
            document_id, request.tenant_id, request.access_scope, request.actor_id
        )
    except (PostgresError, ValueError) as exc:
        raise HTTPException(503, "Document catalog is unavailable") from exc
    if not document:
        raise HTTPException(404, "Document was not found")
    return asdict(document)


@app.delete("/v1/documents/{document_id}")
def delete_document(
    document_id: str, request: DocumentAccessRequest, http_request: Request
) -> dict:
    """Delete PostgreSQL chunks and corresponding Neo4j graph evidence for a document."""
    try:
        authorize_request(http_request, request.tenant_id, request.actor_id, None, "editor")
        deleted = get_knowledge_service().store.delete_document(
            document_id, request.tenant_id, request.actor_id
        )
        if deleted:
            get_graph_service().delete_document(request.tenant_id, document_id)
    except (PostgresError, Neo4jError, ValueError) as exc:
        raise HTTPException(503, "Document deletion infrastructure is unavailable") from exc
    if not deleted:
        raise HTTPException(404, "Document was not found")
    return {"document_id": document_id, "status": "deleted"}


@app.post("/v1/search")
def hybrid_search(request: SearchRequest, http_request: Request) -> dict:
    """Search vector and keyword indexes, then merge ranks using RRF."""
    try:
        authorize_request(
            http_request, request.tenant_id, request.user_id, request.allowed_scopes, "reader"
        )
        service = get_knowledge_service()
        hits = service.search(
            request.query,
            request.tenant_id,
            request.user_id,
            request.allowed_scopes,
            request.limit,
        )
    except ValueError as exc:
        code = status.HTTP_503_SERVICE_UNAVAILABLE if "OPENAI_API_KEY" in str(exc) else 400
        raise HTTPException(code, str(exc)) from exc
    except OpenAIError as exc:
        raise HTTPException(502, "Embedding provider request failed") from exc
    except PostgresError as exc:
        raise HTTPException(503, "Knowledge database is unavailable") from exc
    return {
        "query": request.query,
        "strategy": "vector + PostgreSQL full-text + reciprocal-rank fusion",
        "result_count": len(hits),
        "results": [asdict(hit) for hit in hits],
    }


@app.post("/v1/graph/enrich")
def enrich_graph(request: GraphEnrichmentRequest, http_request: Request) -> dict:
    """Extract a document's evidence-linked entities and relationships into Neo4j."""
    try:
        authorize_request(
            http_request, request.tenant_id, request.user_id, request.allowed_scopes, "editor"
        )
        result = get_graph_service().enrich(
            request.document_id,
            request.tenant_id,
            request.user_id,
            request.allowed_scopes,
        )
    except ValueError as exc:
        code = status.HTTP_503_SERVICE_UNAVAILABLE if "OPENAI_API_KEY" in str(exc) else 400
        raise HTTPException(code, str(exc)) from exc
    except OpenAIError as exc:
        raise HTTPException(502, "Graph extraction provider request failed") from exc
    except PostgresError as exc:
        raise HTTPException(503, "Knowledge database is unavailable") from exc
    except Neo4jError as exc:
        raise HTTPException(503, "Graph database is unavailable") from exc
    return asdict(result)


@app.post("/v1/graph/search")
def graph_search(request: GraphSearchRequest, http_request: Request) -> dict:
    """Search authorized entities and evidence-backed graph relationships."""
    try:
        authorize_request(
            http_request, request.tenant_id, request.user_id, request.allowed_scopes, "reader"
        )
        hits = get_graph_service().search(
            request.query,
            request.tenant_id,
            request.user_id,
            request.allowed_scopes,
            request.limit,
        )
    except ValueError as exc:
        code = status.HTTP_503_SERVICE_UNAVAILABLE if "OPENAI_API_KEY" in str(exc) else 400
        raise HTTPException(code, str(exc)) from exc
    except Neo4jError as exc:
        raise HTTPException(503, "Graph database is unavailable") from exc
    return {
        "query": request.query,
        "result_count": len(hits),
        "results": [asdict(hit) for hit in hits],
    }


@app.post("/v1/retrieve")
def retrieve_evidence(request: RetrieveRequest, http_request: Request) -> dict:
    """Route, fuse, rerank and assemble citation-ready evidence without generating an answer."""
    try:
        authorize_request(
            http_request, request.tenant_id, request.user_id, request.allowed_scopes, "reader"
        )
        result = get_retrieval_orchestrator().retrieve(
            request.query,
            request.tenant_id,
            request.user_id,
            request.allowed_scopes,
            request.limit,
        )
    except ValueError as exc:
        code = status.HTTP_503_SERVICE_UNAVAILABLE if "OPENAI_API_KEY" in str(exc) else 400
        raise HTTPException(code, str(exc)) from exc
    except OpenAIError as exc:
        raise HTTPException(502, "Retrieval provider request failed") from exc
    except (PostgresError, Neo4jError) as exc:
        raise HTTPException(503, "Retrieval infrastructure is unavailable") from exc
    return {
        "query": result.query,
        "route": result.plan.route,
        "route_reason": result.plan.reason,
        "evidence_count": len(result.evidence),
        "evidence": [asdict(item) for item in result.evidence],
        "context": result.context,
        "context_token_estimate": result.context_token_estimate,
    }


@app.post("/v1/answers")
def answer_question(request: AnswerRequest, http_request: Request) -> dict:
    """Generate a citation-verified answer or abstain when the evidence is insufficient."""
    started_at = time.perf_counter()
    try:
        authorize_request(
            http_request, request.tenant_id, request.user_id, request.allowed_scopes, "reader"
        )
        result = get_answer_service().answer(
            request.query,
            request.tenant_id,
            request.user_id,
            request.allowed_scopes,
            request.limit,
        )
    except ValueError as exc:
        code = status.HTTP_503_SERVICE_UNAVAILABLE if "OPENAI_API_KEY" in str(exc) else 400
        raise HTTPException(code, str(exc)) from exc
    except OpenAIError as exc:
        raise HTTPException(502, "Answer generation or verification request failed") from exc
    except (PostgresError, Neo4jError) as exc:
        raise HTTPException(503, "Answer retrieval infrastructure is unavailable") from exc
    payload = asdict(result)
    latency_ms = round((time.perf_counter() - started_at) * 1000)
    event_id = None
    try:
        event_id = get_operations_store().record_answer(
            request.tenant_id,
            request.user_id,
            request.query,
            result.route,
            result.decision,
            latency_ms,
            [item["chunk_id"] for item in result.citations],
            asdict(result.confidence),
        )
        needs_review = (
            result.decision == "abstained"
            or result.confidence.overall < settings.review_confidence_threshold
        )
        if needs_review:
            review_reason = (
                "abstained: insufficient verified evidence"
                if result.decision == "abstained"
                else "confidence below review threshold"
            )
            payload["review"] = asdict(
                get_operations_store().create_review(
                    event_id,
                    request.tenant_id,
                    request.user_id,
                    request.query,
                    review_reason,
                    result.answer if result.decision == "answered" else None,
                    asdict(result.confidence),
                )
            )
        else:
            payload["review"] = None
    except (PostgresError, ValueError) as exc:
        if settings.audit_required:
            raise HTTPException(503, "Answer audit store is unavailable") from exc
        payload["audit_warning"] = "Answer was not persisted to the audit trail."
        payload["review"] = None
    payload["latency_ms"] = latency_ms
    return payload


@app.get("/v1/reviews")
def list_reviews(
    request: Request,
    tenant_id: str,
    review_status: Literal["pending", "approved", "rejected"] = "pending",
    limit: int = 20,
) -> dict:
    """List human-review items for a tenant; reviewer authorization belongs at the gateway."""
    if not 1 <= limit <= 100:
        raise HTTPException(400, "limit must be between 1 and 100")
    try:
        authorize_request(request, tenant_id, None, None, "reviewer")
        reviews = get_operations_store().list_reviews(tenant_id, review_status, limit)
    except PostgresError as exc:
        raise HTTPException(503, "Review store is unavailable") from exc
    return {
        "tenant_id": tenant_id,
        "review_status": review_status,
        "items": [asdict(item) for item in reviews],
    }


@app.get("/v1/metrics")
def operational_metrics(tenant_id: str, request: Request) -> dict:
    """Return tenant-scoped answer volume, outcomes, latency and pending-review metrics."""
    try:
        authorize_request(request, tenant_id, None, None, "operator")
        metrics = get_operations_store().metrics(tenant_id)
    except PostgresError as exc:
        raise HTTPException(503, "Metrics store is unavailable") from exc
    return asdict(metrics)


@app.post("/v1/reviews/{review_id}/resolve")
def resolve_review(review_id: str, request: ReviewResolutionRequest, http_request: Request) -> dict:
    """Record a reviewer decision; production must enforce reviewer privileges upstream."""
    try:
        authorize_request(http_request, request.tenant_id, request.reviewer_id, None, "reviewer")
        item = get_operations_store().resolve_review(
            review_id,
            request.tenant_id,
            request.reviewer_id,
            request.outcome,
            request.notes,
        )
    except (PostgresError, ValueError) as exc:
        raise HTTPException(503, "Review store is unavailable") from exc
    if not item:
        raise HTTPException(404, "Pending review item was not found")
    return asdict(item)


@app.post("/v1/evaluations/run")
def run_evaluation(request: EvaluationRequest, http_request: Request) -> dict:
    """Run a bounded regression set and return answer, decision and source metrics."""
    try:
        authorize_request(
            http_request, request.tenant_id, request.user_id, request.allowed_scopes, "operator"
        )
        report = get_evaluation_service().run(
            [case.model_dump() for case in request.cases],
            request.tenant_id,
            request.user_id,
            request.allowed_scopes,
            request.limit,
        )
    except ValueError as exc:
        code = status.HTTP_503_SERVICE_UNAVAILABLE if "OPENAI_API_KEY" in str(exc) else 400
        raise HTTPException(code, str(exc)) from exc
    except OpenAIError as exc:
        raise HTTPException(502, "Evaluation model request failed") from exc
    except (PostgresError, Neo4jError) as exc:
        raise HTTPException(503, "Evaluation infrastructure is unavailable") from exc
    return asdict(report)
