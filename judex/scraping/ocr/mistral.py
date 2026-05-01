"""Mistral OCR provider — sync mode + batch helper.

Sync flow (3 HTTP calls per PDF):
  1. POST /v1/files               (purpose=ocr) → file_id
  2. GET  /v1/files/{id}/url      → signed_url (24 h expiry)
  3. POST /v1/ocr                 → pages[].markdown

Batch flow (50 % cost reduction, ~24 h turnaround):
  1. Build JSONL of base64-encoded PDFs (one line per request)
  2. POST /v1/files               (purpose=batch) → input_file_id
  3. POST /v1/batch/jobs          (endpoint=/v1/ocr) → job_id
  4. Poll  /v1/batch/jobs/{id}    until status=SUCCESS
  5. GET   /v1/files/{out}/content → JSONL of OCR results

Pricing: $2 / 1k pages sync, $1 / 1k batch.

Bakeoff result (2026-04-30, see docs/reports/2026-04-30-ocr-bakeoff.md):
**Replaced as production OCR by Tesseract** (1.04% median CER at
$0.14/1k pages — 14× cheaper, strictly better quality). Mistral's
scanned median CER is 32.71% because of one structural defect:

- **Reading-order bug on 1-page scanned DESPACHOs**: Mistral places
  the digital-signature footer (``Documento assinado digitalmente
  conforme MP n° 2.200-2/2001 ... e senha XXXX-XXXX-XXXX-XXXX``) on
  line 1, before the heading. Reproduced on every 1-pg DESPACHO tested
  (e0f74de6, 4752742c, 8e11f096, 16f4709e, 288744ef) and on the
  page-1-of-multi-page docs 04dff48e, c9233de1. Born-digital pages
  are fine.
- Body text is otherwise faithful — paragraph reflow excellent, no
  character drops or scrambling observed.

If keeping Mistral as a fallback: post-process to detect a leading
``Documento assinado digitalmente conforme MP`` line and move it to
the natural position (end of file for 1-pg, before the next
``HC <num> / <UF>`` page-marker for multi-pg).
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any, Iterable, Iterator

import requests

from judex.scraping.ocr.base import ExtractResult, OCRConfig, ProviderSpec

DEFAULT_API_BASE = "https://api.mistral.ai"


def _concat_pages(pages: list[dict[str, Any]]) -> str:
    out: list[str] = []
    for p in pages or []:
        if not isinstance(p, dict):
            continue
        md = (p.get("markdown") or "").strip()
        if md:
            out.append(md)
    return "\n\n".join(out).strip()


def _upload(pdf_bytes: bytes, *, purpose: str, api_key: str, base: str, timeout: int,
            filename: str = "doc.pdf", mime: str = "application/pdf") -> str:
    r = requests.post(
        f"{base}/v1/files",
        headers={"Authorization": f"Bearer {api_key}"},
        files={"file": (filename, pdf_bytes, mime)},
        data={"purpose": purpose},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["id"]


def _signed_url(file_id: str, *, api_key: str, base: str, timeout: int) -> str:
    r = requests.get(
        f"{base}/v1/files/{file_id}/url",
        headers={"Authorization": f"Bearer {api_key}"},
        params={"expiry": 24},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["url"]


def _parse_ocr_response(payload: dict[str, Any]) -> ExtractResult:
    pages = payload.get("pages") or []
    return ExtractResult(
        text=_concat_pages(pages),
        elements=pages,
        pages_processed=(payload.get("usage_info") or {}).get("pages_processed"),
        provider="mistral",
    )


def extract(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
    base = config.api_url or DEFAULT_API_BASE
    file_id = _upload(
        pdf_bytes, purpose="ocr",
        api_key=config.api_key, base=base, timeout=config.timeout,
    )
    url = _signed_url(file_id, api_key=config.api_key, base=base, timeout=config.timeout)
    body = {
        "model": config.model,
        "document": {"type": "document_url", "document_url": url},
    }
    r = requests.post(
        f"{base}/v1/ocr",
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=config.timeout,
    )
    r.raise_for_status()
    return _parse_ocr_response(r.json() or {})


# ---------------------------------------------------------------------------
# Batch API — 50 % cost reduction, async (~24 h turnaround).
# ---------------------------------------------------------------------------


def build_batch_jsonl(items: Iterable[tuple[str, bytes]], *, model: str) -> str:
    """Render a list of (custom_id, pdf_bytes) into JSONL for /v1/batch/jobs.

    Each line is one OCR request, base64-inlined so the batch is
    self-contained (no separate file uploads required).
    """
    lines: list[str] = []
    for custom_id, pdf_bytes in items:
        b64 = base64.b64encode(pdf_bytes).decode("ascii")
        body = {
            "model": model,
            "document": {
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{b64}",
            },
        }
        lines.append(json.dumps({
            "custom_id": custom_id,
            "body": body,
        }, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


def submit_batch(jsonl_bytes: bytes, *, config: OCRConfig) -> str:
    """Upload JSONL + create batch job. Returns job_id."""
    base = config.api_url or DEFAULT_API_BASE
    input_file_id = _upload(
        jsonl_bytes, purpose="batch",
        api_key=config.api_key, base=base, timeout=config.timeout,
        filename="batch.jsonl", mime="application/jsonl",
    )
    r = requests.post(
        f"{base}/v1/batch/jobs",
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": config.model,
            "endpoint": "/v1/ocr",
            "input_files": [input_file_id],
        },
        timeout=config.timeout,
    )
    r.raise_for_status()
    return r.json()["id"]


def get_batch_status(job_id: str, *, config: OCRConfig) -> dict[str, Any]:
    base = config.api_url or DEFAULT_API_BASE
    r = requests.get(
        f"{base}/v1/batch/jobs/{job_id}",
        headers={"Authorization": f"Bearer {config.api_key}"},
        timeout=config.timeout,
    )
    r.raise_for_status()
    return r.json()


def download_batch_output(output_file_id: str, *, config: OCRConfig) -> Iterator[dict[str, Any]]:
    """Stream the result JSONL — yields {custom_id, response, error?} per line."""
    base = config.api_url or DEFAULT_API_BASE
    r = requests.get(
        f"{base}/v1/files/{output_file_id}/content",
        headers={"Authorization": f"Bearer {config.api_key}"},
        timeout=config.timeout,
        stream=True,
    )
    r.raise_for_status()
    for raw in r.iter_lines(decode_unicode=True):
        if not raw:
            continue
        yield json.loads(raw)


def parse_batch_results(rows: Iterable[dict[str, Any]]) -> dict[str, ExtractResult]:
    """Map result rows from `download_batch_output` to {custom_id: ExtractResult}.

    Failed rows (non-2xx batch entries) are dropped from the dict — the
    caller is expected to reconcile against the input custom_ids to see
    what's missing. Keeps this function pure and total.
    """
    out: dict[str, ExtractResult] = {}
    for row in rows:
        cid = row.get("custom_id")
        body = ((row.get("response") or {}).get("body")) or row.get("response") or {}
        if not isinstance(cid, str) or not isinstance(body, dict):
            continue
        if not body.get("pages"):
            continue
        out[cid] = _parse_ocr_response(body)
    return out


def wait_for_batch(
    job_id: str, *, config: OCRConfig,
    poll_interval: float = 30.0, max_wait: float = 86400.0,
) -> dict[str, Any]:
    """Block until the batch job reaches a terminal state. Returns final status dict."""
    deadline = time.monotonic() + max_wait
    while True:
        status = get_batch_status(job_id, config=config)
        s = (status.get("status") or "").upper()
        if s in {"SUCCESS", "FAILED", "CANCELLED", "TIMEOUT_EXCEEDED"}:
            return status
        if time.monotonic() > deadline:
            raise TimeoutError(f"Mistral batch {job_id} did not finish in {max_wait}s")
        time.sleep(poll_interval)


# ----- ProviderSpec ---------------------------------------------------------

# Mistral batch is submit-and-exit: the call blocks on the upload + job
# creation but then returns immediately. Actual fulfilment is Mistral's
# SLA (~24 h ceiling, usually much faster). The wall estimate for batch
# does NOT scale with n_pdfs.
_BATCH_SUBMIT_WALL_S = 30.0
_SYNC_WALL_PER_PDF_S = 3.5  # 2026-04-19 bakeoff anchor


def cost(n_pages: int, config: OCRConfig) -> float:
    if config.batch:
        return n_pages * 1.0 / 1000
    return n_pages * 2.0 / 1000


def wall(n_pdfs: int, config: OCRConfig) -> float:
    if config.batch:
        return _BATCH_SUBMIT_WALL_S
    return n_pdfs * _SYNC_WALL_PER_PDF_S


SPEC = ProviderSpec(
    name="mistral",
    extract=extract,
    cost=cost,
    wall=wall,
    env_var="MISTRAL_API_KEY",
    supports_batch=True,
)
