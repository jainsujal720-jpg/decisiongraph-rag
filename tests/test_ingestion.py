import io

import pymupdf
from docx import Document
from openpyxl import Workbook

from decisiongraph.ingestion.chunking import StructureAwareChunker
from decisiongraph.ingestion.parsers import parse_document


def test_markdown_preserves_heading_hierarchy():
    document = parse_document(
        "status.md",
        b"# Atlas\n\nLaunch overview.\n\n## Risks\n\nPayment certification is pending.",
    )
    assert [block.kind for block in document.blocks] == [
        "heading",
        "paragraph",
        "heading",
        "paragraph",
    ]
    assert document.blocks[-1].section_path == ("Atlas", "Risks")


def test_csv_and_xlsx_tables_are_normalized():
    csv_document = parse_document("risks.csv", b"risk,owner\nPayment,Priya")
    assert csv_document.blocks[0].kind == "table"
    assert "risk | owner" in csv_document.blocks[0].text

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Roadmap"
    sheet.append(["Feature", "Status"])
    sheet.append(["Payments", "Blocked"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    xlsx_document = parse_document("roadmap.xlsx", buffer.getvalue())
    assert xlsx_document.blocks[0].section_path == ("Roadmap",)
    assert "Payments | Blocked" in xlsx_document.blocks[0].text


def test_docx_and_pdf_preserve_structure_and_page():
    docx = Document()
    docx.add_heading("Launch", level=1)
    docx.add_paragraph("The launch moved to September.")
    table = docx.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Owner"
    table.cell(0, 1).text = "Risk"
    table.cell(1, 0).text = "Priya"
    table.cell(1, 1).text = "Payments"
    docx_buffer = io.BytesIO()
    docx.save(docx_buffer)
    docx_document = parse_document("launch.docx", docx_buffer.getvalue())
    assert any(block.kind == "table" for block in docx_document.blocks)
    assert docx_document.blocks[-1].section_path == ("Launch",)

    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Atlas launch evidence")
    pdf_document = parse_document("launch.pdf", pdf.tobytes())
    pdf.close()
    assert pdf_document.blocks[0].page_number == 1


def test_parent_child_chunking_is_deterministic_and_overlapping():
    text = "# Risks\n\n" + " ".join(f"risk{i}" for i in range(120))
    document = parse_document("risks.md", text.encode())
    chunker = StructureAwareChunker(child_tokens=30, overlap_tokens=5, parent_tokens=200)
    first = chunker.chunk(document)
    second = chunker.chunk(document)
    assert len(first.children) > 1
    assert first.children[0].parent_chunk_id == first.parents[0].chunk_id
    assert first.children[0].chunk_id == second.children[0].chunk_id
    long_parent_children = [
        chunk for chunk in first.children if chunk.parent_chunk_id == first.parents[-1].chunk_id
    ]
    assert long_parent_children[1].metadata["token_start"] == 25


def test_parser_rejects_empty_and_unsupported_files():
    for filename, data in [("empty.txt", b""), ("script.exe", b"unsafe")]:
        try:
            parse_document(filename, data)
        except ValueError:
            pass
        else:
            raise AssertionError("Expected the parser to reject the file")
