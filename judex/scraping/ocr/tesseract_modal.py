"""Tesseract OCR via the Modal-hosted endpoint.

Sibling of ``judex/scraping/ocr/tesseract.py`` (the local-subprocess
version). Same OCR engine, same Portuguese language pack — the
difference is *where* the CPU cycles run. Use this provider when a
sharded sweep needs more parallelism than the local host gives you;
Modal's container fanout (and its ~10-shard concurrency cap) is the
production-scale recipe behind the year-of-HC cost projections in
``docs/cost-estimates.md``.

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
    return call_modal("tesseract_extract", pdf_bytes, provider="tesseract_modal")


def cost(n_pages: int, config: OCRConfig) -> float:
    # Modal-hosted on cpu — placeholder per 2026-04-30 cost research.
    return n_pages * 0.140 / 1000


def wall(n_pdfs: int, config: OCRConfig) -> float:
    raise NotImplementedError(
        "tesseract_modal wall anchor pending; refresh from the next OCR bakeoff"
    )


SPEC = ProviderSpec(
    name="tesseract_modal",
    extract=extract,
    cost=cost,
    wall=wall,
    env_var="",
    supports_batch=False,
)
