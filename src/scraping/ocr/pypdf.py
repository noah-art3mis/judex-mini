"""Local pypdf text-layer extraction, surfaced as an OCR provider.

pypdf doesn't do OCR — it reads the text layer that the PDF generator
embedded. For STF documents that means acórdãos with an intact text
stream come through cleanly and fast (<0.1 s per PDF, zero USD). Scans
and image-only PDFs return empty or garbage; that's when users switch
to a real OCR provider via `--provedor mistral|chandra|unstructured`.

Registering pypdf through the same `OCRProvider` contract as the OCR
providers keeps the extract driver's call site uniform. `extrair-pdfs
--provedor pypdf` is the default and the cost-free first tier.
"""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from src.scraping.ocr.base import ExtractResult, OCRConfig


def extract(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
    reader = PdfReader(BytesIO(pdf_bytes))
    pages_text: list[str] = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            pages_text.append(page_text)
    text = "\n".join(pages_text).strip()
    return ExtractResult(
        text=text,
        elements=None,
        pages_processed=len(reader.pages),
        provider="pypdf",
    )
