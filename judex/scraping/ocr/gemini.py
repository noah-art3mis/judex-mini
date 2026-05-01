"""Gemini 2.5 Flash OCR provider — sync + batch flows.

Calls Google's GenAI REST API directly (no SDK). Vision input via
``inline_data`` with base64-encoded PDF bytes — Gemini natively accepts
PDFs up to 50 MB / 1000 pages per request.

Sync flow (1 HTTP call):
  POST /v1beta/models/gemini-2.5-flash:generateContent
  parts=[{inline_data: {mime_type: application/pdf, data: <b64>}}, {text: prompt}]

Batch flow (50 % cost reduction, ~24 h SLA):
  1. Build JSONL of requests (one line per PDF)
  2. POST /upload/v1beta/files (resumable upload) → file_uri
  3. POST /v1beta/batches → batch name
  4. Poll  /v1beta/batches/{name} until state=BATCH_STATE_SUCCEEDED
  5. GET   {output_uri} → JSONL of OCR results

Pricing (2026-04 paid tier):
  sync   $0.30 / 1M input tok, $2.50 / 1M output tok
  batch  $0.15 / 1M input tok, $1.25 / 1M output tok

Per-page accounting (Google's published constants):
  - PDF page = 258 input tokens
  - Born-digital extracted native text = $0 input
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any, Iterable, Iterator

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from judex.scraping.ocr.base import ExtractResult, OCRConfig, ProviderSpec

DEFAULT_API_BASE = "https://generativelanguage.googleapis.com"
DEFAULT_MODEL = "gemini-2.5-flash"

# Gemini 2.5 Flash pricing (paid tier, USD per 1M tokens).
_PRICE_INPUT_PER_M_USD = 0.30
_PRICE_OUTPUT_PER_M_USD = 2.50
_BATCH_DISCOUNT = 0.5  # batch is 50% off both rates


def _is_retryable_http(exc: BaseException) -> bool:
    """Retry on 429/500/502/503/504 — Gemini returns 503 'high demand' often.
    Non-retry on 4xx (auth / bad request); raise immediately."""
    if isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status in {429, 500, 502, 503, 504}
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    return False


_retry_gemini = retry(
    retry=retry_if_exception(_is_retryable_http),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)

# OCR prompt — minimal instruction; Gemini does best when told what
# *not* to do (commentary, formatting suggestions, refusals).
OCR_PROMPT = (
    "Extract the full text from this document. Output only the document "
    "content as plain text, preserving paragraph breaks and reading order. "
    "Do not add commentary, headers, or formatting markup. If a page is "
    "blank or unreadable, output [PÁGINA EM BRANCO] for that page."
)


def _build_part(pdf_bytes: bytes) -> dict[str, Any]:
    """Inline-data part for a PDF — works for files <20 MB; larger files
    should use the Files API path (not implemented here, would only matter
    for STF docs at the p99+ tail)."""
    return {
        "inline_data": {
            "mime_type": "application/pdf",
            "data": base64.b64encode(pdf_bytes).decode("ascii"),
        },
    }


def _parse_sync_response(payload: dict[str, Any], *, batch: bool = False) -> ExtractResult:
    text_parts: list[str] = []
    candidates = payload.get("candidates") or []
    for c in candidates:
        content = c.get("content") or {}
        for part in content.get("parts") or []:
            t = part.get("text")
            if t:
                text_parts.append(t)
    text = "\n".join(text_parts).strip()
    usage = payload.get("usageMetadata") or {}
    in_tok = usage.get("promptTokenCount")
    out_tok = usage.get("candidatesTokenCount")
    cost: float | None = None
    if isinstance(in_tok, int) and isinstance(out_tok, int):
        rate_in = _PRICE_INPUT_PER_M_USD * (_BATCH_DISCOUNT if batch else 1.0)
        rate_out = _PRICE_OUTPUT_PER_M_USD * (_BATCH_DISCOUNT if batch else 1.0)
        cost = (in_tok / 1_000_000 * rate_in) + (out_tok / 1_000_000 * rate_out)
    return ExtractResult(
        text=text,
        elements=candidates,
        # Gemini doesn't return a per-PDF page count; runner falls back
        # to manifest n_pages.
        pages_processed=None,
        provider="gemini",
        usd_cost=cost,
        input_tokens=in_tok if isinstance(in_tok, int) else None,
        output_tokens=out_tok if isinstance(out_tok, int) else None,
    )


@_retry_gemini
def _post_generate(url: str, *, headers: dict, body: dict, timeout: int) -> dict:
    r = requests.post(url, headers=headers, json=body, timeout=timeout)
    r.raise_for_status()
    return r.json() or {}


def extract(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
    """Sync OCR via generateContent. Retries on 503 'high demand' up to 5x."""
    base = config.api_url or DEFAULT_API_BASE
    model = config.model if config.model and config.model.startswith("gemini") else DEFAULT_MODEL
    url = f"{base}/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{
            "role": "user",
            "parts": [_build_part(pdf_bytes), {"text": OCR_PROMPT}],
        }],
        "generationConfig": {
            "temperature": 0.0,
            # Cap output to avoid runaway cost on degenerate inputs;
            # 32k tokens is generous for most STF PDFs (~50+ pages).
            "maxOutputTokens": 32768,
        },
    }
    payload = _post_generate(
        url,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": config.api_key,
        },
        body=body,
        timeout=config.timeout,
    )
    return _parse_sync_response(payload, batch=config.batch)


# ---------------------------------------------------------------------------
# Batch API — 50 % cost reduction, async (~24 h SLA).
# ---------------------------------------------------------------------------


def build_batch_jsonl(
    items: Iterable[tuple[str, bytes]], *, model: str = DEFAULT_MODEL,
) -> str:
    """Render (custom_id, pdf_bytes) tuples to JSONL for a batch job.

    Each line follows Google's batch-input format:
      {"key": <custom_id>, "request": <generateContent body>}
    """
    lines: list[str] = []
    for custom_id, pdf_bytes in items:
        body = {
            "contents": [{
                "role": "user",
                "parts": [_build_part(pdf_bytes), {"text": OCR_PROMPT}],
            }],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 32768,
            },
        }
        lines.append(json.dumps({
            "key": custom_id,
            "request": body,
        }, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


def _upload_file(
    jsonl_bytes: bytes, *, api_key: str, base: str, timeout: int,
) -> str:
    """Upload via the Files API resumable endpoint. Returns the file URI."""
    headers = {
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(len(jsonl_bytes)),
        "X-Goog-Upload-Header-Content-Type": "application/jsonl",
        "Content-Type": "application/json",
    }
    init = requests.post(
        f"{base}/upload/v1beta/files",
        headers={**headers, "x-goog-api-key": api_key},
        json={"file": {"display_name": "ocr_batch.jsonl"}},
        timeout=timeout,
    )
    init.raise_for_status()
    upload_url = init.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise RuntimeError(f"resumable upload init missing upload URL: {init.headers}")
    finish = requests.post(
        upload_url,
        headers={
            "Content-Length": str(len(jsonl_bytes)),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        },
        data=jsonl_bytes,
        timeout=timeout,
    )
    finish.raise_for_status()
    file_obj = finish.json().get("file") or {}
    name = file_obj.get("name")
    if not name:
        raise RuntimeError(f"upload did not return a file name: {finish.json()}")
    return name  # e.g. "files/abc-123"


def submit_batch(
    jsonl_bytes: bytes, *, config: OCRConfig,
) -> str:
    """Upload + create a batch job. Returns the batch name."""
    base = config.api_url or DEFAULT_API_BASE
    file_name = _upload_file(
        jsonl_bytes, api_key=config.api_key, base=base, timeout=config.timeout,
    )
    model = config.model if config.model.startswith("gemini") else DEFAULT_MODEL
    body = {
        "batch": {
            "displayName": "judex-ocr-batch",
            "inputConfig": {"fileName": file_name},
        },
    }
    r = requests.post(
        f"{base}/v1beta/models/{model}:batchGenerateContent",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": config.api_key,
        },
        json=body,
        timeout=config.timeout,
    )
    r.raise_for_status()
    name = r.json().get("name")
    if not name:
        raise RuntimeError(f"batch creation did not return a name: {r.json()}")
    return name


def get_batch_status(name: str, *, config: OCRConfig) -> dict[str, Any]:
    base = config.api_url or DEFAULT_API_BASE
    r = requests.get(
        f"{base}/v1beta/{name}",
        headers={"x-goog-api-key": config.api_key},
        timeout=config.timeout,
    )
    r.raise_for_status()
    return r.json()


def wait_for_batch(
    name: str, *, config: OCRConfig,
    poll_interval: float = 60.0, max_wait: float = 86400.0,
) -> dict[str, Any]:
    """Block until the batch reaches a terminal state."""
    deadline = time.monotonic() + max_wait
    terminal = {
        "BATCH_STATE_SUCCEEDED",
        "BATCH_STATE_FAILED",
        "BATCH_STATE_CANCELLED",
        "BATCH_STATE_EXPIRED",
    }
    while True:
        status = get_batch_status(name, config=config)
        state = (status.get("metadata") or {}).get("state") or status.get("state")
        if state in terminal:
            return status
        if time.monotonic() > deadline:
            raise TimeoutError(f"Gemini batch {name} did not finish in {max_wait}s")
        time.sleep(poll_interval)


def download_batch_output(
    output_file_name: str, *, config: OCRConfig,
) -> Iterator[dict[str, Any]]:
    """Stream the batch output JSONL. Yields {key, response, error?} per line."""
    base = config.api_url or DEFAULT_API_BASE
    r = requests.get(
        f"{base}/v1beta/{output_file_name}:download",
        params={"alt": "media"},
        headers={"x-goog-api-key": config.api_key},
        timeout=config.timeout,
        stream=True,
    )
    r.raise_for_status()
    for raw in r.iter_lines(decode_unicode=True):
        if not raw:
            continue
        yield json.loads(raw)


def parse_batch_results(
    rows: Iterable[dict[str, Any]],
) -> dict[str, ExtractResult]:
    """Map result rows to {custom_id: ExtractResult}. Failed rows dropped."""
    out: dict[str, ExtractResult] = {}
    for row in rows:
        cid = row.get("key")
        resp = row.get("response") or {}
        if not isinstance(cid, str) or not isinstance(resp, dict):
            continue
        if not resp.get("candidates"):
            continue
        out[cid] = _parse_sync_response(resp)
    return out


# ----- ProviderSpec ---------------------------------------------------------

# Gemini 2.5 Flash list rates (2026-04 paid tier). Per-page accounting:
# 258 input tokens / page (Google's published constant) plus ~500 output
# tokens / page typical. Real cost depends on actual output tokens and the
# "free native text" discount on born-digital pages — these are budget
# defaults that match the rates in the prior central PRICING table.
_SYNC_USD_PER_PAGE = 1.32 / 1000   # 258 * 0.30/1M + 500 * 2.50/1M
_BATCH_USD_PER_PAGE = 0.66 / 1000  # 50 % off both rates

_SYNC_WALL_PER_PDF_S = 5.0  # vendor cookbook anchor for typical 5-page PDF
_BATCH_SUBMIT_WALL_S = 30.0  # submit-and-exit shape, like Mistral batch


def cost(n_pages: int, config: OCRConfig) -> float:
    rate = _BATCH_USD_PER_PAGE if config.batch else _SYNC_USD_PER_PAGE
    return n_pages * rate


def wall(n_pdfs: int, config: OCRConfig) -> float:
    if config.batch:
        return _BATCH_SUBMIT_WALL_S
    return n_pdfs * _SYNC_WALL_PER_PDF_S


SPEC = ProviderSpec(
    name="gemini",
    extract=extract,
    cost=cost,
    wall=wall,
    env_var="GEMINI_API_KEY",
    supports_batch=True,
)
