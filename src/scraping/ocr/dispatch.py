"""Provider registry + cost estimator.

`extract_pdf(pdf_bytes, config)` is the single entry point — looks up
`config.provider` in the registry and forwards the call. Adding a new
provider means: implement `extract(pdf_bytes, *, config) -> ExtractResult`
and register it here.

`estimate_cost(provider, n_pages, *, batch=False)` returns USD assuming
April-2026 list prices (see PRICING dict). Use for dry-run gates before
launching a bulk sweep.
"""

from __future__ import annotations

from typing import Callable

from src.scraping.ocr import chandra as _chandra
from src.scraping.ocr import mistral as _mistral
from src.scraping.ocr import pypdf as _pypdf
from src.scraping.ocr import unstructured as _unstructured
from src.scraping.ocr.base import ExtractResult, OCRConfig


_REGISTRY: dict[str, Callable[..., ExtractResult]] = {
    "pypdf": _pypdf.extract,
    "unstructured": _unstructured.extract,
    "mistral": _mistral.extract,
    "chandra": _chandra.extract,
}


# USD per page. Source notes:
# - pypdf: local text-layer parse; zero API cost. Listed so
#   estimate_cost treats "pypdf" uniformly instead of special-casing
#   the default provider at the call site.
# - unstructured: $10 / 1k on hi_res, $1 / 1k on fast (unstructured.io/pricing)
# - mistral: $2 / 1k sync, $1 / 1k batch (mistral.ai/news/mistral-ocr-3)
# - chandra: not publicly listed; community ~$3 / 1k (verify on dashboard)
PRICING: dict[tuple[str, str], float] = {
    ("pypdf", "local"): 0.0,
    ("unstructured", "hi_res"): 10.0 / 1000,
    ("unstructured", "ocr_only"): 10.0 / 1000,
    ("unstructured", "fast"): 1.0 / 1000,
    ("unstructured", "auto"): 10.0 / 1000,  # conservative
    ("mistral", "sync"): 2.0 / 1000,
    ("mistral", "batch"): 1.0 / 1000,
    ("chandra", "accurate"): 3.0 / 1000,
    ("chandra", "balanced"): 3.0 / 1000,
    ("chandra", "fast"): 3.0 / 1000,
}


def extract_pdf(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
    if config.provider not in _REGISTRY:
        raise ValueError(
            f"unknown OCR provider {config.provider!r}; "
            f"known: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[config.provider](pdf_bytes, config=config)


def estimate_cost(
    provider: str, n_pages: int, *,
    strategy: str = "hi_res", mode: str = "accurate", batch: bool = False,
) -> float:
    """USD for `n_pages` on the given provider/tier."""
    if provider == "pypdf":
        key = ("pypdf", "local")
    elif provider == "mistral":
        key = ("mistral", "batch" if batch else "sync")
    elif provider == "unstructured":
        key = ("unstructured", strategy)
    elif provider == "chandra":
        key = ("chandra", mode)
    else:
        raise ValueError(f"unknown OCR provider {provider!r}")
    if key not in PRICING:
        raise ValueError(f"no price for ({provider}, {key[1]})")
    return PRICING[key] * n_pages


# Per-PDF wall anchors (sync, seconds). Measured on the 2026-04-19
# bakeoff (5-PDF canary, runs/active/2026-04-19-ocr-bakeoff/). These
# drive the `extrair-pdfs` preview ETA; re-anchor when a new bakeoff
# lands.
_WALL_PER_PDF: dict[str, float] = {
    "pypdf": 0.1,
    "mistral": 3.5,
    "chandra": 15.0,
    "unstructured": 25.0,
}

# Mistral batch is submit-and-exit: the call blocks on the upload +
# job creation but then returns immediately. Actual fulfilment is
# Mistral's SLA (~24 h ceiling, usually much faster). The preview
# reports this as "submit now, collect with coletar-lote later" and
# should NOT multiply by n_pdfs.
_BATCH_SUBMIT_WALL_S = 30.0


def estimate_wall(provider: str, n_pdfs: int, *, batch: bool = False) -> float:
    """Wall-seconds estimate for a sweep of `n_pdfs` through `provider`.

    Raises KeyError for unknown providers — callers should validate
    the provider against `_REGISTRY` before calling (same guard as
    `extract_pdf`).
    """
    if batch and provider == "mistral":
        return _BATCH_SUBMIT_WALL_S
    return n_pdfs * _WALL_PER_PDF[provider]


def cheapest_provider(*, batch_ok: bool = True) -> str:
    """Return the provider name with the lowest list price.

    Pure helper for `--provider auto` style flags. Doesn't account for
    quality, latency, or feature differences.
    """
    candidates = [
        ("mistral", PRICING[("mistral", "batch" if batch_ok else "sync")]),
        ("chandra", PRICING[("chandra", "accurate")]),
        ("unstructured", PRICING[("unstructured", "fast")]),
    ]
    return min(candidates, key=lambda x: x[1])[0]
