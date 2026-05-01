"""Tesseract OCR — local pytesseract + pdf2image, no network.

This is the default ``--provedor tesseract`` provider. It runs the same
Tesseract binary + Portuguese language pack as the Modal-hosted variant
(``judex/scraping/ocr/tesseract_modal.py``); the difference is *where*
the CPU cycles run. Use this for ad-hoc extractions and small sweeps
where the local host is enough; reach for ``--provedor tesseract_modal``
when sharded production sweeps need to fan out beyond what one host can
parallelise (Modal's containers + its ~10-shard concurrency cap).

System dependencies (NOT pip-installable):

- ``tesseract`` binary + ``tesseract-ocr-por`` Portuguese language pack.
  Linux/WSL: ``apt install tesseract-ocr tesseract-ocr-por``.
  macOS: ``brew install tesseract tesseract-lang``.
- ``poppler-utils`` for ``pdf2image`` rasterization.
  Linux/WSL: ``apt install poppler-utils``. macOS: ``brew install poppler``.

Python dependencies are in the ``ocr-local`` extra:
``uv sync --extra ocr-local``.

Hyperparameters (all on :class:`OCRConfig`):

- ``tesseract_dpi`` (default 200) — rasterization DPI. 200 is the
  bakeoff anchor (1.04% median CER on STF legal text, 2026-04-30).
  Higher hurts wall ~quadratically without measurable CER gain on
  born-digital PDFs that are already crisp at 200.
- ``tesseract_psm`` (default 3) — Tesseract page segmentation mode.
  3=auto, 4=single column variable size, 6=uniform block, 11=sparse.
- ``tesseract_oem`` (default 3) — engine mode. 1=LSTM only, 3=default.
- ``tesseract_workers`` (default ``None`` → auto) — number of parallel
  page-OCR processes. ``None`` resolves to
  ``len(os.sched_getaffinity(0))`` (cgroup-aware) capped at page count.
  Each pool worker runs Tesseract single-threaded (``OMP_NUM_THREADS=1``)
  to prevent the ``Pool(N) × OMP(N)`` thread-thrash trap.
"""

from __future__ import annotations

import os

from judex.scraping.ocr.base import ExtractResult, OCRConfig, ProviderSpec


_PER_WORKER_RAM_MB = 500  # tesseract LSTM + python child + rasterization headroom


def _ram_cap_workers() -> int:
    """Max workers the box's available RAM can support without swapping.

    Each tesseract subprocess loads the LSTM model (~150 MB) plus the
    Python pool-worker overhead. The 500 MB/worker bound also covers
    the rasterization-side page-cache pressure that a long ACÓRDÃO can
    generate (200 pages × ~9 MB PNG ≈ 1.8 GB of fresh-write cache,
    formally reclaimable but in practice pinned during the OCR pass).
    On a memory-constrained box (e.g. WSL2 capped at 4 GiB) the older
    250 MB number drove 9× slowdowns from page-cache thrashing on the
    HC ACÓRDÃO ladder; bumped 2026-05-01.
    """
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    return max(1, kb // (_PER_WORKER_RAM_MB * 1024))
    except (FileNotFoundError, ValueError, OSError):
        pass
    return 999  # unknown — let cpu_count be the binding cap


def _resolve_workers(requested: int | None, n_pages: int) -> int:
    """Pick a worker count that respects CPU, RAM, and page budget.

    ``None`` → ``min(cpu_affinity, ram_cap, n_pages)``. CPU comes from
    ``os.sched_getaffinity`` (cgroup-aware); RAM cap is computed from
    ``MemAvailable`` in ``/proc/meminfo``. An explicit positive
    ``requested`` is honored (still capped at page count) so the sweep
    can probe pathological values intentionally.
    """
    if requested is None:
        try:
            cpu_cap = len(os.sched_getaffinity(0))
        except AttributeError:
            cpu_cap = os.cpu_count() or 1
        available = min(cpu_cap, _ram_cap_workers())
    else:
        available = max(1, requested)
    return max(1, min(available, n_pages))


def _ocr_one_page(args: tuple[str, str, int, int]) -> str:
    """Worker: rasterize-cached PNG → text. Top-level for picklability."""
    path, lang, psm, oem = args
    # Force tesseract to stay single-threaded inside this worker;
    # the parallelism comes from Pool, not from OpenMP.
    os.environ["OMP_NUM_THREADS"] = "1"

    import pytesseract
    from PIL import Image

    config = f"--oem {oem} --psm {psm}"
    with Image.open(path) as img:
        return pytesseract.image_to_string(img, lang=lang, config=config)


def extract(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
    import tempfile
    from multiprocessing import Pool
    from pathlib import Path

    from pdf2image import convert_from_bytes

    lang = "+".join(config.languages) if config.languages else "por"
    dpi = config.tesseract_dpi
    psm = config.tesseract_psm
    oem = config.tesseract_oem

    # Streaming rasterization: write pages to a temp dir, OCR them via
    # a process pool, discard each before returning. Peak per-worker
    # memory stays at ~50 MB regardless of page count.
    pages_text: list[str] = []
    n_pages = 0
    with tempfile.TemporaryDirectory(prefix="judex_tesseract_") as tmp:
        # Rasterize first (poppler is fast and disk-bound). thread_count
        # matches the OCR pool size so both stages scale with the box.
        rast_threads = _resolve_workers(config.tesseract_workers, n_pages=999)
        paths = convert_from_bytes(
            pdf_bytes,
            dpi=dpi,
            output_folder=tmp,
            paths_only=True,
            fmt="png",
            thread_count=rast_threads,
        )
        n_pages = len(paths)
        if n_pages == 0:
            return ExtractResult(
                text="", elements=None, pages_processed=0,
                provider="tesseract",
            )

        n_workers = _resolve_workers(config.tesseract_workers, n_pages)
        worker_args = [(str(p), lang, psm, oem) for p in paths]

        if n_workers == 1:
            # Skip Pool overhead on single-page docs / explicit serial mode.
            pages_raw = [_ocr_one_page(a) for a in worker_args]
        else:
            with Pool(processes=n_workers) as pool:
                pages_raw = pool.map(_ocr_one_page, worker_args)

        for page_text in pages_raw:
            if page_text and page_text.strip():
                pages_text.append(page_text.strip())

        for p in paths:
            Path(p).unlink(missing_ok=True)

    text = "\n\n".join(pages_text)
    return ExtractResult(
        text=text,
        elements=None,
        pages_processed=n_pages,
        provider="tesseract",
    )


def cost(n_pages: int, config: OCRConfig) -> float:
    # Local CPU — zero API cost.
    return 0.0


def wall(n_pdfs: int, config: OCRConfig) -> float:
    # ~3 s / PDF anchor from the 2026-04-30 Modal-CPU bakeoff at the
    # default DPI/PSM/OEM and 4 cores. Local wall scales roughly with
    # (4 / n_workers) for multi-page docs; for single-page docs the
    # rasterization floor dominates and parallelism doesn't help.
    return n_pdfs * 3.0


SPEC = ProviderSpec(
    name="tesseract",
    extract=extract,
    cost=cost,
    wall=wall,
    env_var="",
    supports_batch=False,
)
