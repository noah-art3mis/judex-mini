"""Shared client wrapper for Modal-hosted OCR endpoints.

The three Modal-hosted providers (surya, paddle, tesseract) all do the
same thing: look up a function in the deployed `judex-ocr-bakeoff` app
and call `.remote(pdf_bytes)`. Centralized here to avoid copy-paste.
"""

from __future__ import annotations

import modal

from judex.scraping.ocr.base import ExtractResult, OCRConfig

APP_NAME = "judex-ocr-bakeoff"


def call_modal(function_name: str, pdf_bytes: bytes, *, provider: str) -> ExtractResult:
    """Look up `function_name` in the deployed app and run it remotely."""
    fn = modal.Function.from_name(APP_NAME, function_name)
    result = fn.remote(pdf_bytes)
    return ExtractResult(
        text=result.get("text", ""),
        elements=None,
        pages_processed=result.get("n_pages"),
        provider=provider,
    )


def _accept_config(_: OCRConfig) -> None:
    """No-op — Modal-hosted providers don't read OCRConfig fields today.
    Kept as an explicit hook so callers know the parameter is intentional."""
    return None
