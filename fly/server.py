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
ThreadPoolExecutor sized to the Machine's vCPU count — that's where
the 2× speedup over Modal's sequential page-loop comes from.
"""

from __future__ import annotations

import io
import os
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


app = FastAPI(title="judex-tesseract-fly")


def _resolve_page_workers() -> int:
    # Fly Machines expose vCPU count via /proc/cpuinfo. Tesseract is
    # single-threaded per page, so worker count = vCPU is the right cap.
    # OMP_NUM_THREADS=1 inside _ocr_one_page prevents OpenMP from
    # multiplying threads underneath us.
    try:
        return max(1, os.cpu_count() or 1)
    except Exception:
        return 1


def _ocr_one_page(image) -> str:
    os.environ["OMP_NUM_THREADS"] = "1"
    import pytesseract
    return pytesseract.image_to_string(image, lang="por")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/extract")
async def extract(request: Request) -> JSONResponse:
    pdf_bytes = await request.body()
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="body must be PDF bytes")

    from pdf2image import convert_from_bytes
    from pypdf import PdfReader

    t0 = time.monotonic()
    n_pages = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    images = convert_from_bytes(pdf_bytes, dpi=200)

    n_workers = _resolve_page_workers()
    if n_workers == 1 or len(images) <= 1:
        page_texts = [_ocr_one_page(img) for img in images]
    else:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            page_texts = list(pool.map(_ocr_one_page, images))

    return JSONResponse({
        "text": "\n\n".join(t.strip() for t in page_texts if t and t.strip()),
        "n_pages": n_pages,
        "wall_seconds": round(time.monotonic() - t0, 3),
        "provider": "tesseract_fly",
    })
