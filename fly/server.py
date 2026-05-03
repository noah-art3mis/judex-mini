"""Tesseract OCR HTTP service.

Mirrors `judex.scraping.ocr.modal_app.tesseract_extract` — same
engine, same DPI, same Portuguese language pack — but wrapped as a
FastAPI endpoint so Fly.io Machines can autoscale on request load.

POST /extract  (body: raw PDF bytes)
GET  /healthz

The server is single-process (uvicorn --workers 1) on purpose: each
Fly Machine handles one PDF at a time, and concurrency comes from
spawning more Machines via Fly's auto_start_machines, not from
in-process threading. Pages within one PDF *are* parallelised via a
module-scoped ThreadPoolExecutor sized to the Machine's vCPU count.

OCR uses tesserocr (Cython bindings to libtesseract) instead of
pytesseract (subprocess wrapper). The win is that each worker thread
holds a long-lived `PyTessBaseAPI` instance — the LSTM language model
is loaded once per worker at server startup, then reused for every
page across every request, instead of re-loaded by a fresh tesseract
subprocess per page (the pytesseract pattern). Tesserocr releases the
GIL during recognition, so threading still gives real parallelism.
"""

from __future__ import annotations

import asyncio
import io
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

# Imported here at module load — must run on the main thread because
# tesserocr's first import calls cysignals.init_cysignals(), which
# registers SIGINT/SIGTERM handlers via signal.signal() (main-thread-only
# in CPython). Lazy-importing inside _get_api (which runs on worker
# threads) raises "signal only works in main thread of the main
# interpreter" and aborts the request.
from tesserocr import PyTessBaseAPI


app = FastAPI(title="judex-tesseract-fly")


def _resolve_page_workers() -> int:
    # Prefer cgroup v2 cpu.max (the actual quota Fly enforces) over
    # os.cpu_count() (which can leak host vCPUs through Firecracker on
    # some shapes). Falls back to cpu_count for non-cgroup environments
    # (local docker-run, macOS dev). Tesseract is effectively
    # single-threaded per page, so worker count = vCPU is the right cap;
    # OMP_NUM_THREADS=1 (set in fly.toml [env]) prevents OpenMP from
    # multiplying threads underneath us.
    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            quota_str, period_str = f.read().split()
        if quota_str != "max":
            return max(1, int(int(quota_str) / int(period_str)))
    except (OSError, ValueError):
        pass
    return max(1, os.cpu_count() or 1)


_N_WORKERS = _resolve_page_workers()
_OCR_LANG = "por"

# Per-thread tesseract API. PyTessBaseAPI is not safe for concurrent
# use across threads (it holds recognition state), so each worker
# thread gets its own lazily-initialised instance. The first OCR call
# on a thread pays the model-load cost (~150 ms for por.traineddata);
# every subsequent call on that thread reuses the loaded model.
# With a persistent module-scoped pool of N_WORKERS threads, the model
# is loaded N_WORKERS times for the entire server lifetime.
_thread_local = threading.local()


def _get_api():
    api = getattr(_thread_local, "api", None)
    if api is None:
        api = PyTessBaseAPI(lang=_OCR_LANG)
        _thread_local.api = api
    return api


def _ocr_one_page(image) -> str:
    api = _get_api()
    api.SetImage(image)
    return api.GetUTF8Text()


# Persistent OCR pool. Module-scoped so worker threads (and their
# thread-local PyTessBaseAPI instances) survive across requests —
# initialising a fresh pool per chunk would re-pay the LSTM-load cost
# for every PDF, defeating the whole point of switching off pytesseract.
_OCR_POOL = ThreadPoolExecutor(
    max_workers=_N_WORKERS, thread_name_prefix="ocr"
)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


# Chunk size trades pdftoppm subprocess overhead vs peak RAM. Each
# call re-parses the full PDF index, so big chunks amortize the parse
# cost; small chunks bound peak memory uniformly across page counts.
#
# At 16 pages: peak raster = 16 × 11 MB = 176 MB. Combined with steady
# ~510 MB (Python/uvicorn + tesserocr API instances holding LSTM model
# resident per worker thread) → ~686 MB peak working set, fits in the
# 1 GB shape with ~33% headroom. Headroom went up vs the pytesseract
# era because tesseract subprocesses no longer transiently allocate
# ~100 MB each — the model lives once-per-worker in our process heap
# instead of being re-mmap'd by N transient subprocesses.
_RASTER_CHUNK_PAGES = 16


def _ocr_pdf_sync(pdf_bytes: bytes) -> dict:
    """Synchronous OCR pipeline. Runs in a thread (via run_in_executor) so
    the asyncio event loop stays free to serve /healthz during OCR — Fly's
    health watchdog kills Machines that fail health checks for ~6 min,
    which on the prior async-blocking version meant any 295+-page PDF
    request died mid-OCR (empirically confirmed 2026-05-02).
    """
    from pdf2image import convert_from_bytes
    from pypdf import PdfReader

    t0 = time.monotonic()
    n_pages = len(PdfReader(io.BytesIO(pdf_bytes)).pages)

    # Chunked rasterization: render at most _RASTER_CHUNK_PAGES PIL Images
    # at a time, OCR them, drop them. Peak RAM is bounded by chunk size,
    # not by total page count, so a 150-page non-outlier PDF uses the
    # same memory as a 4-page one. This is what allows [[vm]] memory = "1gb".
    page_texts: list[str] = []
    for chunk_start in range(1, n_pages + 1, _RASTER_CHUNK_PAGES):
        chunk_end = min(chunk_start + _RASTER_CHUNK_PAGES - 1, n_pages)
        chunk_imgs = convert_from_bytes(
            pdf_bytes, dpi=200,
            first_page=chunk_start, last_page=chunk_end,
        )
        if _N_WORKERS == 1 or len(chunk_imgs) <= 1:
            page_texts.extend(_ocr_one_page(img) for img in chunk_imgs)
        else:
            page_texts.extend(_OCR_POOL.map(_ocr_one_page, chunk_imgs))

    return {
        "text": "\n\n".join(t.strip() for t in page_texts if t and t.strip()),
        "n_pages": n_pages,
        "wall_seconds": round(time.monotonic() - t0, 3),
        "provider": "tesseract_fly",
    }


@app.post("/extract")
async def extract(request: Request) -> JSONResponse:
    pdf_bytes = await request.body()
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="body must be PDF bytes")

    loop = asyncio.get_running_loop()
    payload = await loop.run_in_executor(None, _ocr_pdf_sync, pdf_bytes)
    return JSONResponse(payload)
