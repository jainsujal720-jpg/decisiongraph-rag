from dataclasses import dataclass, field


@dataclass(frozen=True)
class Block:
    kind: str
    text: str
    page_number: int | None = None
    section_path: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedDocument:
    filename: str
    media_type: str
    checksum_sha256: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    level: str
    chunk_index: int
    content: str
    token_count: int
    parent_chunk_id: str | None
    page_numbers: tuple[int, ...]
    section_path: tuple[str, ...]
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ChunkedDocument:
    document: ParsedDocument
    parents: tuple[Chunk, ...]
    children: tuple[Chunk, ...]
