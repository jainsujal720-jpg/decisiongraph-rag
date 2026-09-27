import csv
import hashlib
import io
import re
from pathlib import Path

import pymupdf
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook

from decisiongraph.ingestion.models import Block, ParsedDocument

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx"}
MAX_FILE_BYTES = 20 * 1024 * 1024


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\x00", " ")).strip()


def _text_blocks(text: str) -> list[Block]:
    return [
        Block("paragraph", cleaned)
        for part in re.split(r"\n\s*\n", text)
        if (cleaned := _clean(part))
    ]


def _markdown_blocks(text: str) -> list[Block]:
    blocks: list[Block] = []
    section: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(
                Block("paragraph", _clean(" ".join(paragraph)), section_path=tuple(section))
            )
            paragraph.clear()

    for line in text.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if heading:
            flush()
            level = len(heading.group(1))
            title = _clean(heading.group(2))
            section[:] = section[: level - 1] + [title]
            blocks.append(Block("heading", title, section_path=tuple(section)))
        elif line.strip():
            paragraph.append(line.strip())
        else:
            flush()
    flush()
    return blocks


def _pdf_blocks(data: bytes) -> list[Block]:
    blocks: list[Block] = []
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        for page_number, page in enumerate(pdf, 1):
            for item in sorted(page.get_text("blocks"), key=lambda row: (row[1], row[0])):
                text = _clean(item[4])
                if text:
                    blocks.append(Block("paragraph", text, page_number=page_number))
    return blocks


def _table_text(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(cell for cell in row) for row in rows if any(row))


def _docx_blocks(data: bytes) -> list[Block]:
    document = Document(io.BytesIO(data))
    blocks: list[Block] = []
    section: list[str] = []
    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            text = _clean(item.text)
            if not text:
                continue
            style = item.style.name if item.style else ""
            match = re.match(r"Heading (\d+)", style)
            if match:
                level = int(match.group(1))
                section[:] = section[: level - 1] + [text]
                blocks.append(Block("heading", text, section_path=tuple(section)))
            else:
                blocks.append(Block("paragraph", text, section_path=tuple(section)))
        elif isinstance(item, Table):
            rows = [[_clean(cell.text) for cell in row.cells] for row in item.rows]
            if text := _table_text(rows):
                blocks.append(Block("table", text, section_path=tuple(section)))
    return blocks


def _csv_blocks(data: bytes) -> list[Block]:
    stream = io.StringIO(data.decode("utf-8-sig"))
    rows = [[_clean(cell) for cell in row] for row in csv.reader(stream)]
    text = _table_text(rows)
    return [Block("table", text, metadata={"rows": len(rows)})] if text else []


def _xlsx_blocks(data: bytes) -> list[Block]:
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    blocks: list[Block] = []
    try:
        for sheet in workbook.worksheets:
            rows = [
                [_clean(str(value)) if value is not None else "" for value in row]
                for row in sheet.iter_rows(values_only=True)
            ]
            if text := _table_text(rows):
                blocks.append(
                    Block(
                        "table",
                        text,
                        section_path=(sheet.title,),
                        metadata={"sheet": sheet.title, "rows": len(rows)},
                    )
                )
    finally:
        workbook.close()
    return blocks


def parse_document(filename: str, data: bytes, media_type: str | None = None) -> ParsedDocument:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {extension or 'missing extension'}")
    if not data:
        raise ValueError("The uploaded file is empty")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("The uploaded file exceeds the 20 MB limit")

    if extension == ".pdf":
        blocks = _pdf_blocks(data)
    elif extension == ".docx":
        blocks = _docx_blocks(data)
    elif extension == ".md":
        blocks = _markdown_blocks(data.decode("utf-8-sig"))
    elif extension == ".csv":
        blocks = _csv_blocks(data)
    elif extension == ".xlsx":
        blocks = _xlsx_blocks(data)
    else:
        blocks = _text_blocks(data.decode("utf-8-sig"))
    if not blocks:
        raise ValueError("No usable text was extracted from the document")
    return ParsedDocument(
        filename=filename,
        media_type=media_type or "application/octet-stream",
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        blocks=tuple(blocks),
    )
