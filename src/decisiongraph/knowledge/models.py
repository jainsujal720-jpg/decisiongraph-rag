from dataclasses import dataclass


@dataclass(frozen=True)
class IngestionResult:
    document_id: str
    version_id: str
    filename: str
    parent_chunks: int
    child_chunks: int
    deduplicated: bool


@dataclass(frozen=True)
class DocumentSummary:
    document_id: str
    filename: str
    source_type: str
    access_scope: str
    owner_id: str
    latest_version_number: int
    status: str
    parent_chunks: int
    child_chunks: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DocumentDetail(DocumentSummary):
    checksum_sha256: str
    versions: tuple[dict, ...]
    events: tuple[dict, ...]


@dataclass(frozen=True)
class Candidate:
    chunk_id: str
    document_id: str
    source_name: str
    content: str
    parent_content: str | None
    section_path: tuple[str, ...]
    page_numbers: tuple[int, ...]
    raw_score: float


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    document_id: str
    source_name: str
    content: str
    context: str
    section_path: tuple[str, ...]
    page_numbers: tuple[int, ...]
    vector_rank: int | None
    keyword_rank: int | None
    vector_score: float | None
    keyword_score: float | None
    fused_score: float
