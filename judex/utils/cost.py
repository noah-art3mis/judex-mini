"""Cost surfaces for sweeps — pre-launch forecasts + post-hoc attribution.

This module replaces the prior split between ``judex.utils.forecasts``
(pre-launch: ``--prever``) and ``judex.utils.pricing`` (post-hoc:
``report.md`` cost line). The split was a documentation distinction,
not an architectural one — both surfaces answered "how much does X
cost?" against the same anchored constants. The OCR rate constants
in ``pricing`` had already drifted from the provider SPECs (only knew
pypdf/mistral/chandra/unstructured; missing gemini/paddle/surya/
tesseract added in the OCR-bakeoff work) by the time of unification.

Two surfaces, side by side:

- **pre-launch forecasting** — ``forecast_baixar_pecas``,
  ``forecast_varrer_processos``, ``forecast_extrair_pecas``. Used by
  ``judex {varrer,baixar,extrair}-pecas --prever`` to print a wall +
  cost preview.
- **post-hoc attribution** — ``estimate_proxy_cost``,
  ``estimate_ocr_cost``. Used by drivers at end-of-run to print the
  cost line on ``report.md``.

Both surfaces share two rate sources:

- ``proxy_usd_per_gb()`` — env-overridable via
  ``PROXY_PRICE_USD_PER_GB``. Default: $3.65/GB (residential proxy).
- ``ocr_usd_per_1k_pages(provider)`` — env-overridable via
  ``OCR_PRICE_<PROVIDER>_USD_PER_1K_PAGES``. Falls back to the
  provider's SPEC at its cheapest tier (batch when supported, sync
  otherwise). The SPEC is the single source of truth for OCR rates;
  this rate getter is a thin facade with env override.

Real-run anchors (re-measured 2026-05-01 for ``_AVG_PDF_MB``,
2026-04-29 for the rest):

| anchor                     | value  | source                                                 |
|----------------------------|--------|--------------------------------------------------------|
| ``_AVG_PDF_MB``            | 0.1685 | mean of 90,168 cached `.pdf.gz` (median 0.146); RTFs   |
|                            |        | now live in `.rtf.gz` (separate ext); empty-body       |
|                            |        | gzip entries excluded. Pre-rename the same population  |
|                            |        | mean was 0.139 — biased low by 2,417 RTFs and 1,506    |
|                            |        | empty 0-byte downloads contaminating the .pdf.gz set.  |
| ``_AVG_CASE_KB``           | 47    | docs/rate-limits.md sweep V (170k HC blended)           |
| ``_AVG_REQ_WALL_S_DIRECT`` | 3.0   | HC 2024 + HC 2023 overnight runs (~32k requests)        |
| ``_AVG_CASE_WALL_S_DIRECT``| 2.0   | "12k HC cases @ 16 shards in ~25 min" anchor            |
| ``_SHARD_SPEEDUP_X``       | 12.7  | docs/cost-estimates.md TL;DR (1.8d direct / 3.4h 16x)   |
| ``_SHARDS``                | 16    | only sharded-mode value supported in the CLI today      |

The forecasts are coarse — useful for "is this run 1h or 1 day, $0 or
$100" reasoning, not for billing. Single-IP wall under-predicts SSL
tail-storm fails (one fail eats ~14m) and over-predicts the honeymoon
phase (~0.8s/req for the first ~10 minutes); the chosen anchor is
the realised overnight average.

Re-anchoring rule of thumb: if a recent sweep's ``report.md`` shows
``elapsed/reqs`` more than 30% off ``_AVG_REQ_WALL_S_DIRECT``, refresh
the constant from the latest two overnight runs and bump the date.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


# ----- Anchored constants ----------------------------------------------------

_AVG_PDF_MB: float = 0.1685
_AVG_CASE_KB: float = 47.0
_AVG_REQ_WALL_S_DIRECT: float = 3.0
_AVG_CASE_WALL_S_DIRECT: float = 2.0
_SHARD_SPEEDUP_X: float = 12.7
_SHARDS: int = 16

_DEFAULT_PROXY_USD_PER_GB: float = 3.65


# ----- Rate sources ----------------------------------------------------------


def proxy_usd_per_gb() -> float:
    """Per-GB residential-proxy rate. Env-overridable.

    Override with ``PROXY_PRICE_USD_PER_GB=<float>``. Falls back to the
    default if the env var is missing or malformed.
    """
    raw = os.environ.get("PROXY_PRICE_USD_PER_GB")
    if raw is None:
        return _DEFAULT_PROXY_USD_PER_GB
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_PROXY_USD_PER_GB


def ocr_usd_per_1k_pages(provider: str) -> float:
    """Per-1k-pages OCR rate for ``provider``. Env-overridable.

    Default is the cheapest tier from the provider's SPEC (batch when
    supported, sync otherwise). Override with
    ``OCR_PRICE_<PROVIDER>_USD_PER_1K_PAGES=<float>``; falls back to the
    SPEC default on missing or malformed env. ``pypdf`` returns 0.0
    (local, no API bill).
    """
    p = provider.lower()
    env_key = f"OCR_PRICE_{p.upper()}_USD_PER_1K_PAGES"
    raw = os.environ.get(env_key)
    if raw is not None:
        try:
            return float(raw)
        except ValueError:
            pass  # fall through to SPEC lookup
    if p in ("pypdf", "tesseract", "auto"):
        # All free / local-CPU: pypdf has no API bill; `tesseract` runs
        # on the operator's host (the Modal-hosted billed sibling lives
        # at `tesseract_modal`); `auto` routes only between those two.
        # If `auto` ever fans out to a billed provider, this special
        # case has to become a per-target cost computation in
        # extract_driver.
        return 0.0
    # SPEC is the source of truth for OCR rates post the OCR-deepening.
    from judex.scraping.ocr.base import OCRConfig
    from judex.scraping.ocr.dispatch import get_provider

    spec = get_provider(p)
    config = OCRConfig(provider=p, batch=spec.supports_batch)
    # spec.cost(1000, ...) returns USD for 1000 pages == USD per 1k pages.
    return spec.cost(1000, config)


# ----- Forecast dataclass + pre-launch forecasts ----------------------------


@dataclass(frozen=True)
class Forecast:
    """One forecast row for one execution mode.

    ``bandwidth_gb`` is the *download* bandwidth — same in either mode
    since shards just split the work, not the byte count. ``cost_usd``
    differs because direct-IP isn't billed and proxy is.
    """

    mode: str
    wall_s: float
    bandwidth_gb: float
    cost_usd: float
    notes: str


def forecast_baixar_pecas(n_targets: int) -> list[Forecast]:
    """Return single-IP and 16-shard forecasts for ``baixar-pecas``."""
    bandwidth_gb = n_targets * _AVG_PDF_MB / 1024
    wall_single = n_targets * _AVG_REQ_WALL_S_DIRECT
    wall_shards = wall_single / _SHARD_SPEEDUP_X
    proxy_rate = proxy_usd_per_gb()
    cost_proxy = bandwidth_gb * proxy_rate
    return [
        Forecast(
            mode="single direct-IP",
            wall_s=wall_single,
            bandwidth_gb=bandwidth_gb,
            cost_usd=0.0,
            notes="no proxy bill; WAF ceiling caps throughput",
        ),
        Forecast(
            mode=f"{_SHARDS} shards + proxy",
            wall_s=wall_shards,
            bandwidth_gb=bandwidth_gb,
            cost_usd=cost_proxy,
            notes=f"{bandwidth_gb:.2f} GB × ${proxy_rate:.2f}/GB residential",
        ),
    ]


def forecast_varrer_processos(n_cases: int) -> list[Forecast]:
    """Return single-IP and 16-shard forecasts for ``varrer-processos``.

    Bandwidth math uses the 47 KB/case blended anchor; this includes
    the multi-fragment fetch (``detalhe.asp``, ``aba*.asp``, partes).
    """
    bandwidth_gb = n_cases * _AVG_CASE_KB / (1024 * 1024)
    wall_single = n_cases * _AVG_CASE_WALL_S_DIRECT
    wall_shards = wall_single / _SHARD_SPEEDUP_X
    proxy_rate = proxy_usd_per_gb()
    cost_proxy = bandwidth_gb * proxy_rate
    return [
        Forecast(
            mode="single direct-IP",
            wall_s=wall_single,
            bandwidth_gb=bandwidth_gb,
            cost_usd=0.0,
            notes="no proxy bill; expect cliffs on >2k case sweeps",
        ),
        Forecast(
            mode=f"{_SHARDS} shards + proxy",
            wall_s=wall_shards,
            bandwidth_gb=bandwidth_gb,
            cost_usd=cost_proxy,
            notes=f"{bandwidth_gb*1024:.1f} MB × ${proxy_rate:.2f}/GB residential",
        ),
    ]


def forecast_extrair_pecas(n_pdfs: int, provedor: str) -> list[Forecast]:
    """Return a single-mode forecast for ``extrair-pecas``.

    OCR is local-first or API-bound — sharding doesn't apply (no STF
    rate limit involved). Returns a one-element list to keep the
    rendering path uniform with the other forecasts.
    """
    from judex.scraping.ocr.dispatch import estimate_cost, estimate_wall

    n_pages = int(n_pdfs * 4.9)
    cost = estimate_cost(provedor, n_pages)
    wall = estimate_wall(provedor, n_pdfs)
    note = (
        "local extractor, no API bill"
        if provedor == "pypdf"
        else f"API-billed at provider rate ({provedor})"
    )
    return [
        Forecast(
            mode=f"OCR via {provedor}",
            wall_s=wall,
            bandwidth_gb=0.0,
            cost_usd=cost,
            notes=note,
        ),
    ]


# ----- Pretty-printing -------------------------------------------------------


def _format_wall(wall_s: float) -> str:
    if wall_s < 60:
        return f"{wall_s:>5.1f}s"
    if wall_s < 3600:
        return f"{wall_s/60:>4.1f}m"
    if wall_s < 24 * 3600:
        return f"{wall_s/3600:>4.1f}h"
    return f"{wall_s/86400:>4.1f}d"


def render_forecast_table(
    forecasts: list[Forecast], *, n_units: int, unit_label: str,
) -> str:
    """Render forecasts as a fixed-width table for the CLI preview.

    Designed for the launcher's stdout — readable plain, no
    rich-formatted output (logs end up in ``launcher-stdout.log``).
    """
    header = f"forecast — {n_units:,} {unit_label}"
    rows = [
        header,
        "-" * len(header),
        f"  {'mode':<22}  {'wall':>6}  {'cost':>8}  notes",
    ]
    for f in forecasts:
        rows.append(
            f"  {f.mode:<22}  {_format_wall(f.wall_s):>6}  "
            f"${f.cost_usd:>7.2f}  {f.notes}"
        )
    return "\n".join(rows) + "\n"


# ----- Post-hoc attribution dataclasses --------------------------------------


@dataclass(frozen=True)
class ProxyCost:
    bytes_downloaded: int
    used_proxy: bool
    usd_per_gb: float

    @property
    def dollars(self) -> float:
        if not self.used_proxy:
            return 0.0
        return (self.bytes_downloaded / 1_000_000_000) * self.usd_per_gb

    def summary_line(self) -> str:
        if not self.used_proxy:
            return "cost: $0.00 (direct-IP, no proxy bandwidth billed)"
        mb = self.bytes_downloaded / 1_000_000
        return (
            f"cost: ~${self.dollars:.2f}  "
            f"({mb:.1f} MB via proxy @ ${self.usd_per_gb:.2f}/GB)"
        )


@dataclass(frozen=True)
class OcrCost:
    provider: str
    pages: int
    usd_per_1k_pages: float

    @property
    def dollars(self) -> float:
        if self.provider == "pypdf":
            return 0.0
        return (self.pages / 1_000) * self.usd_per_1k_pages

    def summary_line(self) -> str:
        if self.provider == "pypdf":
            return f"cost: $0.00 ({self.pages} pages via pypdf, local/free)"
        return (
            f"cost: ~${self.dollars:.2f}  "
            f"({self.pages} pages via {self.provider} @ "
            f"${self.usd_per_1k_pages:.2f}/1k pages)"
        )


def estimate_proxy_cost(
    *,
    bytes_downloaded: int,
    used_proxy: bool,
    usd_per_gb: Optional[float] = None,
) -> ProxyCost:
    rate = usd_per_gb if usd_per_gb is not None else proxy_usd_per_gb()
    return ProxyCost(
        bytes_downloaded=bytes_downloaded,
        used_proxy=used_proxy,
        usd_per_gb=rate,
    )


def estimate_ocr_cost(
    *,
    provider: str,
    pages: int,
    usd_per_1k_pages: Optional[float] = None,
) -> OcrCost:
    rate = (
        usd_per_1k_pages
        if usd_per_1k_pages is not None
        else ocr_usd_per_1k_pages(provider)
    )
    return OcrCost(provider=provider, pages=pages, usd_per_1k_pages=rate)
