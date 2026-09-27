from neo4j import GraphDatabase

from decisiongraph.core.config import get_settings

CONSTRAINTS = (
    "CREATE CONSTRAINT entity_identity IF NOT EXISTS "
    "FOR (entity:Entity) REQUIRE (entity.tenant_id, entity.entity_id) IS UNIQUE",
    "CREATE INDEX entity_name IF NOT EXISTS FOR (entity:Entity) ON (entity.name)",
    "CREATE INDEX entity_type IF NOT EXISTS FOR (entity:Entity) ON (entity.entity_type)",
    "CREATE CONSTRAINT relation_identity IF NOT EXISTS "
    "FOR (relation:Relation) REQUIRE (relation.tenant_id, relation.relation_id) IS UNIQUE",
    "CREATE CONSTRAINT graph_document_identity IF NOT EXISTS "
    "FOR (document:Document) REQUIRE (document.tenant_id, document.document_id) IS UNIQUE",
    "CREATE CONSTRAINT graph_chunk_identity IF NOT EXISTS "
    "FOR (chunk:Chunk) REQUIRE (chunk.tenant_id, chunk.chunk_id) IS UNIQUE",
    "CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS FOR (entity:Entity) "
    "ON EACH [entity.canonical_name, entity.description]",
    "CALL db.awaitIndexes(300)",
)


def main() -> None:
    settings = get_settings()
    with GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
    ) as driver:
        driver.verify_connectivity()
        with driver.session() as session:
            for statement in CONSTRAINTS:
                session.run(statement).consume()
    print("Neo4j constraints and indexes are ready.")


if __name__ == "__main__":
    main()
