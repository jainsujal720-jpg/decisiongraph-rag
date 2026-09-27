# DecisionGraph RAG · Stage 14

**New in Stage 14:** optional, private S3 document uploads from the dashboard.
The API signs each upload, verifies file size and SHA-256 before indexing,
and reuses the existing tenant-aware ingestion pipeline. The previous Stage 13
cost routing remains in place; Jev stays off. Read [Stage 14 setup](docs/STAGE-14.md).

DecisionGraph is an enterprise-style hybrid GraphRAG product-intelligence platform. It will
combine semantic vector retrieval, keyword retrieval and knowledge-graph traversal with
permission filtering, reranking, citations, verification, abstention and measurable evaluation.

This package contains **Stage 14: cloud document upload**. It builds on verified generation,
persistent hybrid retrieval, an evidence-linked knowledge graph, audit events, human review and a
React reviewer dashboard.

## Current architecture

```text
FastAPI
  ├── PostgreSQL + pgvector: documents, versions, chunks, vectors and keyword search
  ├── Neo4j: entities and relationships
  └── Redis: cache and background-job coordination
  └── RelayGuard: tenant-aware answer routing, fallback, rate limits, spend budgets and audit events
```

## Quick start

Prerequisites: Docker Desktop with Docker Compose.

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
curl http://localhost:8000/health/ready
```

Then open:

- API documentation: <http://localhost:8000/docs>
- Reviewer dashboard: <http://localhost:3000>
- Neo4j browser: <http://localhost:7474>
- RelayGuard safety dashboard: <http://localhost:3100>

The API exposes these core operations:

- `POST /v1/ingestion/preview` — inspect parsing and chunks without persistence or API cost.
- `POST /v1/documents` — parse, chunk, embed and store a versioned document.
- `POST /v1/cloud/uploads` — issue a private S3 upload URL tied to one tenant/user and checksum.
- `POST /v1/cloud/uploads/{id}/complete` — verify the object and index its contents.
- `GET /v1/cloud/uploads/{id}` — inspect a specific user's upload status.
- `POST /v1/search` — run vector and full-text retrieval, permission filtering and RRF fusion.
- `POST /v1/graph/enrich` — extract entities and evidence-backed relationships for one stored
  document.
- `POST /v1/graph/search` — search the authorized entity graph and return source evidence.
- `POST /v1/retrieve` — route a question, fuse and rerank graph/passage evidence, and return a
  citation-ready context package without generating an answer.
- `POST /v1/answers` — draft atomic claims, verify every cited claim against retrieved evidence,
  then answer or safely abstain.
- `GET /v1/reviews` and `POST /v1/reviews/{id}/resolve` — list and resolve human-review items.
- `GET /v1/metrics` — tenant-scoped answer, latency, confidence and pending-review metrics.
- `POST /v1/evaluations/run` — run bounded answer, decision and source regression checks.

Stage 9 adds an optional JWT mode that validates signed user, tenant, role and scope claims; a
Redis-backed rate-limit option for multi-replica deployments; request IDs; and browser-security
response headers. Read `docs/STAGE_9_GUIDE.md` before enabling `AUTH_MODE=jwt`.

The document, hybrid-search and graph-enrichment operations require `OPENAI_API_KEY` in `.env`.
The key remains on the server; clients never send it in an API request. Graph search itself does
not call the model, although the current API service initializes its extraction dependency.

## Stage 11: governed answer generation

`POST /v1/answers` now sends its two free-text model operations through RelayGuard: the evidence
draft and the citation-verification pass. RelayGuard receives the DecisionGraph tenant and user IDs,
enforces its policy and budget controls, chooses a route/fallback and records the operational event.
DecisionGraph still performs its own citation validation, confidence calculation, abstention and
human-review routing after the gateway returns. Embeddings and graph extraction remain direct OpenAI
calls in this stage because RelayGuard currently exposes a governed chat-completion API, not an
embedding API.

For real answers, set both values below in `.env` before starting the stack:

```bash
OPENAI_API_KEY=your-server-side-key
RELAYGUARD_PROVIDER_MODE=openai
```

`RELAYGUARD_PROVIDER_MODE=mock` is retained as the safe default for gateway-only demonstrations;
it does not produce schema-valid DecisionGraph answers.

With `openai` mode, RelayGuard offers six workload classes: basic GPT-4.1 Mini;
GPT-5.6 Luna, Terra and Sol for progressively more involved work; GPT-6 Sol for demanding
reasoning; and GPT-6 Luna for long, focused input. DecisionGraph selects a class based on the
question and retrieved evidence. Read `docs/STAGE_11_GUIDE.md` for the full route/fallback
table. API access depends on the configured OpenAI project. The dashboard cost figure is an
approximate prototype estimate and is not a provider billing total.

The local Neo4j login is defined in `.env.example` and `compose.yaml`. It is only a development
credential and must be changed before any shared deployment.

## Development without Docker for the API process

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
uvicorn decisiongraph.api.main:app --reload
```

PostgreSQL, Neo4j and Redis must still be running for `/health/ready` to report `ready`.

## Tests

```bash
pytest -q
ruff check .
ruff format --check .
```

## Build roadmap

1. **Complete:** architecture, data schema, containers, configuration and health checks
2. **Complete:** parsing, normalization, structure-aware and parent-child chunking
3. **Complete:** embeddings, versioned persistence, vector/keyword retrieval and rank fusion
4. **Complete:** evidence-bound entity extraction, Neo4j graph construction and graph retrieval
5. **Complete:** deterministic query routing, evidence fusion, reranking and context assembly
6. **Complete:** grounded generation, citation verification, confidence and abstention
7. **Complete:** evaluation, auditability, review-queue foundation and API hardening
8. **Complete:** React reviewer dashboard for live answers, citations, metrics and review decisions
9. **Complete:** JWT authorization boundary, tenant/role enforcement, Redis rate limiting and request safeguards
10. **In progress:** cloud document import from a private S3 bucket
11. Asynchronous ingestion and external object-change synchronization
12. IdP JWKS integration, OpenTelemetry and cloud deployment

Read the guides in `docs/` for the infrastructure, parsing/chunking, hybrid retrieval and graph
pipeline decisions, including limitations, failure modes and manual verification steps.
