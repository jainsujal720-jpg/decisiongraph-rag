from collections.abc import Sequence

from decisiongraph.ingestion.chunking import StructureAwareChunker
from decisiongraph.ingestion.parsers import parse_document
from decisiongraph.knowledge.embeddings import EmbeddingProvider
from decisiongraph.knowledge.models import IngestionResult, SearchHit
from decisiongraph.knowledge.retrieval import reciprocal_rank_fusion


class KnowledgeService:
    def __init__(
        self,
        store,
        embedding_provider: EmbeddingProvider,
        candidate_limit: int = 20,
        rrf_constant: int = 60,
    ):
        self.store = store
        self.embedding_provider = embedding_provider
        self.candidate_limit = candidate_limit
        self.rrf_constant = rrf_constant

    def ingest(
        self,
        filename: str,
        data: bytes,
        media_type: str | None,
        tenant_id: str,
        owner_id: str,
        access_scope: str,
    ) -> IngestionResult:
        if access_scope not in {"private", "team", "company"}:
            raise ValueError("access_scope must be private, team or company")
        document = parse_document(filename, data, media_type)
        duplicate = self.store.find_ready_document(
            tenant_id, document.filename, document.checksum_sha256
        )
        if duplicate:
            return duplicate
        chunks = StructureAwareChunker().chunk(document)
        embeddings = self.embedding_provider.embed([chunk.content for chunk in chunks.children])
        return self.store.ingest(
            chunks,
            embeddings,
            tenant_id=tenant_id,
            owner_id=owner_id,
            access_scope=access_scope,
        )

    def search(
        self,
        query: str,
        tenant_id: str,
        user_id: str,
        allowed_scopes: Sequence[str],
        limit: int,
    ) -> list[SearchHit]:
        if not query.strip():
            raise ValueError("query must not be empty")
        invalid = set(allowed_scopes) - {"private", "team", "company"}
        if invalid:
            raise ValueError("allowed_scopes contains an invalid access scope")
        query_embedding = self.embedding_provider.embed([query])[0]
        vector = self.store.vector_candidates(
            query_embedding, tenant_id, user_id, allowed_scopes, self.candidate_limit
        )
        keyword = self.store.keyword_candidates(
            query, tenant_id, user_id, allowed_scopes, self.candidate_limit
        )
        return reciprocal_rank_fusion(vector, keyword, limit, self.rrf_constant)

    def reindex(self, document_id: str, tenant_id: str, actor_id: str) -> int:
        """Recreate stored child-chunk embeddings without changing document content or version."""
        payload = self.store.reindex_payload(document_id, tenant_id)
        if not payload:
            raise ValueError("Document was not found")
        version_id, chunks = payload
        embeddings = self.embedding_provider.embed([content for _, content in chunks])
        return self.store.replace_embeddings_and_audit(
            document_id, tenant_id, version_id, embeddings, actor_id
        )
