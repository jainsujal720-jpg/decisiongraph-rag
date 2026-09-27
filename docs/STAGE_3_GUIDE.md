# Stage 3 — Embeddings, persistence and hybrid retrieval

## The pipeline

### Document ingestion

1. The API authenticates the logical tenant, owner and document access scope supplied by the
   caller. Authentication itself will be connected to a real identity provider in the security
   stage; callers must not be trusted to choose these values in production.
2. The Stage 2 parser validates and normalizes the document.
3. A checksum and source name are checked before embedding. An unchanged ready document is
   returned as a duplicate, avoiding unnecessary API cost.
4. Structure-aware parent and child chunks are produced. Parents retain context; children are
   optimized for retrieval.
5. Only child chunks are embedded with `text-embedding-3-small` at 1,536 dimensions.
6. PostgreSQL stores the document, immutable version, parent/child lineage, permissions,
   provenance and vectors in one transaction.
7. The version becomes searchable only after every chunk has been stored successfully.

### Query retrieval

1. The question is embedded with the same model and dimension used during ingestion.
2. pgvector runs approximate nearest-neighbor semantic search over child chunks.
3. PostgreSQL full-text search independently finds exact names, acronyms, dates and keywords.
4. Both queries enforce tenant and access-scope filters inside SQL, before results leave the
   database. Private documents additionally require owner identity.
5. Only the newest ready version of each document can be retrieved.
6. Reciprocal Rank Fusion (RRF) combines ranks without pretending cosine similarity and text
   rank are directly comparable. A result found by both channels receives two contributions:
   `1 / (k + vector_rank) + 1 / (k + keyword_rank)`.
7. Each child result is expanded to its parent context for downstream reranking and generation.

## Why PostgreSQL and pgvector

Keeping permissions, metadata, keyword indexes and vectors in PostgreSQL gives this project
transactional consistency and makes permission filtering part of retrieval. A dedicated vector
database can be appropriate at much larger scale, but it adds another distributed system and can
make authorization joins harder. The HNSW index provides fast approximate vector search while
the GIN index accelerates full-text search.

## Versioning and idempotency

`tenant_id + source_name` identifies a logical document. A changed checksum creates a new
version; an unchanged checksum returns the current ready version with `deduplicated: true`.
Search excludes older ready versions so outdated decisions do not leak into current answers.

## Access model in this stage

- `private`: retrievable only when `owner_id == user_id`.
- `team`: retrievable within the same tenant when the caller includes `team` in allowed scopes.
- `company`: retrievable within the same tenant when allowed by the caller.

This demonstrates retrieval-time authorization, but request fields are not authentication.
Production must derive tenant, user and scopes from verified JWT claims or an API gateway.

## Failure modes and mitigations

- **Wrong or missing API key:** ingestion/search returns a controlled 503 or 502, not a raw stack
  trace. Readiness remains available so operations can distinguish configuration from downtime.
- **Embedding-model change:** dimensions and model must stay consistent with stored vectors.
  A production migration should create a new embedding version rather than mixing models.
- **Duplicate upload cost:** checksum preflight occurs before the embedding request.
- **Partial writes:** document versions become `ready` only inside a successful transaction.
- **Stale versions:** SQL selects only the newest ready version.
- **Keyword/vector scale mismatch:** RRF uses ranks rather than combining raw scores.
- **Cross-tenant leakage:** every retrieval query filters `tenant_id` in the database.
- **Prompt injection:** this stage retrieves evidence only. Stage 6 will treat retrieved text as
  untrusted data and add grounded generation and citation verification.
- **HNSW recall:** approximate search trades some recall for speed. Stage 7 evaluation will tune
  candidate counts and compare against exact-search baselines.

## Manual verification sequence

1. Put a newly created OpenAI API key in `.env`; never paste it into screenshots or Git.
2. Rebuild with `docker compose up --build -d`.
3. Confirm `db-init` and `graph-init` exit with code 0 and long-running services are healthy.
4. Upload `sample_docs/atlas_status.md` with `POST /v1/documents`.
5. Search for `Why was the Atlas launch delayed?` using `POST /v1/search`.
6. Upload the same document again and confirm `deduplicated` becomes `true`.

## What Stage 3 deliberately does not do

It does not generate an answer, rerank with a cross-encoder, extract entities, traverse Neo4j or
verify citations. Those layers will be added separately so each subsystem remains inspectable
and measurable rather than hidden inside a monolithic RAG chain.
