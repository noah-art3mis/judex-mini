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


_RASTER_CHUNK_PAGES = 4


@app.post("/extract")
async def extract(request: Request) -> JSONResponse:
    pdf_bytes = await request.body()
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="body must be PDF bytes")

    from pdf2image import convert_from_bytes
    from pypdf import PdfReader

    t0 = time.monotonic()
    n_pages = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    n_workers = _resolve_page_workers()

    # Chunked rasterization: render at most _RASTER_CHUNK_PAGES PIL Images
    # at a time, OCR them, drop them. Peak RAM is bounded by chunk size,
    # not by total page count, so a 200-page ACÓRDÃO uses the same memory
    # as a 4-page one. This is what allows [[vm]] memory = "2gb".
    page_texts: list[str] = []
    for chunk_start in range(1, n_pages + 1, _RASTER_CHUNK_PAGES):
        chunk_end = min(chunk_start + _RASTER_CHUNK_PAGES - 1, n_pages)
        chunk_imgs = convert_from_bytes(
            pdf_bytes, dpi=200,
            first_page=chunk_start, last_page=chunk_end,
        )
        if n_workers == 1 or len(chunk_imgs) <= 1:
            page_texts.extend(_ocr_one_page(img) for img in chunk_imgs)
        else:
            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                page_texts.extend(pool.map(_ocr_one_page, chunk_imgs))

    return JSONResponse({
        "text": "\n\n".join(t.strip() for t in page_texts if t and t.strip()),
        "n_pages": n_pages,
        "wall_seconds": round(time.monotonic() - t0, 3),
        "provider": "tesseract_fly",
    })
