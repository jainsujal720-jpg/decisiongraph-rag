import asyncio
import time

import httpx
import jwt

from decisiongraph.api.main import app
from decisiongraph.generation.models import AnswerResult, ConfidenceScore, VerifiedClaim
from decisiongraph.graph.models import GraphEnrichmentResult, GraphHit
from decisiongraph.knowledge.models import IngestionResult, SearchHit
from decisiongraph.orchestration.models import EvidenceItem, RetrievalPlan, RetrievalResponse


async def api_get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def api_options(path: str, headers: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.options(path, headers=headers)


async def api_post_file(path: str, filename: str, content: bytes) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, files={"file": (filename, content)})


async def api_post_document(path: str, filename: str, content: bytes) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            path,
            files={"file": (filename, content)},
            data={"tenant_id": "acme", "owner_id": "u1", "access_scope": "team"},
        )


async def api_post_json(path: str, body: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=body)


async def api_post_json_with_headers(path: str, body: dict, headers: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=body, headers=headers)


def test_root_exposes_service_metadata():
    response = asyncio.run(api_get("/"))
    assert response.status_code == 200
    assert response.json()["service"] == "DecisionGraph RAG"
    assert response.json()["docs"] == "/docs"


def test_liveness_does_not_depend_on_databases():
    response = asyncio.run(api_get("/health/live"))
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_v1_responses_include_request_and_browser_security_headers(monkeypatch):
    response = asyncio.run(
        api_post_json("/v1/search", {"query": "Atlas", "tenant_id": "acme", "user_id": "u1"})
    )
    assert response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_dashboard_origin_has_an_explicit_cors_preflight_response():
    response = asyncio.run(
        api_options(
            "/v1/answers",
            {
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-api-key",
            },
        )
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_jwt_mode_allows_browser_preflight_without_a_bearer_token(monkeypatch):
    monkeypatch.setattr("decisiongraph.api.main.settings.auth_mode", "jwt")
    response = asyncio.run(
        api_options(
            "/v1/metrics",
            {
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_api_access_key_protects_v1_endpoints_when_configured(monkeypatch):
    monkeypatch.setattr("decisiongraph.api.main.settings.api_access_key", "test-access-key")
    response = asyncio.run(
        api_post_json(
            "/v1/answers",
            {"query": "Question", "tenant_id": "acme", "user_id": "u1"},
        )
    )
    assert response.status_code == 401
    response = asyncio.run(
        api_post_json_with_headers(
            "/v1/answers",
            {"query": "Question", "tenant_id": "acme", "user_id": "u1"},
            {"X-API-Key": "test-access-key"},
        )
    )
    assert response.status_code != 401


def test_jwt_mode_denies_cross_tenant_request_before_model_work(monkeypatch):
    key = "stage-nine-test-key-with-at-least-thirty-two-characters"
    monkeypatch.setattr("decisiongraph.api.main.settings.auth_mode", "jwt")
    monkeypatch.setattr("decisiongraph.api.main.settings.jwt_signing_key", key)
    token = jwt.encode(
        {
            "sub": "u1",
            "tenant_id": "acme",
            "roles": ["reader"],
            "scope": "team",
            "iss": "decisiongraph-local",
            "aud": "decisiongraph-api",
            "exp": int(time.time()) + 60,
        },
        key,
        algorithm="HS256",
    )
    response = asyncio.run(
        api_post_json_with_headers(
            "/v1/search",
            {"query": "Atlas", "tenant_id": "other", "user_id": "u1", "allowed_scopes": ["team"]},
            {"Authorization": f"Bearer {token}"},
        )
    )
    assert response.status_code == 403
    assert "tenant" in response.json()["detail"]


def test_readiness_reports_all_dependencies(monkeypatch):
    expected = {
        "status": "ready",
        "components": [
            {"name": "postgres", "status": "up", "latency_ms": 1.0, "detail": None},
            {"name": "neo4j", "status": "up", "latency_ms": 2.0, "detail": None},
            {"name": "redis", "status": "up", "latency_ms": 1.0, "detail": None},
        ],
    }
    monkeypatch.setattr("decisiongraph.api.main.readiness_report", lambda settings: expected)
    response = asyncio.run(api_get("/health/ready"))
    assert response.status_code == 200
    assert response.json() == expected


def test_readiness_returns_503_when_a_dependency_is_down(monkeypatch):
    report = {
        "status": "degraded",
        "components": [
            {
                "name": "postgres",
                "status": "down",
                "latency_ms": 3.0,
                "detail": "OperationalError",
            }
        ],
    }
    monkeypatch.setattr("decisiongraph.api.main.readiness_report", lambda settings: report)
    response = asyncio.run(api_get("/health/ready"))
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_ingestion_preview_returns_provenance_and_chunks():
    response = asyncio.run(
        api_post_file(
            "/v1/ingestion/preview",
            "status.md",
            b"# Atlas\n\nPayment testing delayed the launch.",
        )
    )
    assert response.status_code == 200
    body = response.json()
    assert body["document"]["filename"] == "status.md"
    assert body["document"]["block_count"] == 2
    assert body["chunking"]["parent_count"] == 1
    assert body["chunking"]["children"][0]["section_path"] == ["Atlas"]


def test_ingestion_preview_rejects_unsupported_file():
    response = asyncio.run(api_post_file("/v1/ingestion/preview", "malware.exe", b"data"))
    assert response.status_code == 400


class FakeKnowledgeService:
    def ingest(self, filename, *_args):
        return IngestionResult("doc-1", "version-1", filename, 2, 3, False)

    def search(self, *_args):
        return [
            SearchHit(
                "chunk-1",
                "doc-1",
                "atlas.md",
                "payment testing",
                "full decision context",
                ("Atlas", "Decision"),
                (),
                1,
                2,
                0.91,
                0.7,
                0.0325,
            )
        ]


def test_document_ingestion_and_hybrid_search(monkeypatch):
    monkeypatch.setattr("decisiongraph.api.main.get_knowledge_service", FakeKnowledgeService)
    ingestion = asyncio.run(api_post_document("/v1/documents", "atlas.md", b"# Atlas"))
    assert ingestion.status_code == 200
    assert ingestion.json()["child_chunks"] == 3

    search = asyncio.run(
        api_post_json(
            "/v1/search",
            {
                "query": "Why was launch delayed?",
                "tenant_id": "acme",
                "user_id": "u1",
                "allowed_scopes": ["team"],
                "limit": 5,
            },
        )
    )
    assert search.status_code == 200
    assert search.json()["results"][0]["source_name"] == "atlas.md"
    assert "reciprocal-rank fusion" in search.json()["strategy"]


def test_knowledge_endpoints_return_configuration_error(monkeypatch):
    def unavailable():
        raise ValueError("OPENAI_API_KEY is not configured")

    monkeypatch.setattr("decisiongraph.api.main.get_knowledge_service", unavailable)
    ingestion = asyncio.run(api_post_document("/v1/documents", "atlas.md", b"# Atlas"))
    assert ingestion.status_code == 503
    search = asyncio.run(
        api_post_json(
            "/v1/search",
            {"query": "launch", "tenant_id": "acme", "user_id": "u1"},
        )
    )
    assert search.status_code == 503


class FakeGraphService:
    def enrich(self, document_id, *_args):
        return GraphEnrichmentResult(document_id, 4, 8, 3)

    def search(self, *_args):
        return [
            GraphHit(
                "entity-1",
                "Atlas Launch",
                "INITIATIVE",
                "Product launch",
                "Priya Shah",
                "OWNS",
                "Atlas Launch",
                "Priya owns the launch.",
                "atlas.md",
                "chunk-1",
                1.0,
            )
        ]


def test_graph_enrichment_and_search_endpoints(monkeypatch):
    monkeypatch.setattr("decisiongraph.api.main.get_graph_service", FakeGraphService)
    enrichment = asyncio.run(
        api_post_json(
            "/v1/graph/enrich",
            {
                "document_id": "doc-1",
                "tenant_id": "acme",
                "user_id": "u1",
                "allowed_scopes": ["team"],
            },
        )
    )
    assert enrichment.status_code == 200
    assert enrichment.json()["entity_mentions"] == 8

    search = asyncio.run(
        api_post_json(
            "/v1/graph/search",
            {
                "query": "Atlas",
                "tenant_id": "acme",
                "user_id": "u1",
                "allowed_scopes": ["team"],
            },
        )
    )
    assert search.status_code == 200
    assert search.json()["results"][0]["relation_type"] == "OWNS"


def test_graph_endpoints_return_configuration_error(monkeypatch):
    def unavailable():
        raise ValueError("OPENAI_API_KEY is not configured")

    monkeypatch.setattr("decisiongraph.api.main.get_graph_service", unavailable)
    response = asyncio.run(
        api_post_json(
            "/v1/graph/enrich",
            {"document_id": "doc-1", "tenant_id": "acme", "user_id": "u1"},
        )
    )
    assert response.status_code == 503


def test_retrieve_endpoint_returns_route_and_citation_ready_context(monkeypatch):
    class FakeOrchestrator:
        def retrieve(self, query, *_args):
            evidence = EvidenceItem(
                "chunk:1",
                "E1",
                "atlas.md",
                "chunk-1",
                "Atlas was delayed by payment testing.",
                ("Atlas", "Decision"),
                (),
                ("vector_keyword",),
                1.0,
                0.9,
            )
            return RetrievalResponse(
                query,
                RetrievalPlan("vector", "The question asks for document-grounded detail."),
                (evidence,),
                (
                    "[E1] source=atlas.md; section=Atlas > Decision\\n"
                    "Atlas was delayed by payment testing."
                ),
                20,
            )

    monkeypatch.setattr("decisiongraph.api.main.get_retrieval_orchestrator", FakeOrchestrator)
    response = asyncio.run(
        api_post_json(
            "/v1/retrieve",
            {"query": "Why was Atlas delayed?", "tenant_id": "acme", "user_id": "u1"},
        )
    )
    assert response.status_code == 200
    assert response.json()["route"] == "vector"
    assert response.json()["evidence"][0]["citation"] == "E1"


def test_answer_endpoint_returns_only_verified_claims(monkeypatch):
    class FakeAnswerService:
        def answer(self, query, *_args):
            return AnswerResult(
                query=query,
                answer="Priya Shah owns payment reliability. [E1]",
                decision="answered",
                confidence=ConfidenceScore(0.9, 0.9, 1.0, 1.0, "high"),
                claims=(
                    VerifiedClaim(
                        "Priya Shah owns payment reliability.",
                        ("E1",),
                        True,
                        ("Explicitly supported.",),
                    ),
                ),
                citations=(
                    {
                        "citation": "E1",
                        "source_name": "atlas.md",
                        "chunk_id": "chunk-1",
                        "section_path": ["Atlas"],
                        "page_numbers": [],
                        "content": "Priya Shah owns payment reliability.",
                        "rerank_score": 0.9,
                    },
                ),
                route="hybrid",
                route_reason="Relationship plus passage detail.",
            )

    class FakeOperationsStore:
        def record_answer(self, *_args):
            return "event-1"

        def create_review(self, *_args):
            raise AssertionError("high-confidence answer should not enter review")

    monkeypatch.setattr("decisiongraph.api.main.get_answer_service", FakeAnswerService)
    monkeypatch.setattr("decisiongraph.api.main.get_operations_store", FakeOperationsStore)
    response = asyncio.run(
        api_post_json(
            "/v1/answers",
            {"query": "Who owns payment reliability?", "tenant_id": "acme", "user_id": "u1"},
        )
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "answered"
    assert response.json()["answer"].endswith("[E1]")


def test_answer_endpoint_creates_review_for_an_abstention(monkeypatch):
    class FakeAnswerService:
        def answer(self, query, *_args):
            return AnswerResult(
                query,
                "I don't have enough verified evidence to answer that safely.",
                "abstained",
                ConfidenceScore(0.0, 0.0, 0.0, 0.0, "low"),
                (),
                (),
                "hybrid",
                "Fallback retrieval.",
            )

    class FakeOperationsStore:
        def record_answer(self, *_args):
            return "event-1"

        def create_review(self, *_args):
            from decisiongraph.operations.models import ReviewItem

            return ReviewItem(
                "review-1",
                "event-1",
                "acme",
                "u1",
                "Question",
                "abstained: insufficient verified evidence",
                "pending",
                None,
                {},
                None,
                None,
                "2026-01-01T00:00:00+00:00",
                None,
            )

    monkeypatch.setattr("decisiongraph.api.main.get_answer_service", FakeAnswerService)
    monkeypatch.setattr("decisiongraph.api.main.get_operations_store", FakeOperationsStore)
    response = asyncio.run(
        api_post_json(
            "/v1/answers",
            {"query": "Question", "tenant_id": "acme", "user_id": "u1"},
        )
    )
    assert response.status_code == 200
    assert response.json()["review"]["status"] == "pending"


def test_review_and_evaluation_endpoints(monkeypatch):
    from decisiongraph.operations.models import EvaluationReport, ReviewItem

    class FakeOperationsStore:
        def list_reviews(self, *_args):
            return [
                ReviewItem(
                    "review-1",
                    None,
                    "acme",
                    "u1",
                    "Question",
                    "abstained",
                    "pending",
                    None,
                    {},
                    None,
                    None,
                    "2026-01-01T00:00:00+00:00",
                    None,
                )
            ]

        def resolve_review(self, *_args):
            return self.list_reviews()[0]

        def metrics(self, tenant_id):
            from decisiongraph.operations.models import OperationsMetrics

            return OperationsMetrics(tenant_id, 2, 1, 1, 120.0, 0.45, 1)

    class FakeEvaluationService:
        def run(self, *_args):
            return EvaluationReport(1, 1.0, 1.0, 1.0, 0.9, ())

    monkeypatch.setattr("decisiongraph.api.main.get_operations_store", FakeOperationsStore)
    monkeypatch.setattr("decisiongraph.api.main.get_evaluation_service", FakeEvaluationService)
    reviews = asyncio.run(api_get("/v1/reviews?tenant_id=acme"))
    assert reviews.status_code == 200
    assert reviews.json()["items"][0]["id"] == "review-1"
    metrics = asyncio.run(api_get("/v1/metrics?tenant_id=acme"))
    assert metrics.status_code == 200
    assert metrics.json()["pending_reviews"] == 1
    resolution = asyncio.run(
        api_post_json(
            "/v1/reviews/review-1/resolve",
            {"tenant_id": "acme", "reviewer_id": "reviewer", "outcome": "approved"},
        )
    )
    assert resolution.status_code == 200
    evaluation = asyncio.run(
        api_post_json(
            "/v1/evaluations/run",
            {
                "tenant_id": "acme",
                "user_id": "u1",
                "cases": [{"question": "Who owns payment reliability?"}],
            },
        )
    )
    assert evaluation.status_code == 200
    assert evaluation.json()["answer_accuracy"] == 1.0


def test_answer_endpoint_returns_configuration_error(monkeypatch):
    def unavailable():
        raise ValueError("OPENAI_API_KEY is not configured")

    monkeypatch.setattr("decisiongraph.api.main.get_answer_service", unavailable)
    response = asyncio.run(
        api_post_json(
            "/v1/answers",
            {"query": "Who owns payment reliability?", "tenant_id": "acme", "user_id": "u1"},
        )
    )
    assert response.status_code == 503
