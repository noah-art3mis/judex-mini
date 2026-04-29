"""Cost + wall-time forecasts for sweeps.

Predictive complement to `judex/utils/pricing.py` (which is post-hoc:
"how much did this run cost?"). These functions answer "given N
targets, how much will the sweep cost and how long will it take?".

All anchors below are real-run measurements, not guesses. Re-anchor
when the corpus doubles or after any major scrape pipeline change.

Anchor sources (re-measured 2026-04-29):

| anchor | value | source |
|---|---|---|
| `_AVG_PDF_MB` | 0.139 | mean of 79,084 cached `.pdf.gz` (median 0.117) |
| `_AVG_CASE_KB` | 47 | `docs/rate-limits.md` sweep V (170k HC blended) |
| `_AVG_REQ_WALL_S_DIRECT` | 3.0 | mean wall_s (incl. saturation tail + fails) over HC 2024 + HC 2023 overnight runs (~32k requests) |
| `_AVG_CASE_WALL_S_DIRECT` | 2.0 | derived from "12k HC cases @ 16 shards in ~25 min" anchor (CLAUDE.md / rate-limits.md), so 8 cases/sec sharded → 0.5 cases/sec single-IP |
| `_SHARD_SPEEDUP_X` | 12.7 | `docs/cost-estimates.md` TL;DR table: 1.8d direct-IP / 3.4h 16-shard. Below the 16× theoretical ceiling because of per-pool budget limits + ASN-level WAF reputation effects (see `docs/rate-limits.md § Two-layer model`). |
| `_SHARDS` | 16 | the only sharded-mode value supported in the CLI today |

The forecasts are coarse — useful for "is this run 1h or 1 day, $0
or $100" reasoning, not for billing. Single-IP wall in particular
under-predicts SSL-storm tails (one fail eats ~14m) and over-predicts
the honeymoon phase (~0.8s/req for the first ~10 minutes); the chosen
anchor is the realised overnight average.

Re-anchoring rule of thumb: if a recent sweep's `report.md` shows
`elapsed / reqs` more than 30% off `_AVG_REQ_WALL_S_DIRECT`, refresh
the constant from the latest two overnight runs and bump the date.
"""

from __future__ import annotations

from dataclasses import dataclass

from judex.utils.pricing import proxy_usd_per_gb


_AVG_PDF_MB: float = 0.139
_AVG_CASE_KB: float = 47.0
_AVG_REQ_WALL_S_DIRECT: float = 3.0
_AVG_CASE_WALL_S_DIRECT: float = 2.0
_SHARD_SPEEDUP_X: float = 12.7
_SHARDS: int = 16


@dataclass(frozen=True)
class Forecast:
    """One forecast row for one execution mode.

    `bandwidth_gb` is the *download* bandwidth — same in either mode
    since shards just split the work, not the byte count. `cost_usd`
    differs because direct-IP isn't billed and proxy is.
    """
    mode: str
    wall_s: float
    bandwidth_gb: float
    cost_usd: float
    notes: str


def forecast_baixar_pecas(n_targets: int) -> list[Forecast]:
    """Return single-IP and 16-shard forecasts for `baixar-pecas`."""
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
    """Return single-IP and 16-shard forecasts for `varrer-processos`.

    Bandwidth math uses the 47 KB/case blended anchor; this includes
    the multi-fragment fetch (`detalhe.asp`, `aba*.asp`, partes).
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
    """Return a single-mode forecast for `extrair-pecas`.

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
    rich-formatted output (logs end up in `launcher-stdout.log`).
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
