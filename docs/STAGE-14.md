# Stage 14 · Private cloud documents

## What is included

Stage 14 adds an **optional** Amazon S3 upload path to the existing DecisionGraph
dashboard. Local uploads, answers, and RelayGuard routing keep working when cloud
storage is not configured. Jev remains off.

The browser asks `POST /v1/cloud/uploads` for a short-lived (15 minute) URL,
uploads up to 20 MB directly to the configured private bucket with a signed
SHA-256 header, then calls `POST /v1/cloud/uploads/{id}/complete`. The API
checks the upload's owner and tenant, object size, checksum, and ETag before
calling the existing parser, embedding provider, and PostgreSQL indexer.
The `cloud_uploads` table records `requested`, `processing`, `indexed`, or
`failed`; the status API returns only the requesting tenant and owner's item.

The browser never receives AWS credentials. S3 object keys contain an opaque
tenant hash and a random upload ID. A stable derived filename within each
tenant, owner, access scope, bucket, and original filename lets a new upload
of the same name become a new searchable document version. The source name in
citations includes an `__s3_` marker. The original filename remains visible
in the cloud upload status.

Graph enrichment is an **optional checkbox**. It calls the existing graph
extractor and Neo4j after the document becomes searchable. If enrichment
fails, the vector/keyword index is retained and the dashboard reports the
failure; `POST /v1/graph/enrich` can retry. Embeddings call OpenAI directly;
graph enrichment also calls OpenAI if selected. Asking a question uses
RelayGuard for answer draft and citation verification. Merely displaying cloud
configuration or checking upload status does not call a model.

## One-time AWS setup you perform

1. Create a private, general-purpose S3 bucket in a region you choose. Keep
   block-public-access enabled; consider bucket versioning for recovery.
2. Give the API identity `s3:PutObject` and `s3:GetObject` only on the intended
   object prefix. For a bucket named `YOUR_PRIVATE_BUCKET`, the resource in a
   least-privilege policy is `arn:aws:s3:::YOUR_PRIVATE_BUCKET/tenants/*`.
   Use an IAM role in a hosted environment or an authorized local AWS
   credential for Docker Desktop. Do not put cloud credentials into the browser
   or send them in chat.
3. In the S3 bucket's **Permissions → Cross-origin resource sharing (CORS)**,
   add the configuration below for the exact origin you use locally:

   ```json
   [{
     "AllowedOrigins": ["http://localhost:3000", "http://127.0.0.1:3000"],
     "AllowedMethods": ["PUT"],
     "AllowedHeaders": ["Content-Type", "x-amz-checksum-sha256"],
     "MaxAgeSeconds": 300
   }]
   ```

4. In the existing local project `.env`, set `CLOUD_S3_BUCKET` and the matching
   `CLOUD_S3_REGION` (the sample defaults to `ap-south-1`). Supply
   `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN` only
   if the local API does not already have an approved AWS identity. Do not
   quote or paste these values into a support message.
5. From the **Stage 14 project folder**, run:

   ```bash
   docker compose build db-init api dashboard
   docker compose run --rm db-init
   docker compose up -d --no-build --force-recreate api dashboard
   docker compose ps api dashboard
   curl -s http://localhost:8000/v1/cloud/config
   ```

   The config response should be `{"enabled":true,"provider":"s3"}`.
   If cloud mode is disabled, the same response has `enabled:false` and the
   rest of DecisionGraph stays usable. Use the dashboard at
   `http://localhost:3000` to upload one fictional test `.md` document.

### Automatically load a folder

The dashboard upload is optional. From your **Stage 14 project folder** run:

```bash
python3 scripts/load_cloud_documents.py "$HOME/Downloads/my-documents" --tenant acme --user sujal
```

The loader recursively sends `.pdf`, `.docx`, `.txt`, `.md`, `.csv`, and `.xlsx`
files through the same presigned S3 upload and DecisionGraph indexing endpoints
as the dashboard. It requires no Python packages beyond the standard library
and does not handle AWS keys: the running API uses its configured AWS identity.
It records successful file checksums in `.decisiongraph-cloud-loader.json` in
the watched folder, so rerunning skips unchanged files. If a file changes, it
is uploaded again as a new document version. The loader rejects duplicate
filenames across subfolders because the API versions documents by filename.
Files over 20 MB are reported as failures without an upload. A failed file is
retried on the next run. Keep this state file with the folder, since deleting
it causes unchanged documents to be sent again.

To keep finding new or changed files while Terminal is open, run:

```bash
python3 scripts/load_cloud_documents.py "$HOME/Downloads/my-documents" --watch
```

Stop with Ctrl+C. Use `--enrich-graph` only if graph relationships are wanted;
it makes extra OpenAI calls. `--scope private` or `--scope company` changes the
access scope; `--tenant` and `--user` must match the identity you use in the
dashboard. With API key authentication enabled, supply the key via the
`DECISIONGRAPH_API_KEY` environment variable, never via shell arguments.
This loader watches **local files**; files placed directly into S3 by another
application are not indexed by this script. The future event-driven sync handles
external bucket writes.

## APIs and costs during one upload

| Step | API | External call |
| --- | --- | --- |
| Prepare | DecisionGraph `POST /v1/cloud/uploads` | Signs S3 URL locally; no model call |
| Transfer | Browser `PUT` to presigned S3 URL | S3 upload request |
| Complete | DecisionGraph `POST /v1/cloud/uploads/{id}/complete` | S3 `HeadObject` and `GetObject`, OpenAI embeddings, PostgreSQL writes |
| Optional graph | DecisionGraph graph enrichment in completion | OpenAI extraction and local Neo4j writes |
| Observe | DecisionGraph `GET /v1/cloud/uploads/{id}` | Local database read |
| Ask | DecisionGraph `POST /v1/answers` | Query embeddings; RelayGuard calls routed models |

S3, embeddings, extraction, and model calls can incur charges. The dashboard's
answer token estimate excludes S3 and embedding charges.

## Current limits and the next stage

Uploads initiated in this dashboard are indexed on completion. Stage 14 does
not watch external edits made directly in the bucket; Stage 15 adds event-driven
sync, background workers, retries, and reconciliation. Indexing currently runs
inside the completion request and can take time. A process crash during indexing
can leave `processing` status; Stage 15 adds recovery. Deleting a document in
DecisionGraph removes its indexes, **not** its original S3 object. Control S3
retention separately until deletion sync is implemented. Use HTTPS and an
actual organization identity provider before exposing this dashboard publicly.
