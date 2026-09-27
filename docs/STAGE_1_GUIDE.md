# Stage 1 — Architecture and Infrastructure

## What this stage accomplishes

Stage 1 creates a dependable foundation before we add document parsing or an LLM.
The API has two different health checks:

- `/health/live` asks: **Is the API process running?**
- `/health/ready` asks: **Can the API reach every database and queue it needs?**

Separating these matters in production. A process can be alive while PostgreSQL is down;
traffic should not be sent to that unhealthy instance.

## Why each service exists

| Service | Responsibility | It will not do |
|---|---|---|
| PostgreSQL + pgvector | Documents, chunks, permissions, vectors, keyword index, audit data | Multi-hop relationship traversal |
| Neo4j | Product entities and relationships | Store every raw document as the primary source |
| Redis | Short-lived cache and background-job coordination | Act as the durable source of truth |
| FastAPI | Validated API and orchestration boundary | Perform long ingestion work inside web requests |

## Database design decisions

`documents` stores logical document identity and access rules. `document_versions` lets us
retain history when a roadmap or PRD changes. `chunks` stores searchable units and their
embeddings. `ingestion_jobs` records pipeline progress. `query_events` will support quality,
latency and cost analysis.

The embedding column is `vector(1536)` because Stage 2 will initially use a 1536-dimensional
embedding configuration. Changing dimensions later requires a controlled re-index and schema
migration; mixing dimensions would make similarity search invalid.

## Problems we are preventing now

1. **Duplicate ingestion:** document checksums make identical files detectable.
2. **Lost provenance:** every chunk belongs to a specific document version.
3. **Permission leakage:** tenant and access data exist before retrieval is implemented.
4. **Silent dependency failure:** readiness reports each dependency separately.
5. **Unrepeatable setup:** Docker Compose creates the same local services for every developer.
6. **Secret leakage:** `.env` is ignored and the API-key field is hidden from configuration logs.
7. **Untraceable quality:** query events have a place to store routes, scores and latency.

## Problems we may still face

- Port 5432, 6379, 7474, 7687 or 8000 may already be used by another application.
- Docker Desktop may not have enough allocated memory for Neo4j.
- The initial database SQL runs only when the PostgreSQL volume is created. Later schema
  changes must use migrations rather than editing the initial SQL.
- Apple Silicon may take longer when pulling a container image for the first time.
- A vector index improves speed but can reduce recall. We must measure recall before tuning it.
- Health checks prove connectivity, not that retrieval quality is good.

## Manual verification

From the extracted project directory:

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
curl http://localhost:8000/health/ready
```

Expected readiness status:

```json
{
  "status": "ready",
  "components": [
    {"name": "postgres", "status": "up"},
    {"name": "neo4j", "status": "up"},
    {"name": "redis", "status": "up"}
  ]
}
```

Latency values will vary. Do not paste an API key into screenshots or chat.

