# Stage 2 — Parsing, normalization and intelligent chunking

## What happens when a document is uploaded

1. Validate the extension, byte size and non-empty content.
2. Calculate a SHA-256 checksum for duplicate detection.
3. Select the parser for PDF, DOCX, TXT, Markdown, CSV or XLSX.
4. Convert the file into normalized blocks such as headings, paragraphs and tables.
5. Preserve provenance: page number, heading hierarchy, sheet name and block type.
6. Group related blocks into parent chunks.
7. Split parents into smaller overlapping child chunks.

## Why parent-child chunking

Small chunks retrieve precisely but can lack context. Large chunks provide context but may match
too many unrelated questions. DecisionGraph searches child chunks and can later expand a result
to its parent. The defaults are 350 child tokens, 50 overlap tokens and 1,200 parent tokens.

Overlap prevents a sentence near a chunk boundary from losing the surrounding words. Too much
overlap creates duplicates and increases embedding cost, so Stage 7 will compare configurations
on a gold evaluation set.

## What the preview endpoint does

`POST /v1/ingestion/preview` performs parsing and chunking but does not write to PostgreSQL,
create embeddings or modify Neo4j. This makes pipeline behavior inspectable before persistence.

## Known limitations and future improvements

- Image-only PDFs require OCR, which will be added as a confidence-gated fallback.
- PDF reading order can be wrong for multi-column layouts.
- Complex merged spreadsheet cells may lose visual relationships.
- Tables larger than the child-token limit can be split mid-row in this version.
- `cl100k_base` estimates tokens consistently, but Stage 3 will ensure the tokenizer matches the
  selected embedding model.
- Password-protected and corrupted files are rejected; they should enter a review queue later.
- Parser versions must be stored so documents can be reprocessed when extraction improves.

## Manual test

After rebuilding the Stage 2 containers, open <http://localhost:8000/docs>, expand
`POST /v1/ingestion/preview`, select `sample_docs/atlas_status.md`, execute it and inspect the
normalized parent and child chunks.

