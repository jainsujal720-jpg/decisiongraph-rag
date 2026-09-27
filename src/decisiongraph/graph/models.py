from dataclasses import dataclass

from pydantic import BaseModel, Field, model_validator


class ExtractedEntity(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    entity_type: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)


class ExtractedRelation(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=200)
    relation_type: str = Field(min_length=1, max_length=100)
    evidence: str = Field(min_length=1, max_length=1000)


class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity]
    relations: list[ExtractedRelation]

    @model_validator(mode="after")
    def relations_reference_entities(self):
        names = {entity.name.casefold() for entity in self.entities}
        if len(names) != len(self.entities):
            raise ValueError("Entity names must be unique within one extraction")
        for relation in self.relations:
            if relation.source.casefold() not in names or relation.target.casefold() not in names:
                raise ValueError("Every relation endpoint must appear in entities")
        return self


@dataclass(frozen=True)
class GraphSource:
    document_id: str
    chunk_id: str
    source_name: str
    content: str
    section_path: tuple[str, ...]
    version_id: str = ""
    version_number: int = 1


@dataclass(frozen=True)
class GraphEnrichmentResult:
    document_id: str
    processed_chunks: int
    entity_mentions: int
    relationships: int


@dataclass(frozen=True)
class GraphHit:
    entity_id: str
    entity_name: str
    entity_type: str
    description: str
    source_entity: str | None
    relation_type: str | None
    target_entity: str | None
    evidence: str | None
    source_name: str | None
    chunk_id: str | None
    graph_score: float
