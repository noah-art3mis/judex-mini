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

from dataclasses import dataclass
from typing import Optional

from judex.scraping.ocr import chandra as _chandra
from judex.scraping.ocr import chandra_runpod as _chandra_runpod
from judex.scraping.ocr import gemini as _gemini
from judex.scraping.ocr import mistral as _mistral
from judex.scraping.ocr import paddle as _paddle
from judex.scraping.ocr import pypdf as _pypdf
from judex.scraping.ocr import surya as _surya
from judex.scraping.ocr import tesseract as _tesseract
from judex.scraping.ocr import tesseract_fly as _tesseract_fly
from judex.scraping.ocr import tesseract_modal as _tesseract_modal
from judex.scraping.ocr import unstructured as _unstructured
from judex.scraping.ocr.base import ExtractResult, OCRConfig, ProviderSpec


_PROVIDERS: list[ProviderSpec] = [
    _pypdf.SPEC,
    _unstructured.SPEC,
    _mistral.SPEC,
    _chandra.SPEC,
    _chandra_runpod.SPEC,
    _gemini.SPEC,
    _surya.SPEC,
    _paddle.SPEC,
    _tesseract.SPEC,
    _tesseract_modal.SPEC,
    _tesseract_fly.SPEC,
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


@dataclass(frozen=True)
class ProviderRow:
    """One row of :func:`provider_table` output.

    Pure data; the renderer formats it. Either ``cost_usd`` or
    ``wall_seconds`` may be ``None`` if the provider's anchor raised
    (e.g. Modal-hosted providers awaiting their first bakeoff).
    """

    name: str
    cost_usd: Optional[float]
    wall_seconds: Optional[float]
    supports_batch: bool


def provider_table(
    *,
    n_pdfs: int = 1,
    n_pages: int = 5,
    batch_ok: bool = True,
) -> list[ProviderRow]:
    """Build a row per provider in REGISTRY at the given workload size.

    Pure function — returns data, doesn't print. Sort is by cost
    ascending, with ``None``-cost providers (anchor not implemented)
    sorted last. Used by ``judex providers`` CLI and by ad-hoc scripts
    that want a programmatic comparison.

    Each provider is asked for its cost with batch=True when both
    ``batch_ok`` is set and the provider supports it (favouring the
    cheapest tier the operator can actually use); cost.batch falls
    back to sync otherwise.
    """
    rows: list[ProviderRow] = []
    for spec in _PROVIDERS:
        config = OCRConfig(
            provider=spec.name,
            batch=batch_ok and spec.supports_batch,
            api_key="dummy",  # placate provider classes that require it at construction
        )
        try:
            cost: Optional[float] = spec.cost(n_pages, config)
        except (ValueError, NotImplementedError, Exception):
            cost = None
        try:
            wall: Optional[float] = spec.wall(n_pdfs, config)
        except (ValueError, NotImplementedError, Exception):
            wall = None
        rows.append(ProviderRow(
            name=spec.name,
            cost_usd=cost,
            wall_seconds=wall,
            supports_batch=spec.supports_batch,
        ))
    rows.sort(key=lambda r: (r.cost_usd is None, r.cost_usd or 0.0))
    return rows


def render_provider_table(
    *,
    n_pdfs: int = 1,
    n_pages: int = 5,
    batch_ok: bool = True,
) -> str:
    """Render :func:`provider_table` as a fixed-width plain-text table.

    The format is intentionally terminal-friendly (no Rich, no ANSI):
    ``provider`` left-aligned, ``cost`` right-aligned, ``wall`` in
    minutes right-aligned, ``batch?`` last. ``—`` for missing anchors.
    """
    rows = provider_table(n_pdfs=n_pdfs, n_pages=n_pages, batch_ok=batch_ok)
    name_w = max(len("provider"), max(len(r.name) for r in rows))
    header = (
        f"{'provider':<{name_w}}  {'$':>9}  {'min':>8}  batch?"
    )
    lines = [
        header,
        "-" * len(header),
    ]
    for r in rows:
        cost_s = f"${r.cost_usd:.2f}" if r.cost_usd is not None else "—"
        wall_s = (
            f"{r.wall_seconds / 60:.0f}"
            if r.wall_seconds is not None else "—"
        )
        batch_s = "yes" if r.supports_batch else "no"
        lines.append(
            f"{r.name:<{name_w}}  {cost_s:>9}  {wall_s:>8}  {batch_s}"
        )
    return "\n".join(lines)


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
