# DecisionGraph RAG Stage 9 verification

Validated before packaging:

- Editable installation from `pyproject.toml`: passed
- Ruff formatting: passed
- Ruff static analysis and security rules: passed
- Pytest: 57 passed
- Unit/API-test coverage: 90.56% (required minimum: 90%)
- Python bytecode compilation: passed
- Fresh-process FastAPI liveness request: passed
- Real multipart Markdown preview request: passed
- Controlled missing-key response: HTTP 503 passed
- OpenAPI schema exposes preview, document ingestion, hybrid search, graph enrichment and graph
  search endpoints
- Compose YAML structure: six services present; database and graph initialization gate API startup
- Duplicate preflight, version filtering, permission SQL, reciprocal-rank fusion, evidence-only
  relationships and graph version filtering: tested
- Graph-search Neo4j parameter binding regression: tested
- Query routing, graph/passage fusion, duplicate graph-evidence removal, lexical reranking and
  bounded context assembly: tested
- Cross-channel deduplication merges graph evidence into an equivalent parent passage: tested
- Multiple graph relationships retained on one merged evidence block: tested
- Structured claim drafting, valid-citation filtering and claim/citation verification: tested
- Unsupported claims, missing evidence and unknown citations safely abstain: tested
- Answer API returns citations and an audit trail of verification decisions: tested
- Audit-event, review-queue, evaluation and operational-metrics contracts: tested
- Optional API-key guard and fixed-window rate-limit adapter: tested
- Dashboard TypeScript compilation and production Vite build: passed
- Explicit local CORS allowlist protects API access from browser origins: tested by configuration
- Docker Compose now serves the reviewer dashboard on port 3000 after the API health gate
- JWT authentication validates issuer, audience, expiry, subject and tenant claims: tested
- Role, tenant and scope authorization failures return HTTP 403: tested
- Redis rate limiter uses atomic counter/expiry behavior: tested with a deterministic client double
- API response adds a request ID and security headers: tested by middleware contract

The execution workspace does not provide a Docker daemon. PostgreSQL, Neo4j, Redis and the API
were already verified together in Stages 1 and 2 on the user's Docker Desktop. After installing
Stage 5, the user should rebuild the stack and perform the live orchestrated retrieval sequence
described in `docs/STAGE_9_GUIDE.md`. The `db-init` and `graph-init` services apply idempotent
schema setup before the API starts; the dashboard waits for the API health check.
