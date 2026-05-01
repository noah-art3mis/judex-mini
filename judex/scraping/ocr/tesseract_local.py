"""Local Tesseract OCR provider — pytesseract + pdf2image, no network.

Sibling of ``judex/scraping/ocr/tesseract.py`` (the Modal-hosted version).
Same OCR engine, same Portuguese language pack — the only difference is
where the CPU cycles run. The Modal version is the production default
because sharded sweeps fan out to many containers; this local version
is for ad-hoc one-off extractions where parallelism doesn't matter and
network/auth simplicity does.

System dependencies (NOT pip-installable):

- ``tesseract`` binary + ``tesseract-ocr-por`` Portuguese language pack.
  Linux/WSL: ``apt install tesseract-ocr tesseract-ocr-por``.
  macOS: ``brew install tesseract tesseract-lang``.
- ``poppler-utils`` for ``pdf2image`` rasterization.
  Linux/WSL: ``apt install poppler-utils``. macOS: ``brew install poppler``.

Python dependencies are in the ``ocr-local`` extra:
``uv sync --extra ocr-local``.

Bakeoff anchors (2026-04-30, Modal CPU; single-PDF wall ≈ 3s).
Local single-threaded wall is comparable per-PDF; the win on Modal is
fan-out across containers, not per-PDF speed.
"""

from __future__ import annotations

from io import BytesIO

from judex.scraping.ocr.base import ExtractResult, OCRConfig, ProviderSpec


def extract(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
    # Lazy-imported so the provider registers without the optional deps
    # installed; only the call path requires them.
    import tempfile
    from pathlib import Path

    import pytesseract
    from pdf2image import convert_from_bytes
    from PIL import Image

    lang = "+".join(config.languages) if config.languages else "por"

    # Streaming rasterization: write pages to a temp dir, OCR one at a
    # time, discard each before loading the next. Keeps peak per-worker
    # memory at ~50 MB regardless of page count — the difference between
    # "3–4 workers on a 3.8 GiB box" and "CPU-bound at nproc workers."
    #
    # DPI matches the Modal `tesseract_extract` endpoint (200 DPI). The
    # 2026-04-30 bakeoff anchored 1.04% median CER at this resolution;
    # higher DPI hurts speed without measurable CER gain on STF legal
    # text. Keeping the same DPI means local output is byte-comparable
    # to the Modal version on matched inputs.
    pages_text: list[str] = []
    n_pages = 0
    with tempfile.TemporaryDirectory(prefix="judex_tesseract_") as tmp:
        paths = convert_from_bytes(
            pdf_bytes,
            dpi=200,
            output_folder=tmp,
            paths_only=True,
            fmt="png",
        )
        n_pages = len(paths)
        for path in paths:
            with Image.open(path) as img:
                page_text = pytesseract.image_to_string(img, lang=lang)
            if page_text and page_text.strip():
                pages_text.append(page_text.strip())
            Path(path).unlink(missing_ok=True)

    text = "\n\n".join(pages_text)
    return ExtractResult(
        text=text,
        elements=None,
        pages_processed=n_pages,
        provider="tesseract_local",
    )


def cost(n_pages: int, config: OCRConfig) -> float:
    # Local CPU — zero API cost.
    return 0.0


def wall(n_pdfs: int, config: OCRConfig) -> float:
    # ~3 s / PDF anchor from the 2026-04-30 Modal-CPU bakeoff;
    # single-threaded local wall is comparable. Multiply by n_pdfs for a
    # sequential estimate; divide by your worker count for a parallel
    # one (multiprocessing.Pool will scale near-linearly to n_cores).
    return n_pdfs * 3.0


SPEC = ProviderSpec(
    name="tesseract_local",
    extract=extract,
    cost=cost,
    wall=wall,
    env_var="",
    supports_batch=False,
)
