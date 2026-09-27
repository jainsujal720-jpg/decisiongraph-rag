from types import SimpleNamespace
from uuid import uuid4

import pytest

from decisiongraph.ingestion.chunking import StructureAwareChunker
from decisiongraph.ingestion.parsers import parse_document
from decisiongraph.knowledge.embeddings import OpenAIEmbeddingProvider
from decisiongraph.knowledge.models import Candidate, IngestionResult
from decisiongraph.knowledge.retrieval import reciprocal_rank_fusion
from decisiongraph.knowledge.service import KnowledgeService
from decisiongraph.knowledge.store import PostgresKnowledgeStore, _vector_literal


def candidate(chunk_id: str, score: float) -> Candidate:
    return Candidate(
        chunk_id,
        "doc-1",
        "atlas.md",
        f"child {chunk_id}",
        "full parent context",
        ("Atlas",),
        (1,),
        score,
    )


def test_rrf_rewards_results_found_by_both_channels():
    vector = [candidate("shared", 0.91), candidate("semantic", 0.8)]
    keyword = [candidate("exact", 0.7), candidate("shared", 0.6)]
    results = reciprocal_rank_fusion(vector, keyword, limit=3, constant=60)
    assert results[0].chunk_id == "shared"
    assert results[0].vector_rank == 1
    assert results[0].keyword_rank == 2
    assert results[1].context == "full parent context"
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([], [], 0)


class FakeEmbeddingProvider:
    dimensions = 3

    def embed(self, texts):
        return [[float(len(text)), 0.5, 1.0] for text in texts]


class FakeStore:
    def __init__(self):
        self.ingested = None

    def find_ready_document(self, *_args):
        return None

    def ingest(self, chunks, embeddings, **metadata):
        self.ingested = (chunks, embeddings, metadata)
        return IngestionResult("doc", "version", chunks.document.filename, 1, 1, False)

    def vector_candidates(self, *_args):
        return [candidate("shared", 0.9), candidate("vector", 0.8)]

    def keyword_candidates(self, *_args):
        return [candidate("shared", 0.7), candidate("keyword", 0.6)]


def test_knowledge_service_ingests_and_searches():
    store = FakeStore()
    service = KnowledgeService(store, FakeEmbeddingProvider())
    result = service.ingest(
        "atlas.md", b"# Atlas\n\nPayment testing is pending.", "text/markdown", "acme", "u1", "team"
    )
    assert result.filename == "atlas.md"
    assert store.ingested[2]["tenant_id"] == "acme"
    hits = service.search("payment", "acme", "u1", ["team"], 3)
    assert hits[0].chunk_id == "shared"
    with pytest.raises(ValueError):
        service.search(" ", "acme", "u1", ["team"], 3)
    with pytest.raises(ValueError):
        service.search("payment", "acme", "u1", ["secret"], 3)
    with pytest.raises(ValueError):
        service.ingest("a.txt", b"x", "text/plain", "acme", "u1", "secret")


def test_knowledge_service_skips_embedding_for_duplicate():
    expected = IngestionResult("doc", "version", "atlas.md", 1, 1, True)

    class DuplicateStore(FakeStore):
        def find_ready_document(self, *_args):
            return expected

    class EmbeddingsMustNotRun(FakeEmbeddingProvider):
        def embed(self, _texts):
            raise AssertionError("duplicate documents must not be embedded again")

    service = KnowledgeService(DuplicateStore(), EmbeddingsMustNotRun())
    result = service.ingest(
        "atlas.md", b"# Atlas\n\nKnown content.", "text/markdown", "acme", "u1", "team"
    )
    assert result == expected


def test_knowledge_service_reindexes_existing_child_chunks():
    class ReindexStore(FakeStore):
        def reindex_payload(self, document_id, tenant_id):
            assert (document_id, tenant_id) == ("doc-1", "acme")
            return "version-1", [("child-1", "Payment testing")]

        def replace_embeddings_and_audit(self, *args):
            self.reindex_args = args
            return 1

    store = ReindexStore()
    refreshed = KnowledgeService(store, FakeEmbeddingProvider()).reindex("doc-1", "acme", "u1")
    assert refreshed == 1
    assert store.reindex_args[0:3] == ("doc-1", "acme", "version-1")
    assert store.reindex_args[-1] == "u1"


def test_openai_embedding_adapter_orders_and_validates(monkeypatch):
    class FakeEmbeddings:
        def create(self, **_kwargs):
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=1, embedding=[4.0, 5.0, 6.0]),
                    SimpleNamespace(index=0, embedding=[1.0, 2.0, 3.0]),
                ]
            )

    monkeypatch.setattr(
        "decisiongraph.knowledge.embeddings.OpenAI",
        lambda **_kwargs: SimpleNamespace(embeddings=FakeEmbeddings()),
    )
    provider = OpenAIEmbeddingProvider("test-key", "test-model", 3)
    assert provider.embed([]) == []
    assert provider.embed(["one", "two"])[0] == [1.0, 2.0, 3.0]
    with pytest.raises(ValueError):
        OpenAIEmbeddingProvider("", "test-model")


class FakeCursor:
    def __init__(self, fetchones=None, rows=None):
        self.fetchones = iter(fetchones or [])
        self.rows = rows or []
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))

    def fetchone(self):
        return next(self.fetchones)

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


def test_postgres_store_inserts_parent_and_child_chunks(monkeypatch):
    cursor = FakeCursor(fetchones=[None, {"next_version": 1}])
    connection = FakeConnection(cursor)
    monkeypatch.setattr(
        "decisiongraph.knowledge.store.psycopg.connect", lambda *_a, **_k: connection
    )
    document = parse_document("atlas.md", b"# Atlas\n\nPayment retry testing is pending.")
    chunks = StructureAwareChunker().chunk(document)
    embeddings = [[0.1, 0.2, 0.3] for _ in chunks.children]
    result = PostgresKnowledgeStore("postgres://test").ingest(
        chunks, embeddings, "acme", "u1", "team"
    )
    assert result.deduplicated is False
    assert connection.committed
    assert any("INSERT INTO chunks" in statement for statement, _ in cursor.statements)
    assert _vector_literal([0.1, 0.2]) == "[0.1,0.2]"
    with pytest.raises(ValueError):
        PostgresKnowledgeStore("postgres://test").ingest(chunks, [], "acme", "u1", "team")


def test_postgres_store_deduplicates_ready_version(monkeypatch):
    document_id, version_id = uuid4(), uuid4()
    document = parse_document("atlas.md", b"# Atlas\n\nSame content.")
    chunks = StructureAwareChunker().chunk(document)
    cursor = FakeCursor(
        fetchones=[
            {"id": document_id, "checksum_sha256": document.checksum_sha256},
            {"id": version_id},
        ]
    )
    monkeypatch.setattr(
        "decisiongraph.knowledge.store.psycopg.connect",
        lambda *_a, **_k: FakeConnection(cursor),
    )
    result = PostgresKnowledgeStore("postgres://test").ingest(
        chunks, [[0.1] for _ in chunks.children], "acme", "u1", "team"
    )
    assert result.deduplicated is True
    assert result.document_id == str(document_id)


def test_postgres_store_preflight_duplicate_lookup(monkeypatch):
    document_id, version_id = uuid4(), uuid4()
    cursor = FakeCursor(
        fetchones=[
            {
                "document_id": document_id,
                "version_id": version_id,
                "parents": 2,
                "children": 5,
            }
        ]
    )
    monkeypatch.setattr(
        "decisiongraph.knowledge.store.psycopg.connect",
        lambda *_a, **_k: FakeConnection(cursor),
    )
    store = PostgresKnowledgeStore("postgres://test")
    found = store.find_ready_document("acme", "atlas.md", "checksum")
    assert found and found.deduplicated
    assert found.child_chunks == 5

    empty_cursor = FakeCursor(fetchones=[None])
    monkeypatch.setattr(
        "decisiongraph.knowledge.store.psycopg.connect",
        lambda *_a, **_k: FakeConnection(empty_cursor),
    )
    assert store.find_ready_document("acme", "new.md", "checksum") is None


def test_postgres_store_builds_vector_and_keyword_candidates(monkeypatch):
    row = {
        "id": uuid4(),
        "document_id": uuid4(),
        "source_name": "atlas.md",
        "content": "payment testing",
        "parent_content": None,
        "section_path": ["Atlas"],
        "page_numbers": [2],
        "raw_score": 0.75,
    }
    cursor = FakeCursor(rows=[row])
    monkeypatch.setattr(
        "decisiongraph.knowledge.store.psycopg.connect",
        lambda *_a, **_k: FakeConnection(cursor),
    )
    store = PostgresKnowledgeStore("postgres://test")
    vector = store.vector_candidates([0.1, 0.2], "acme", "u1", ["team"], 10)
    keyword = store.keyword_candidates("payment", "acme", "u1", ["team"], 10)
    assert vector[0].raw_score == 0.75
    assert keyword[0].context if hasattr(keyword[0], "context") else keyword[0].content
    assert len(cursor.statements) == 2


def test_postgres_store_loads_authorized_graph_sources(monkeypatch):
    document_id, version_id, chunk_id = uuid4(), uuid4(), uuid4()
    cursor = FakeCursor(
        rows=[
            {
                "document_id": document_id,
                "source_name": "atlas.md",
                "owner_id": "u1",
                "access_scope": "team",
                "version_id": version_id,
                "version_number": 3,
                "chunk_id": chunk_id,
                "content": "Priya owns payments.",
                "section_path": ["Ownership"],
            }
        ]
    )
    monkeypatch.setattr(
        "decisiongraph.knowledge.store.psycopg.connect",
        lambda *_a, **_k: FakeConnection(cursor),
    )
    sources = PostgresKnowledgeStore("postgres://test").graph_sources(
        str(document_id), "acme", "u1", ["team"], 50
    )
    assert sources[0][0].chunk_id == str(chunk_id)
    assert sources[0][0].section_path == ("Ownership",)
    assert sources[0][0].version_id == str(version_id)
    assert sources[0][0].version_number == 3
    assert sources[0][1:] == ("u1", "team")
