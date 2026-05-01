"""Tesseract client — calls the Modal-hosted endpoint."""

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
