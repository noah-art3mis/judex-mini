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
from src.scraping.ocr import unstructured as _unstructured
from src.scraping.ocr.base import ExtractResult, OCRConfig


_REGISTRY: dict[str, Callable[..., ExtractResult]] = {
    "unstructured": _unstructured.extract,
    "mistral": _mistral.extract,
    "chandra": _chandra.extract,
}


# USD per page. Source notes:
# - unstructured: $10 / 1k on hi_res, $1 / 1k on fast (unstructured.io/pricing)
# - mistral: $2 / 1k sync, $1 / 1k batch (mistral.ai/news/mistral-ocr-3)
# - chandra: not publicly listed; community ~$3 / 1k (verify on dashboard)
PRICING: dict[tuple[str, str], float] = {
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
    if provider == "mistral":
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
