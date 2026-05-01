"""Provider registry + thin metadata facade.

Each provider module exposes a ``SPEC: ProviderSpec`` constant that
self-describes its ``extract`` callable, ``cost`` function, ``wall``
function, env-var name, and batch support. This module imports each
provider, builds a name → spec registry, and surfaces three thin
facades for the rest of the codebase:

- ``extract_pdf(pdf_bytes, config)`` — single dispatch entry point;
  forwards to ``REGISTRY[config.provider].extract``.
- ``estimate_cost(provider, n_pages, **opts)`` — backwards-compat
  wrapper that builds an :class:`OCRConfig` from kwargs and delegates
  to the provider's ``cost`` method. Prefer ``get_provider(name).cost``
  for new call sites.
- ``estimate_wall(provider, n_pdfs, **opts)`` — same shape for wall
  anchors. Some providers (Modal-hosted) raise ``NotImplementedError``
  until their first bakeoff anchors a real number.

Adding a new provider means: implement ``extract``/``cost``/``wall``
plus a ``SPEC`` in ``judex/scraping/ocr/<provider>.py``; add one line
to the ``_PROVIDERS`` list below. The previous central ``PRICING`` dict
+ ``estimate_cost`` if/elif chain are gone — pricing now lives with
the provider that owns it.
"""

from __future__ import annotations

from judex.scraping.ocr import chandra as _chandra
from judex.scraping.ocr import gemini as _gemini
from judex.scraping.ocr import mistral as _mistral
from judex.scraping.ocr import paddle as _paddle
from judex.scraping.ocr import pypdf as _pypdf
from judex.scraping.ocr import surya as _surya
from judex.scraping.ocr import tesseract as _tesseract
from judex.scraping.ocr import unstructured as _unstructured
from judex.scraping.ocr.base import ExtractResult, OCRConfig, ProviderSpec


_PROVIDERS: list[ProviderSpec] = [
    _pypdf.SPEC,
    _unstructured.SPEC,
    _mistral.SPEC,
    _chandra.SPEC,
    _gemini.SPEC,
    _surya.SPEC,
    _paddle.SPEC,
    _tesseract.SPEC,
]


REGISTRY: dict[str, ProviderSpec] = {p.name: p for p in _PROVIDERS}


def get_provider(name: str) -> ProviderSpec:
    """Look up a provider's spec by name. Raises ``ValueError`` on miss."""
    if name not in REGISTRY:
        raise ValueError(
            f"unknown OCR provider {name!r}; known: {sorted(REGISTRY)}"
        )
    return REGISTRY[name]


def extract_pdf(pdf_bytes: bytes, config: OCRConfig) -> ExtractResult:
    return get_provider(config.provider).extract(pdf_bytes, config=config)


def estimate_cost(
    provider: str,
    n_pages: int,
    *,
    strategy: str = "hi_res",
    mode: str = "accurate",
    batch: bool = False,
) -> float:
    """USD for ``n_pages`` on the given provider/tier.

    Backwards-compat shape: builds an :class:`OCRConfig` from the kwargs
    and delegates to the provider's ``cost`` method. Each provider reads
    only the config fields its pricing model cares about.
    """
    spec = get_provider(provider)
    config = OCRConfig(
        provider=provider, strategy=strategy, mode=mode, batch=batch,
    )
    return spec.cost(n_pages, config)


def estimate_wall(
    provider: str,
    n_pdfs: int,
    *,
    batch: bool = False,
) -> float:
    """Wall-seconds estimate for a sweep of ``n_pdfs`` through ``provider``.

    Raises ``ValueError`` for unknown providers (consistent with
    ``estimate_cost``); raises ``NotImplementedError`` for providers
    whose wall anchor has not been measured yet (Modal-hosted providers
    awaiting their first bakeoff).
    """
    spec = get_provider(provider)
    config = OCRConfig(provider=provider, batch=batch)
    return spec.wall(n_pdfs, config)


def cheapest_provider(*, batch_ok: bool = True) -> str:
    """Return the cheapest provider's name across the full registry.

    Compares per-page cost at the spec's preferred config (batch when
    ``batch_ok`` and the provider supports it; sync otherwise). Excludes
    ``pypdf`` since it returns text-layer parses, not OCR. Doesn't
    account for quality, latency, or feature differences.
    """
    candidates: list[tuple[str, float]] = []
    for spec in _PROVIDERS:
        if spec.name == "pypdf":
            continue
        config = OCRConfig(
            provider=spec.name,
            batch=batch_ok and spec.supports_batch,
        )
        try:
            per_page = spec.cost(1, config)
        except (ValueError, NotImplementedError):
            continue
        candidates.append((spec.name, per_page))
    if not candidates:
        raise RuntimeError("no providers available for cheapest_provider()")
    return min(candidates, key=lambda x: x[1])[0]
