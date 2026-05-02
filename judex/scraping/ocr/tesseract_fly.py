"""Tesseract OCR via self-hosted Fly.io HTTP service.

Sibling of ``judex/scraping/ocr/tesseract.py`` (local subprocess) and
``judex/scraping/ocr/tesseract_modal.py`` (Modal-hosted, .remote()
single-call). Same engine, same Portuguese language pack — the
difference is *where* the CPU cycles run and *how much* you pay.

Cost reference (Fly.io shared-cpu-2x / 4 GB / São Paulo, anchored
2026-05-01):

- Rate: $0.0118/hr per Machine = $0.00000328/sec active
- Anchored throughput: ~3 sec/PDF mean on cpu=2 (8-page ACÓRDÃO),
  matching the Modal CPU bakeoff anchor in ``tesseract.py``.
- Effective: ~$0.013 / 1k pages — ~10× cheaper than Modal Tesseract,
  ~50× cheaper than Datalab Chandra.

Auth + endpoint:

- Fly.io Machines are public-internet HTTPS by default; no API key
  required for the prototype. ``OCRConfig.api_url`` overrides the
  default URL; otherwise we read ``FLY_TESSERACT_URL`` from env.
- For a private deploy (auth-gated), set an ``Authorization: Bearer …``
  header by stashing the token in ``OCRConfig.api_key`` — handled
  uniformly with the other Bearer-token providers.

Service definition lives in ``fly/`` at the repo root::

    cd fly && flyctl deploy
    # then export FLY_TESSERACT_URL=https://<app>.fly.dev/extract

The service mirrors ``modal_app.py``'s ``tesseract_extract`` byte-
identically (same image, same DPI, same pytesseract call) so OCR
output is comparable across Modal and Fly variants without
re-bakeoffing.
"""

from __future__ import annotations

import os

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from judex.scraping.ocr.base import ExtractResult, OCRConfig, ProviderSpec


def _is_retryable_http(exc: BaseException) -> bool:
    """Retryable: 502/503/504 (Fly proxy can't reach a Machine — usually
    cold-start) and ReadTimeout / ConnectionError (Machine accepted but
    Tesseract OOM-restarted mid-OCR). 4xx (auth, malformed PDF) are
    permanent — fail fast.
    """
    if isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status in {502, 503, 504}
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    return False


_retry_fly = retry(
    retry=retry_if_exception(_is_retryable_http),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)


def _endpoint_url(config: OCRConfig) -> str:
    """Resolve the Fly.io endpoint URL.

    Order: explicit ``config.api_url`` wins; otherwise read from
    ``FLY_TESSERACT_URL`` env var. Raises ``RuntimeError`` if neither
    is set so misconfiguration fails loud rather than POSTing to a
    bogus URL.
    """
    if config.api_url:
        return config.api_url
    url = os.environ.get("FLY_TESSERACT_URL")
    if not url:
        raise RuntimeError(
            "tesseract_fly: set FLY_TESSERACT_URL env var or pass "
            "api_url explicitly via OCRConfig"
        )
    return url


@_retry_fly
def _post_extract(url: str, *, headers: dict, pdf_bytes: bytes, timeout: int) -> dict:
    r = requests.post(url, data=pdf_bytes, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json() or {}


def extract(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
    headers = {"Content-Type": "application/pdf"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    payload = _post_extract(
        _endpoint_url(config),
        headers=headers,
        pdf_bytes=pdf_bytes,
        timeout=config.timeout,
    )
    return ExtractResult(
        text=(payload.get("text") or "").strip(),
        elements=None,
        pages_processed=payload.get("n_pages"),
        provider="tesseract_fly",
    )


# ----- ProviderSpec ---------------------------------------------------------


def cost(n_pages: int, config: OCRConfig) -> float:
    # shared-cpu-2x / 4 GB at $0.0118/hr × ~3 sec/PDF / 8 pages-per-PDF
    # ≈ $0.013 per 1k pages. Re-anchor against the next Fly bakeoff or
    # if Fly.io's published rates change.
    return n_pages * 0.013 / 1000


def wall(n_pdfs: int, config: OCRConfig) -> float:
    # ~3 s/PDF anchor inherited from the Modal CPU bakeoff (same
    # engine, comparable shape). Refresh from the first Fly-side
    # bakeoff once available.
    return n_pdfs * 3.0


SPEC = ProviderSpec(
    name="tesseract_fly",
    extract=extract,
    cost=cost,
    wall=wall,
    env_var="",  # no API key required by default; FLY_TESSERACT_URL is the addr
    supports_batch=False,
)
