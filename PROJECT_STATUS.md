# Project status and repository layout

This repository contains the Stage 14 DecisionGraph RAG prototype and a copy of the RelayGuard gateway at `relayguard/`. The integrated Docker Compose configuration builds both from this checkout. The gateway also has its own standalone showcase repository: https://github.com/jainsujal720-jpg/relayguard-llm-gateway . Changes to RelayGuard should be synchronized between the two copies.

The verified local workflow uses PostgreSQL with pgvector, Neo4j, Redis, OpenAI embeddings and chat calls through RelayGuard, and optional private S3 uploads. The automatic folder loader is in `scripts/load_cloud_documents.py`; it watches a local directory while running and does not install a durable cloud event trigger. Jev routing is disabled while access is unavailable.

This is a portfolio prototype. Before a shared or production deployment, replace development credentials, enable authentication, configure a secrets manager, tenant isolation and monitoring, and run security and load reviews. Cost estimates are not provider invoices.

Do not commit `.env`, AWS credentials, real documents, upload state files or account data. Configure a private S3 bucket using `docs/STAGE-14.md`.
