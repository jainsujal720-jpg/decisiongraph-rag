import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from decisiongraph.graph.extraction import OpenAIGraphExtractor, canonicalize, stable_id
from decisiongraph.graph.models import (
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    GraphHit,
    GraphSource,
)
from decisiongraph.graph.service import GraphService
from decisiongraph.graph.store import RELATION_CYPHER, UPSERT_CYPHER, Neo4jGraphStore


def extraction_result():
    return ExtractionResult(
        entities=[
            ExtractedEntity(
                name="Atlas Launch", entity_type="Initiative", description="Product launch"
            ),
            ExtractedEntity(name="Priya Shah", entity_type="Person", description="Payments owner"),
        ],
        relations=[
            ExtractedRelation(
                source="Priya Shah",
                target="Atlas Launch",
                relation_type="OWNS",
                evidence="Priya Shah owns the launch workstream.",
            )
        ],
    )


def test_graph_models_canonicalization_and_endpoint_validation():
    assert canonicalize("  Payment-Reliability! ") == "payment reliability"
    assert stable_id("PERSON", "priya") == stable_id("PERSON", "priya")
    with pytest.raises(ValidationError):
        ExtractionResult(
            entities=[ExtractedEntity(name="Atlas", entity_type="Initiative")],
            relations=[
                ExtractedRelation(
                    source="Unknown", target="Atlas", relation_type="OWNS", evidence="evidence"
                )
            ],
        )
    with pytest.raises(ValidationError):
        ExtractionResult(
            entities=[
                ExtractedEntity(name="Atlas", entity_type="Initiative"),
                ExtractedEntity(name="ATLAS", entity_type="Product"),
            ],
            relations=[],
        )


def test_openai_graph_extractor_validates_and_deduplicates(monkeypatch):
    payload = extraction_result().model_dump()
    payload["entities"].append(payload["entities"][0])
    payload["relations"].append(payload["relations"][0])

    class Completions:
        def create(self, **kwargs):
            assert kwargs["response_format"]["type"] == "json_schema"
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr("decisiongraph.graph.extraction.OpenAI", lambda **_kwargs: client)
    extractor = OpenAIGraphExtractor("test-key", "test-model")
    result = extractor.extract("Priya Shah owns the launch workstream.")
    assert len(result.entities) == 2
    assert len(result.relations) == 1
    with pytest.raises(ValueError):
        OpenAIGraphExtractor("", "test-model")


def test_openai_graph_extractor_drops_unquoted_relation_evidence(monkeypatch):
    payload = extraction_result().model_dump()
    payload["relations"][0]["evidence"] = "This sentence was invented."

    class Completions:
        def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr("decisiongraph.graph.extraction.OpenAI", lambda **_kwargs: client)
    result = OpenAIGraphExtractor("test-key", "test-model").extract(
        "Priya Shah owns the launch workstream."
    )
    assert result.relations == []


def test_openai_graph_extractor_drops_dangling_edges_without_losing_valid_ones(monkeypatch):
    payload = extraction_result().model_dump()
    payload["relations"].append({
        "source": "Unlisted Reviewer", "target": "Atlas Launch",
        "relation_type": "REVIEWS", "evidence": "Priya Shah owns the launch workstream.",
    })
    payload["relations"][0]["source"] = "PRIYA SHAH"  # normalizes to the known entity

    class Completions:
        def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr("decisiongraph.graph.extraction.OpenAI", lambda **_kwargs: client)
    result = OpenAIGraphExtractor("test-key", "test-model").extract(
        "Priya Shah owns the launch workstream."
    )
    assert len(result.relations) == 1
    assert result.relations[0].source == "Priya Shah"
    assert result.relations[0].target == "Atlas Launch"


class FakeKnowledgeStore:
    def __init__(self, sources):
        self.sources = sources

    def graph_sources(self, *_args):
        return self.sources


class FakeExtractor:
    def extract(self, _text):
        return extraction_result()


class FakeGraphStore:
    def __init__(self):
        self.upserts = []

    def upsert_extraction(self, *args):
        self.upserts.append(args)

    def search(self, *_args):
        return [
            GraphHit(
                "entity-1",
                "Atlas Launch",
                "INITIATIVE",
                "Product launch",
                "Priya Shah",
                "OWNS",
                "Atlas Launch",
                "Priya owns the launch.",
                "atlas.md",
                "chunk-1",
                1.0,
            )
        ]

    def delete_document(self, *args):
        self.deleted = args


def test_graph_service_enriches_and_searches():
    source = GraphSource("doc-1", "chunk-1", "atlas.md", "content", ("Atlas",), "version-2", 2)
    graph_store = FakeGraphStore()
    service = GraphService(
        FakeKnowledgeStore([(source, "u1", "team")]), graph_store, FakeExtractor()
    )
    result = service.enrich("doc-1", "acme", "u1", ["team"])
    assert result.processed_chunks == 1
    assert result.entity_mentions == 2
    assert result.relationships == 1
    assert len(graph_store.upserts) == 1
    service.delete_document("acme", "doc-1")
    assert graph_store.deleted == ("acme", "doc-1")
    assert service.search("Atlas", "acme", "u1", ["team"], 10)[0].entity_name == "Atlas Launch"
    with pytest.raises(ValueError):
        service.search(" ", "acme", "u1", ["team"], 10)
    with pytest.raises(ValueError):
        service.search("Atlas", "acme", "u1", ["secret"], 10)
    with pytest.raises(ValueError):
        GraphService(FakeKnowledgeStore([]), graph_store, FakeExtractor()).enrich(
            "missing", "acme", "u1", ["team"]
        )


class FakeResult:
    def consume(self):
        return None


class FakeRecord:
    def __init__(self, data):
        self._data = data

    def data(self):
        return self._data


class FakeSession:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def run(self, query, parameters=None):
        self.calls.append((query, parameters))
        if "queryNodes" in query:
            return [
                FakeRecord(
                    {
                        "entity_id": "entity-1",
                        "entity_name": "Atlas Launch",
                        "entity_type": "INITIATIVE",
                        "description": "Product launch",
                        "source_entity": "Priya Shah",
                        "relation_type": "OWNS",
                        "target_entity": "Atlas Launch",
                        "evidence": "Priya owns the launch.",
                        "source_name": "atlas.md",
                        "chunk_id": "chunk-1",
                        "graph_score": 1.2,
                    }
                )
            ]
        return FakeResult()


class FakeDriver:
    def __init__(self):
        self.session_value = FakeSession()
        self.closed = False

    def session(self):
        return self.session_value

    def close(self):
        self.closed = True


def test_neo4j_store_upserts_evidence_graph_and_searches(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(
        "decisiongraph.graph.store.GraphDatabase.driver", lambda *_args, **_kwargs: driver
    )
    store = Neo4jGraphStore("bolt://test", "neo4j", "password")
    source = GraphSource("doc-1", "chunk-1", "atlas.md", "content", ("Atlas",), "version-2", 2)
    store.upsert_extraction("acme", "u1", "team", source, extraction_result())
    assert driver.session_value.calls[0][0] == UPSERT_CYPHER
    assert driver.session_value.calls[1][0] == RELATION_CYPHER
    parameters = driver.session_value.calls[1][1]
    assert parameters["relations"][0]["relation_type"] == "OWNS"
    assert parameters["version_id"] == "version-2"
    assert parameters["version_number"] == 2
    assert "latest_version_number" in UPSERT_CYPHER
    hits = store.search("Atlas", "acme", "u1", ["team"], 10)
    assert hits[0].source_name == "atlas.md"
    assert driver.session_value.calls[2][1]["query"] == "Atlas"
    store.close()
    assert driver.closed
