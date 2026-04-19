"""Unstructured SaaS API provider.

Equivalent to the inlined logic in `scripts/reextract_unstructured.py`,
extracted into a reusable module. The script keeps its own copy for
backwards compat; this module is the forward-looking entry point used
by the unified dispatcher.

Endpoint: POST https://api.unstructuredapp.io/general/v0/general
Auth: `unstructured-api-key` header.
Pricing: $10 / 1k pages on `hi_res`, $1 / 1k on `fast`.
"""

from __future__ import annotations

from typing import Any

import requests

from src.scraping.ocr.base import ExtractResult, OCRConfig

DEFAULT_API_URL = "https://api.unstructuredapp.io/general/v0/general"


def _concat_elements(elements: Any) -> str:
    if not elements:
        return ""
    pieces: list[str] = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        txt = (el.get("text") or "").strip()
        if txt:
            pieces.append(txt)
    return "\n".join(pieces).strip()


def extract(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
    api_url = config.api_url or DEFAULT_API_URL
    headers = {
        "unstructured-api-key": config.api_key,
        "accept": "application/json",
    }
    files = {"files": ("doc.pdf", pdf_bytes, "application/pdf")}
    data: list[tuple[str, str]] = [("strategy", config.strategy)]
    for lg in config.languages:
        data.append(("languages", lg))
    r = requests.post(
        api_url, headers=headers, files=files, data=data, timeout=config.timeout,
    )
    r.raise_for_status()
    elements = r.json() or []
    if not isinstance(elements, list):
        elements = []
    return ExtractResult(
        text=_concat_elements(elements),
        elements=elements,
        pages_processed=None,
        provider="unstructured",
    )
