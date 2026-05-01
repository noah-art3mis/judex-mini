"""Datalab Chandra (and Marker) provider — submit + poll.

Uses the unified `/api/v1/convert` endpoint with `mode=accurate`
to route through Chandra (vs `balanced`/`fast` which route through
Marker tiers). Submit returns `request_check_url`; we poll until
`status="complete"`.

Pricing: Datalab does not publish per-page rates publicly; community
reports cluster around $3 / 1k pg for Chandra. Verify against your
own Datalab dashboard before bulk runs.

Output formats: markdown | html | json | chunks. We default to
markdown to match Mistral's primary output for cross-provider
comparability.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from judex.scraping.ocr.base import ExtractResult, OCRConfig, ProviderSpec

DEFAULT_API_URL = "https://www.datalab.to/api/v1/convert"


def _parse_complete_payload(payload: dict[str, Any], *, output_format: str) -> ExtractResult:
    text_field = output_format if output_format in {"markdown", "html"} else "markdown"
    text = (payload.get(text_field) or "").strip()
    chunks = payload.get("chunks")
    elements = chunks.get("blocks") if isinstance(chunks, dict) else None
    return ExtractResult(
        text=text,
        elements=elements,
        pages_processed=payload.get("page_count"),
        provider="chandra",
    )


def submit(pdf_bytes: bytes, *, config: OCRConfig) -> str:
    """POST PDF, return request_check_url."""
    api_url = config.api_url or DEFAULT_API_URL
    r = requests.post(
        api_url,
        headers={"X-API-Key": config.api_key},
        files={"file": ("doc.pdf", pdf_bytes, "application/pdf")},
        data={
            "output_format": config.output_format,
            "mode": config.mode,
            "langs": ",".join(config.languages),
        },
        timeout=config.timeout,
    )
    r.raise_for_status()
    payload = r.json() or {}
    check_url = payload.get("request_check_url")
    if not check_url:
        raise RuntimeError(f"Chandra submit returned no request_check_url: {payload}")
    return check_url


def poll(check_url: str, *, config: OCRConfig) -> ExtractResult:
    """Block until status=complete; return ExtractResult.

    Honors `config.poll_interval` and `config.poll_max_wait`.
    """
    deadline = time.monotonic() + config.poll_max_wait
    while True:
        r = requests.get(
            check_url,
            headers={"X-API-Key": config.api_key},
            timeout=config.timeout,
        )
        r.raise_for_status()
        payload = r.json() or {}
        status = (payload.get("status") or "").lower()
        if status == "complete":
            return _parse_complete_payload(payload, output_format=config.output_format)
        if status in {"error", "failed"}:
            raise RuntimeError(f"Chandra job failed: {payload}")
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Chandra job did not complete in {config.poll_max_wait}s "
                f"(last status: {status})"
            )
        time.sleep(config.poll_interval)


def extract(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
    return poll(submit(pdf_bytes, config=config), config=config)


# ----- ProviderSpec ---------------------------------------------------------


def cost(n_pages: int, config: OCRConfig) -> float:
    # All three Chandra modes (accurate / balanced / fast) share the same
    # ~$3 / 1k community-reported rate as of 2026-04. Verify against the
    # Datalab dashboard before bulk runs.
    return n_pages * 3.0 / 1000


def wall(n_pdfs: int, config: OCRConfig) -> float:
    # ~15 s / pdf (2026-04-19 bakeoff anchor).
    return n_pdfs * 15.0


SPEC = ProviderSpec(
    name="chandra",
    extract=extract,
    cost=cost,
    wall=wall,
    env_var="DATALAB_API_KEY",
    supports_batch=False,
)
