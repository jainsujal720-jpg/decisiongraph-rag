# Stage 14 S3 upload redirect fix

The API was signing uploads for a global S3 hostname, even though its normal
client endpoint was in Mumbai. Fresh buckets can return HTTP 307 for this host.
This patch pins presigned URLs to the configured regional S3 endpoint.

Extract this ZIP inside your existing Stage 14 project folder (the one with
`compose.yaml`), then rebuild only the API:

```bash
docker compose build api
docker compose up -d --no-build --force-recreate api
```

Retry the folder loader:

```bash
python3 scripts/load_cloud_documents.py "$HOME/Downloads/decisiongraph-documents" --tenant acme --user sujal --watch
```

The signed host should now end with `.s3.ap-south-1.amazonaws.com`. The patch
does not change IAM policy, CORS, AWS credentials, or existing indexed files.
