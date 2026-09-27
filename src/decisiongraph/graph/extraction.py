import json
import re
from hashlib import sha256

from openai import OpenAI

from decisiongraph.graph.models import ExtractionResult

EXTRACTION_SCHEMA = {
    "name": "knowledge_graph_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "entity_type": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["name", "entity_type", "description"],
                },
            },
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                        "relation_type": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["source", "target", "relation_type", "evidence"],
                },
            },
        },
        "required": ["entities", "relations"],
    },
}


def canonicalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def stable_id(*values: str) -> str:
    return sha256(":".join(values).encode()).hexdigest()[:24]


class OpenAIGraphExtractor:
    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for graph extraction")
        self.model = model
        self.client = OpenAI(api_key=api_key)

    def extract(self, text: str) -> ExtractionResult:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract only explicitly supported product-intelligence entities and "
                        "relationships. Use consistent singular names and concise uppercase "
                        "relation types. Evidence must be copied from the supplied text. Do not "
                        "infer facts that are not stated."
                    ),
                },
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_schema", "json_schema": EXTRACTION_SCHEMA},
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("The extraction model returned no structured content")
        payload = self._normalize_payload(json.loads(content))
        result = ExtractionResult.model_validate(payload)
        return self._deduplicate(result, text)

    @staticmethod
    def _normalize_payload(payload: dict) -> dict:
        entities = {}
        for entity in payload.get("entities", []):
            name = canonicalize(str(entity.get("name", "")))
            if name:
                entities.setdefault(name, entity)
        relations = {}
        for relation in payload.get("relations", []):
            source = canonicalize(str(relation.get("source", "")))
            target = canonicalize(str(relation.get("target", "")))
            # Structured JSON constrains shape, not the endpoint invariant.
            # Drop dangling edges; never invent an entity to complete one.
            if source not in entities or target not in entities:
                continue
            relation = {**relation,
                        "source": entities[source]["name"],
                        "target": entities[target]["name"]}
            key = (
                source,
                target,
                canonicalize(str(relation.get("relation_type", ""))),
                canonicalize(str(relation.get("evidence", ""))),
            )
            relations.setdefault(key, relation)
        return {"entities": list(entities.values()), "relations": list(relations.values())}

    @staticmethod
    def _deduplicate(result: ExtractionResult, source_text: str) -> ExtractionResult:
        entities = {}
        for entity in result.entities:
            key = canonicalize(entity.name)
            entities.setdefault(key, entity)
        relations = {}
        for relation in result.relations:
            if canonicalize(relation.evidence) not in canonicalize(source_text):
                continue
            key = (
                canonicalize(relation.source),
                canonicalize(relation.target),
                canonicalize(relation.relation_type),
                canonicalize(relation.evidence),
            )
            relations.setdefault(key, relation)
        return ExtractionResult(
            entities=list(entities.values()), relations=list(relations.values())
        )
