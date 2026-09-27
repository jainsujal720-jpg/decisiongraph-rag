# Stage 14 automatic cloud document loader

Extract this ZIP **inside the Stage 14 project folder** (the folder containing
`compose.yaml`). This adds `scripts/load_cloud_documents.py` and updates
`docs/STAGE-14.md`; it does not change the running API or dashboard image.

Put supported documents in a local folder such as
`$HOME/Downloads/decisiongraph-documents`, then from the Stage 14 folder run:

```bash
python3 scripts/load_cloud_documents.py "$HOME/Downloads/decisiongraph-documents" --tenant acme --user sujal
```

To keep watching that folder for additions and changes until you press Ctrl+C:

```bash
python3 scripts/load_cloud_documents.py "$HOME/Downloads/decisiongraph-documents" --tenant acme --user sujal --watch
```

The script uploads via DecisionGraph's existing Stage 14 API and a presigned
S3 URL. It never reads AWS credentials, and it does not require extra Python
packages. Successfully indexed files are remembered in the folder's
`.decisiongraph-cloud-loader.json`, so unchanged files are skipped later.
Consult `docs/STAGE-14.md` for limits, supported formats, API calls, and costs.
