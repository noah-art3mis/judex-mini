"""Modal app exposing self-hosted OCR endpoints for the bakeoff.

Three endpoints, three GPU classes, one app:

- ``surya_extract`` (L40S, surya-ocr) — pipeline OCR
- ``paddle_extract`` (A10, paddleocr + paddlepaddle-gpu) — pipeline OCR
- ``tesseract_extract`` (CPU, tesseract-ocr-por) — classic OCR floor

Each accepts raw PDF bytes and returns ``{text, n_pages, wall_seconds}``.
The thin client providers in ``surya.py`` / ``paddle.py`` / ``tesseract.py``
look these up via ``modal.Function.from_name`` and call ``.remote()``.

Deploy with:

    uv run modal deploy judex/scraping/ocr/modal_app.py

Smoke-test with:

    uv run modal run judex/scraping/ocr/modal_app.py::test_endpoints

Pricing reference (Modal published rates, fetched 2026-04-30):
  CPU             $0.0000131 / physical core / sec
  RAM             $0.00000222 / GiB / sec
  A10             $0.000306 / sec  ($1.10/h)
  L40S            $0.000542 / sec  ($1.95/h)
"""

from __future__ import annotations

import io
import time

import modal


APP_NAME = "judex-ocr-bakeoff"

app = modal.App(APP_NAME)


# ---------------------------------------------------------------------------
# Tesseract — CPU only, classic OCR. Quality floor reference.
# ---------------------------------------------------------------------------

tesseract_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("tesseract-ocr", "tesseract-ocr-por", "poppler-utils")
    .pip_install("pytesseract==0.3.13", "pdf2image==1.17.0", "pypdf==4.3.1")
)


@app.function(
    image=tesseract_image,
    cpu=4.0,
    memory=8192,
    timeout=600,
)
def tesseract_extract(pdf_bytes: bytes) -> dict:
    """Tesseract via pytesseract on rasterized PDF pages."""
    import pytesseract
    from pdf2image import convert_from_bytes
    from pypdf import PdfReader

    t0 = time.monotonic()
    n_pages = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    # 200 DPI is the sweet spot — higher hurts speed without much CER gain
    # on legal text (most STF PDFs are not high-DPI to begin with).
    images = convert_from_bytes(pdf_bytes, dpi=200)
    page_texts: list[str] = []
    for img in images:
        page_texts.append(pytesseract.image_to_string(img, lang="por"))
    return {
        "text": "\n\n".join(page_texts).strip(),
        "n_pages": n_pages,
        "wall_seconds": time.monotonic() - t0,
        "provider": "tesseract",
    }


# ---------------------------------------------------------------------------
# Surya — L40S, pipeline OCR (detection + recognition + layout).
# ---------------------------------------------------------------------------

surya_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("poppler-utils")
    .pip_install(
        # Pinned to last 0.16.x — 0.17 has a self-inconsistency bug where
        # SuryaDecoderModel reads config.pad_token_id but SuryaDecoderConfig
        # doesn't define it. Reproduces with transformers 4.57.6 too, so
        # it's a Surya bug not a transformers compat issue.
        "surya-ocr==0.16.7",
        "pdf2image==1.17.0",
        "pypdf==4.3.1",
        "requests>=2.31",
        "huggingface-hub>=0.20",
        # surya 0.16.7 requires transformers>=4.56.1 but breaks on 4.57+
        # (SuryaDecoderConfig.pad_token_id KeyError). Pin to the exact
        # minimum allowed version — that's the only one in the surya/
        # transformers compatibility window.
        "transformers==4.56.1",
    )
    # Skip build-time weight prepull — let the first call download.
    # The function uses scaledown_window=30 so successive calls in a
    # bakeoff hit the warm container.
)


@app.function(
    image=surya_image,
    gpu="L40S",
    timeout=900,
    # Short scaledown — minimize warm-idle billing. Successive calls
    # within 30s of each other still hit the warm container; longer gaps
    # cold-start (~30s model load).
    scaledown_window=30,
)
def surya_extract(pdf_bytes: bytes) -> dict:
    """Surya OCR pipeline (detect + recognize) — Surya 0.16.7 API."""
    from pdf2image import convert_from_bytes
    from pypdf import PdfReader
    from surya.detection import DetectionPredictor
    from surya.foundation import FoundationPredictor
    from surya.recognition import RecognitionPredictor

    t0 = time.monotonic()
    n_pages = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    images = convert_from_bytes(pdf_bytes, dpi=200)

    foundation = FoundationPredictor()
    rec = RecognitionPredictor(foundation)
    det = DetectionPredictor()

    predictions = rec(images, det_predictor=det)

    page_texts: list[str] = []
    for pred in predictions:
        lines = [line.text for line in (pred.text_lines or []) if line.text]
        page_texts.append("\n".join(lines))

    return {
        "text": "\n\n".join(page_texts).strip(),
        "n_pages": n_pages,
        "wall_seconds": time.monotonic() - t0,
        "provider": "surya",
    }


# ---------------------------------------------------------------------------
# PaddleOCR — A10, PP-OCRv5. Apache 2.0, multilingual (Latin includes pt).
# ---------------------------------------------------------------------------

paddle_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("poppler-utils", "libgl1", "libglib2.0-0")
    .pip_install(
        "paddlepaddle-gpu==3.0.0",
        "paddleocr==2.10.0",
        "pdf2image==1.17.0",
        "pypdf==4.3.1",
        "requests>=2.31",
        extra_index_url="https://www.paddlepaddle.org.cn/packages/stable/cu118/",
    )
    # Skip build-time weight prepull — first call downloads; warm
    # container amortizes for successive calls.
)


@app.function(
    image=paddle_image,
    gpu="A10",
    timeout=900,
    scaledown_window=30,
)
def paddle_extract(pdf_bytes: bytes) -> dict:
    """PaddleOCR PP-OCRv4 latin (covers pt) on rasterized pages."""
    import numpy as np
    from paddleocr import PaddleOCR
    from pdf2image import convert_from_bytes
    from pypdf import PdfReader

    t0 = time.monotonic()
    n_pages = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    images = convert_from_bytes(pdf_bytes, dpi=200)

    ocr = PaddleOCR(use_angle_cls=True, lang="latin", show_log=False)

    page_texts: list[str] = []
    for img in images:
        # PaddleOCR.ocr expects numpy arrays (BGR). PIL gives RGB → flip.
        arr = np.array(img)[..., ::-1]
        result = ocr.ocr(arr, cls=True)
        # result shape: [[[box, (text, conf)], ...]] — one outer list per
        # input image (single image here → first element).
        lines: list[str] = []
        for line in (result[0] or []):
            try:
                text = line[1][0]
            except (IndexError, TypeError):
                continue
            if text:
                lines.append(text)
        page_texts.append("\n".join(lines))

    return {
        "text": "\n\n".join(page_texts).strip(),
        "n_pages": n_pages,
        "wall_seconds": time.monotonic() - t0,
        "provider": "paddle",
    }


# ---------------------------------------------------------------------------
# Smoke test entrypoint — runs each endpoint on a tiny in-memory PDF.
# ---------------------------------------------------------------------------


@app.local_entrypoint()
def test_endpoints():
    """Tiny end-to-end test on a 1-page generated PDF."""
    from pypdf import PdfWriter
    from io import BytesIO

    # Build a minimal 1-page PDF (no rendered text, just structure).
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    print("== tesseract ==")
    r = tesseract_extract.remote(pdf_bytes)
    print(f"  n_pages={r['n_pages']} wall={r['wall_seconds']:.1f}s text_len={len(r['text'])}")

    print("== surya ==")
    r = surya_extract.remote(pdf_bytes)
    print(f"  n_pages={r['n_pages']} wall={r['wall_seconds']:.1f}s text_len={len(r['text'])}")

    print("== paddle ==")
    r = paddle_extract.remote(pdf_bytes)
    print(f"  n_pages={r['n_pages']} wall={r['wall_seconds']:.1f}s text_len={len(r['text'])}")
