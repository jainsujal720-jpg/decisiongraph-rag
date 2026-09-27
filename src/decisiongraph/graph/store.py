from neo4j import GraphDatabase

from decisiongraph.graph.extraction import canonicalize, stable_id
from decisiongraph.graph.models import ExtractionResult, GraphHit, GraphSource

UPSERT_CYPHER = """
MERGE (document:Document {tenant_id: $tenant_id, document_id: $document_id})
SET document.source_name = $source_name,
    document.owner_id = $owner_id,
    document.access_scope = $access_scope,
    document.latest_version_number = $version_number
MERGE (chunk:Chunk {tenant_id: $tenant_id, chunk_id: $chunk_id})
SET chunk.content = $content,
    chunk.section_path = $section_path,
    chunk.version_id = $version_id,
    chunk.version_number = $version_number
MERGE (document)-[:HAS_CHUNK]->(chunk)
WITH chunk
UNWIND $entities AS item
MERGE (entity:Entity {tenant_id: $tenant_id, entity_id: item.entity_id})
SET entity.canonical_name = item.canonical_name,
    entity.display_name = item.display_name,
    entity.entity_type = item.entity_type,
    entity.description = item.description
MERGE (chunk)-[:MENTIONS]->(entity)
"""

RELATION_CYPHER = """
UNWIND $relations AS item
MATCH (source:Entity {tenant_id: $tenant_id, entity_id: item.source_id})
MATCH (target:Entity {tenant_id: $tenant_id, entity_id: item.target_id})
MATCH (chunk:Chunk {tenant_id: $tenant_id, chunk_id: $chunk_id})
MERGE (relation:Relation {tenant_id: $tenant_id, relation_id: item.relation_id})
SET relation.relation_type = item.relation_type,
    relation.evidence = item.evidence,
    relation.document_id = $document_id
MERGE (relation)-[:FROM]->(source)
MERGE (relation)-[:TO]->(target)
MERGE (chunk)-[:SUPPORTS]->(relation)
"""

SEARCH_CYPHER = """
CALL db.index.fulltext.queryNodes('entity_fulltext', $query, {limit: $candidate_limit})
YIELD node, score
MATCH (mentioning_chunk:Chunk)-[:MENTIONS]->(node)
MATCH (mentioning_document:Document)-[:HAS_CHUNK]->(mentioning_chunk)
WHERE node.tenant_id = $tenant_id
  AND mentioning_document.tenant_id = $tenant_id
  AND mentioning_document.access_scope IN $allowed_scopes
  AND (mentioning_document.access_scope <> 'private'
       OR mentioning_document.owner_id = $user_id)
  AND mentioning_chunk.version_number = mentioning_document.latest_version_number
OPTIONAL MATCH (relation:Relation {tenant_id: $tenant_id})-[:FROM|TO]->(node)
OPTIONAL MATCH (relation)-[:FROM]->(source:Entity)
OPTIONAL MATCH (relation)-[:TO]->(target:Entity)
OPTIONAL MATCH (chunk:Chunk)-[:SUPPORTS]->(relation)
OPTIONAL MATCH (document:Document)-[:HAS_CHUNK]->(chunk)
WITH node, score, relation, source, target, chunk, document,
     mentioning_chunk, mentioning_document
WHERE relation IS NULL OR (
    document.tenant_id = $tenant_id
    AND document.access_scope IN $allowed_scopes
    AND (document.access_scope <> 'private' OR document.owner_id = $user_id)
    AND chunk.version_number = document.latest_version_number
)
RETURN node.entity_id AS entity_id,
       coalesce(node.display_name, node.canonical_name) AS entity_name,
       node.entity_type AS entity_type,
       coalesce(node.description, '') AS description,
       source.display_name AS source_entity,
       relation.relation_type AS relation_type,
       target.display_name AS target_entity,
       relation.evidence AS evidence,
       coalesce(document.source_name, mentioning_document.source_name) AS source_name,
       coalesce(chunk.chunk_id, mentioning_chunk.chunk_id) AS chunk_id,
       score AS graph_score
ORDER BY score DESC
LIMIT $limit
"""


class Neo4jGraphStore:
    def __init__(self, uri: str, username: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(username, password))

    def close(self) -> None:
        self.driver.close()

    def upsert_extraction(
        self,
        tenant_id: str,
        owner_id: str,
        access_scope: str,
        source: GraphSource,
        extraction: ExtractionResult,
    ) -> None:
        by_name: dict[str, str] = {}
        entities = []
        for entity in extraction.entities:
            name = canonicalize(entity.name)
            entity_type = canonicalize(entity.entity_type).replace(" ", "_").upper()
            entity_id = stable_id(entity_type, name)
            by_name[name] = entity_id
            entities.append(
                {
                    "entity_id": entity_id,
                    "canonical_name": name,
                    "display_name": entity.name,
                    "entity_type": entity_type,
                    "description": entity.description,
                }
            )
        relations = []
        for relation in extraction.relations:
            source_id = by_name[canonicalize(relation.source)]
            target_id = by_name[canonicalize(relation.target)]
            relation_type = canonicalize(relation.relation_type).replace(" ", "_").upper()
            relations.append(
                {
                    "relation_id": stable_id(
                        source_id, relation_type, target_id, source.chunk_id, relation.evidence
                    ),
                    "source_id": source_id,
                    "target_id": target_id,
                    "relation_type": relation_type,
                    "evidence": relation.evidence,
                }
            )
        parameters = {
            "tenant_id": tenant_id,
            "document_id": source.document_id,
            "source_name": source.source_name,
            "owner_id": owner_id,
            "access_scope": access_scope,
            "chunk_id": source.chunk_id,
            "content": source.content,
            "section_path": list(source.section_path),
            "version_id": source.version_id,
            "version_number": source.version_number,
            "entities": entities,
            "relations": relations,
        }
        with self.driver.session() as session:
            if entities:
                session.run(UPSERT_CYPHER, parameters).consume()
            if relations:
                session.run(RELATION_CYPHER, parameters).consume()

    def search(
        self,
        query: str,
        tenant_id: str,
        user_id: str,
        allowed_scopes: list[str],
        limit: int,
        candidate_limit: int = 100,
    ) -> list[GraphHit]:
        with self.driver.session() as session:
            parameters = {
                "query": query,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "allowed_scopes": allowed_scopes,
                "limit": limit,
                "candidate_limit": candidate_limit,
            }
            records = list(session.run(SEARCH_CYPHER, parameters))
        return [GraphHit(**record.data()) for record in records]

    def delete_document(self, tenant_id: str, document_id: str) -> None:
        """Remove graph evidence for a deleted source document; shared entities may remain."""
        cypher = """
        MATCH (document:Document {tenant_id: $tenant_id, document_id: $document_id})
        OPTIONAL MATCH (document)-[:HAS_CHUNK]->(chunk:Chunk)
        OPTIONAL MATCH (chunk)-[:SUPPORTS]->(relation:Relation {tenant_id: $tenant_id})
        DETACH DELETE relation, chunk, document
        """
        with self.driver.session() as session:
            session.run(cypher, {"tenant_id": tenant_id, "document_id": document_id}).consume()
