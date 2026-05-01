"""Tesseract client — calls the Modal-hosted endpoint.

Bakeoff winner (2026-04-30, see docs/reports/2026-04-30-ocr-bakeoff.md):
1.04% median CER, $0.14/1k pages — 14× cheaper than Mistral sync, beats
Mistral on every quality axis. Body text faithful; reading order correct.

Known character-level errors (programmatically post-processable):
- ``§`` → digit ``8``, Roman ``I`` → digit ``1`` in some contexts.
- Ellipsis period drops: ``(...)`` → ``(..)``.
- Auth-code digit↔letter swaps: ``BFD0`` → ``BFDO``, ``21A1`` → ``2141``.
- Small-caps font confusion: ``LUÍS ROBERTO`` → ``Luís ROBERTO``.
"""

from __future__ import annotations

from judex.scraping.ocr._modal_client import call_modal
from judex.scraping.ocr.base import ExtractResult, OCRConfig, ProviderSpec


def extract(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
    return call_modal("tesseract_extract", pdf_bytes, provider="tesseract")


def cost(n_pages: int, config: OCRConfig) -> float:
    # Modal-hosted on cpu — placeholder per 2026-04-30 cost research.
    return n_pages * 0.140 / 1000


def wall(n_pdfs: int, config: OCRConfig) -> float:
    raise NotImplementedError(
        "tesseract wall anchor pending; refresh from the next OCR bakeoff"
    )


SPEC = ProviderSpec(
    name="tesseract",
    extract=extract,
    cost=cost,
    wall=wall,
    env_var="",
    supports_batch=False,
)
