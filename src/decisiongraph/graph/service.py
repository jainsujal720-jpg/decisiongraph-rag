from decisiongraph.graph.models import GraphEnrichmentResult, GraphHit


class GraphService:
    def __init__(self, knowledge_store, graph_store, extractor, max_chunks: int = 50):
        self.knowledge_store = knowledge_store
        self.graph_store = graph_store
        self.extractor = extractor
        self.max_chunks = max_chunks

    def enrich(
        self,
        document_id: str,
        tenant_id: str,
        user_id: str,
        allowed_scopes: list[str],
    ) -> GraphEnrichmentResult:
        sources = self.knowledge_store.graph_sources(
            document_id, tenant_id, user_id, allowed_scopes, self.max_chunks
        )
        if not sources:
            raise ValueError("Document not found or access denied")
        entity_mentions = 0
        relationship_count = 0
        for source, owner_id, access_scope in sources:
            extraction = self.extractor.extract(source.content)
            self.graph_store.upsert_extraction(
                tenant_id, owner_id, access_scope, source, extraction
            )
            entity_mentions += len(extraction.entities)
            relationship_count += len(extraction.relations)
        return GraphEnrichmentResult(
            document_id,
            len(sources),
            entity_mentions,
            relationship_count,
        )

    def search(
        self,
        query: str,
        tenant_id: str,
        user_id: str,
        allowed_scopes: list[str],
        limit: int,
    ) -> list[GraphHit]:
        if not query.strip():
            raise ValueError("query must not be empty")
        invalid = set(allowed_scopes) - {"private", "team", "company"}
        if invalid:
            raise ValueError("allowed_scopes contains an invalid access scope")
        return self.graph_store.search(query, tenant_id, user_id, allowed_scopes, limit)

    def delete_document(self, tenant_id: str, document_id: str) -> None:
        self.graph_store.delete_document(tenant_id, document_id)
