"""PaddleOCR client — calls the Modal-hosted endpoint."""

from __future__ import annotations

from judex.scraping.ocr._modal_client import call_modal
from judex.scraping.ocr.base import ExtractResult, OCRConfig, ProviderSpec


def extract(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
    return call_modal("paddle_extract", pdf_bytes, provider="paddle")


def cost(n_pages: int, config: OCRConfig) -> float:
    # Modal-hosted on a10 — placeholder per 2026-04-30 cost research.
    # Real $/1k must come from Modal billing aggregated post-run.
    return n_pages * 0.080 / 1000


def wall(n_pdfs: int, config: OCRConfig) -> float:
    # Anchor pending — first bakeoff against the Modal endpoint will set this.
    raise NotImplementedError(
        "paddle wall anchor pending; refresh from the next OCR bakeoff"
    )


SPEC = ProviderSpec(
    name="paddle",
    extract=extract,
    cost=cost,
    wall=wall,
    env_var="",
    supports_batch=False,
)
