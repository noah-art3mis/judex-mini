"""Chandra OCR via Datalab's ``chandra_vllm`` image on RunPod Serverless.

Sibling of ``judex/scraping/ocr/chandra.py`` (the Datalab hosted-API
variant). Same engine, same Portuguese-language quality — different
*deployment*. Where the hosted variant POSTs to Datalab's own HTTPS
endpoint and pays Datalab's per-page rate, this variant talks to a
self-deployed RunPod Serverless endpoint running RunPod's
``worker-vllm`` template serving Datalab's open-source Chandra v2.

Cost reference (Chandra v2 self-hosted on RunPod 4090 Serverless,
cf. cost analysis 2026-05-01):

- Rate: $0.00031/sec active = $1.12/hr active (RunPod 4090 Flex tier)
- Throughput: ~1 page/sec on RTX 4090 → ~$0.31 per 1k pages
- Roughly 10× cheaper than the Datalab hosted API ($3/1k pages) at
  bulk-batch scale.

Transport: **the async ``/run`` + ``/status`` path**, not the
OpenAI-compatible proxy. The proxy at ``/v2/{ep}/openai/v1/...``
returns HTTP 500 on the worker-vllm image we're deployed on
(2026-05-01 endpoint observation; the OpenAI compat layer was not
functional). The ``/run`` path works and returns RunPod's own
worker-vllm envelope, which we parse manually:

- Submit: ``POST /v2/{ep}/run`` with ``{"input": {"messages": [...],
  "max_tokens": ..., "temperature": ...}}`` → ``{"id": ..., "status":
  "IN_QUEUE"}``
- Poll:   ``GET /v2/{ep}/status/{job_id}`` until ``status`` is one of
  COMPLETED / FAILED / CANCELLED / TIMED_OUT
- Output: ``output[*].choices[*].tokens`` — list of token strings
  flattened and joined to produce the assistant's text

PDF → PIL rasterisation happens client-side via ``pdf2image`` (one
PNG per page, 200 DPI), then each page is base64-image-url'd into a
multimodal message and submitted as one ``/run`` job. Per-page
sequential within a single PDF; cross-PDF parallelism comes from
RunPod's worker pool size.

Auth + endpoint lookup:

- ``OCRConfig.api_key`` carries ``RUNPOD_API_KEY`` (Bearer token)
- ``OCRConfig.api_url``, when set, overrides the constructed base URL
- otherwise the base is built from ``RUNPOD_CHANDRA_ENDPOINT_ID``
  in the environment

License (verified 2026-05-01):

- Code: Apache 2.0 (datalab-to/chandra repo)
- Weights: modified OpenRAIL-M — free for research / personal use /
  startups under $2M revenue. STF research usage falls inside the
  free tier; verify against your context before commercial use.

Required RunPod endpoint configuration (one-time, on the console):

- Container image: ``runpod/worker-vllm`` (or equivalent)
- Env: ``MODEL_NAME=datalab-to/chandra-ocr-2``
- Env: ``HF_TOKEN=<your hf token>``  (Chandra weights need HF auth)
- Env: ``MAX_MODEL_LEN=16384``  (overrides Chandra's 262144 default;
  the unrestricted default tries to reserve ~33 GB of KV cache,
  which OOMs any 24 GB GPU during model load)
- Env: ``ENABLE_CHUNKED_PREFILL=true``  (defensive; the worker-vllm
  template otherwise sometimes disables it, which Chandra's config
  warns may crash the engine)
- GPU: 24 GB tier (4090 / 3090). 16 GB is too tight; 40+ GB wastes
  money for a 5B-param model
- Max Workers: 5 for production batch, 2 for debug (1 traps you with
  no replacement when a worker hangs)
- Idle Timeout: 60 s
"""

from __future__ import annotations

import base64
import io
import os
import time
from typing import Any

import requests

from judex.scraping.ocr.base import ExtractResult, OCRConfig, ProviderSpec


DEFAULT_PROMPT = (
    "Extract all text from this document image. Preserve layout, "
    "tables, and headings using Markdown. Output only the extracted "
    "content with no commentary."
)

_TERMINAL_OK = {"COMPLETED"}
_TERMINAL_FAIL = {"FAILED", "CANCELLED", "TIMED_OUT"}


def _endpoint_base(config: OCRConfig) -> str:
    """Resolve the RunPod Serverless endpoint base URL.

    Order: explicit ``config.api_url`` wins; otherwise construct from
    ``RUNPOD_CHANDRA_ENDPOINT_ID``. Raises ``RuntimeError`` if neither
    is set so misconfiguration fails loud rather than POSTing to a
    bogus URL.
    """
    if config.api_url:
        return config.api_url.rstrip("/")
    endpoint_id = os.environ.get("RUNPOD_CHANDRA_ENDPOINT_ID")
    if not endpoint_id:
        raise RuntimeError(
            "chandra_runpod: set RUNPOD_CHANDRA_ENDPOINT_ID env var "
            "or pass api_url explicitly via OCRConfig"
        )
    return f"https://api.runpod.ai/v2/{endpoint_id}"


def _pdf_to_page_pngs(pdf_bytes: bytes, *, dpi: int = 200) -> list[bytes]:
    """Rasterise a PDF into PNG bytes, one entry per page.

    ``pdf2image`` is imported lazily so the host doesn't need
    poppler-utils unless this provider is actually used.
    """
    try:
        from pdf2image import convert_from_bytes
    except ImportError as exc:
        raise RuntimeError(
            "chandra_runpod requires pdf2image+pillow+poppler-utils for "
            "client-side PDF rasterisation. Install with `uv sync --extra "
            "ocr-local` and ensure poppler-utils is on the system path."
        ) from exc

    images = convert_from_bytes(pdf_bytes, dpi=dpi)
    out: list[bytes] = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out.append(buf.getvalue())
    return out


def submit(page_png: bytes, *, config: OCRConfig, base: str) -> str:
    """Submit one page's image to /run, return RunPod job_id."""
    b64 = base64.b64encode(page_png).decode("ascii")
    r = requests.post(
        f"{base}/run",
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        json={
            "input": {
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        {"type": "text", "text": DEFAULT_PROMPT},
                    ],
                }],
                "max_tokens": 4096,
                "temperature": 0.0,
            },
        },
        timeout=config.timeout,
    )
    r.raise_for_status()
    payload = r.json() or {}
    job_id = payload.get("id")
    if not job_id:
        raise RuntimeError(f"chandra_runpod: no job id in submit response: {payload}")
    return job_id


def poll(job_id: str, *, config: OCRConfig, base: str) -> str:
    """Block until the job hits a terminal status; return assistant text.

    Honours ``config.poll_interval`` and ``config.poll_max_wait``.
    Raises ``RuntimeError`` on FAILED / CANCELLED / TIMED_OUT and
    ``TimeoutError`` if the local poll deadline expires.
    """
    deadline = time.monotonic() + config.poll_max_wait
    while True:
        r = requests.get(
            f"{base}/status/{job_id}",
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=config.timeout,
        )
        r.raise_for_status()
        payload = r.json() or {}
        status = (payload.get("status") or "").upper()
        if status in _TERMINAL_OK:
            return _extract_text(payload.get("output"))
        if status in _TERMINAL_FAIL:
            raise RuntimeError(
                f"chandra_runpod: job {job_id} ended {status}: {payload}"
            )
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"chandra_runpod: job {job_id} did not complete in "
                f"{config.poll_max_wait}s (last status: {status})"
            )
        time.sleep(config.poll_interval)


def _extract_text(output: Any) -> str:
    """Flatten ``output[*].choices[*].tokens[*]`` into one string.

    RunPod worker-vllm returns ``output`` as a list of chunks; each
    chunk has its own ``choices[].tokens[]``. Streaming or chunked
    long generations produce >1 chunk; short ones produce 1.
    """
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for chunk in output:
        if not isinstance(chunk, dict):
            continue
        for choice in chunk.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            for tok in choice.get("tokens") or []:
                if isinstance(tok, str):
                    parts.append(tok)
    return "".join(parts).strip()


def extract(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
    base = _endpoint_base(config)
    pages = _pdf_to_page_pngs(pdf_bytes)
    page_texts: list[str] = []
    for page in pages:
        job_id = submit(page, config=config, base=base)
        page_texts.append(poll(job_id, config=config, base=base))
    text = "\n\n".join(t for t in page_texts if t).strip()
    return ExtractResult(
        text=text,
        elements=None,
        pages_processed=len(pages),
        provider="chandra_runpod",
    )


# ----- ProviderSpec ---------------------------------------------------------


def cost(n_pages: int, config: OCRConfig) -> float:
    # RunPod 4090 Serverless Flex: $0.00031/sec active, sustained
    # ~1 page/sec on Chandra v2 → effective $0.31 / 1k pages.
    return n_pages * 0.31 / 1000


def wall(n_pdfs: int, config: OCRConfig) -> float:
    raise NotImplementedError(
        "chandra_runpod wall anchor pending; refresh from the next OCR bakeoff"
    )


SPEC = ProviderSpec(
    name="chandra_runpod",
    extract=extract,
    cost=cost,
    wall=wall,
    env_var="RUNPOD_API_KEY",
    supports_batch=False,
)
