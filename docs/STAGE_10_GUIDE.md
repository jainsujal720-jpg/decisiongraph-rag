# Stage 10 — Enterprise Document Operations

Stage 10 turns DecisionGraph from a strong RAG demo into a knowledge-base
product. Documents have a secure lifecycle: authorized upload, version-aware
cataloguing, re-indexing, access changes, deletion, and an immutable audit trail.

## What was added

| Capability | What it does | Why it matters |
| --- | --- | --- |
| Document catalog | Lists only documents visible to the caller's tenant, user, and scopes. | Prevents accidental cross-team discovery. |
| Document detail | Shows version history, chunk counts, and recent operational events. | Makes ingestion inspectable and debuggable. |
| Upload and index | Uploading the same filename with changed contents creates a new version. | Retrieval always uses the latest ready version. |
| Re-index | Recreates embeddings for the latest stored child chunks. | Lets you migrate embedding models or repair vector indexes without re-uploading. |
| Scope update | Changes `private`, `team`, or `company` access with authorization. | Applies least-privilege access at the data layer. |
| Delete | Deletes PostgreSQL document versions/chunks and matching Neo4j graph evidence. | Avoids stale citations after source removal. |
| Audit events | Records uploads, access changes, re-indexes, and deletion requests. | Provides governance evidence for reviewers. |

## New API endpoints

All endpoints remain tenant-scoped and require the role shown when `AUTH_MODE=jwt`.

| Endpoint | Role | Use |
| --- | --- | --- |
| `GET /v1/documents` | reader | List authorized documents. |
| `GET /v1/documents/{document_id}` | reader | Inspect versions and audit events. |
| `POST /v1/documents` | editor | Upload and index a document. |
| `POST /v1/documents/{document_id}/reindex` | editor | Refresh stored child-chunk embeddings. |
| `POST /v1/documents/{document_id}/access` | editor | Set document scope. |
| `DELETE /v1/documents/{document_id}` | editor | Delete document, vectors, and graph evidence. |

## Dashboard flow

1. Enter the JWT bearer token and click **Refresh live data**.
2. In **Knowledge-base lifecycle**, select a supported file (`PDF`, `DOCX`,
   `TXT`, `MD`, or `CSV`), choose its scope, and click **Upload and index**.
3. The catalog reports its current version and number of searchable chunks.
4. Use **Re-index** after an embedding-model change. This does not alter source
   content or create a new document version.
5. Use **Delete** only when the source should no longer be retrievable. It asks
   for confirmation and removes corresponding graph evidence as well.

## Important limits

- This synchronous demo is appropriate for small-to-medium files. Production
  systems should place parsing, embedding, and graph enrichment in a queue.
- Re-indexing refreshes vectors from stored chunks. If source content changes,
  upload it again so the system records a new document version.
- The app records audit events in PostgreSQL. For regulatory retention, export
  them to immutable external storage and restrict direct database access.
- JWT verification is intentionally local HMAC development mode. Production
  should use an identity provider, short-lived tokens, and JWKS key rotation.

## Interview explanation

> “The system treats documents as governed operational assets, not anonymous
> text. Every document is tenant-scoped, versioned, and access-controlled. We
> can refresh vectors without changing the source, and deletion removes both
> vector chunks and graph evidence to prevent stale answers. The lifecycle is
> visible in an audit trail and enforced through role-based API authorization.”
