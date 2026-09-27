import hashlib

import tiktoken

from decisiongraph.ingestion.models import Block, Chunk, ChunkedDocument, ParsedDocument


class StructureAwareChunker:
    def __init__(
        self,
        child_tokens: int = 350,
        overlap_tokens: int = 50,
        parent_tokens: int = 1200,
    ):
        if child_tokens <= 0 or parent_tokens < child_tokens:
            raise ValueError(
                "parent_tokens must be at least child_tokens, and both must be positive"
            )
        if overlap_tokens < 0 or overlap_tokens >= child_tokens:
            raise ValueError("overlap_tokens must be between zero and child_tokens")
        self.child_tokens = child_tokens
        self.overlap_tokens = overlap_tokens
        self.parent_tokens = parent_tokens
        self.encoding = tiktoken.get_encoding("cl100k_base")

    def _id(self, checksum: str, level: str, index: int, content: str) -> str:
        value = f"{checksum}:{level}:{index}:{content}".encode()
        return hashlib.sha256(value).hexdigest()[:24]

    def _parent_groups(self, document: ParsedDocument) -> list[list[Block]]:
        groups: list[list[Block]] = []
        current: list[Block] = []
        current_tokens = 0
        current_section: tuple[str, ...] | None = None
        for block in document.blocks:
            tokens = len(self.encoding.encode(block.text))
            section_changed = bool(current and block.section_path != current_section)
            size_exceeded = bool(current and current_tokens + tokens > self.parent_tokens)
            if section_changed or size_exceeded:
                groups.append(current)
                current, current_tokens = [], 0
            current.append(block)
            current_tokens += tokens
            current_section = block.section_path
        if current:
            groups.append(current)
        return groups

    def chunk(self, document: ParsedDocument) -> ChunkedDocument:
        parents: list[Chunk] = []
        children: list[Chunk] = []
        child_index = 0
        for parent_index, blocks in enumerate(self._parent_groups(document)):
            section = blocks[0].section_path
            body = "\n\n".join(block.text for block in blocks)
            prefix = f"Section: {' > '.join(section)}\n\n" if section else ""
            parent_content = prefix + body
            pages = tuple(sorted({block.page_number for block in blocks if block.page_number}))
            parent_id = self._id(document.checksum_sha256, "parent", parent_index, parent_content)
            parents.append(
                Chunk(
                    parent_id,
                    "parent",
                    parent_index,
                    parent_content,
                    len(self.encoding.encode(parent_content)),
                    None,
                    pages,
                    section,
                )
            )

            token_ids = self.encoding.encode(parent_content)
            step = self.child_tokens - self.overlap_tokens
            for start in range(0, len(token_ids), step):
                window = token_ids[start : start + self.child_tokens]
                if not window:
                    break
                content = self.encoding.decode(window).strip()
                chunk_id = self._id(document.checksum_sha256, "child", child_index, content)
                children.append(
                    Chunk(
                        chunk_id,
                        "child",
                        child_index,
                        content,
                        len(window),
                        parent_id,
                        pages,
                        section,
                        {"token_start": start},
                    )
                )
                child_index += 1
                if start + self.child_tokens >= len(token_ids):
                    break
        return ChunkedDocument(document, tuple(parents), tuple(children))
