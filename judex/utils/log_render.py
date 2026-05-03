"""Live-log line rendering for sweep stdout.

Two-channel discipline (already established in this codebase):

- **Machine-readable**: pdfs.log.jsonl / sweep.log.jsonl / state.json /
  errors.jsonl. Stable schemas, atomic writes, what the runtime + tooling
  read. `judex analisar-regimes`, `judex probe`, the warehouse build,
  ``--retentar-de`` replay — all read JSONL/state, never stdout.
- **Human-readable**: stdout (→ launcher-stdout.log when nohup-detached).
  Read only by humans via `tail -f`. This module owns the format.

Format goals (vs the legacy `[N/total] <url>: ok (X chars)` shape):

1. **Glyph + status word** for each line. Glyph drives fast eye-scan
   (`✓✓✓✗⊘`); the word survives so `grep ok` / `grep provider_error`
   still works.
2. **Timestamp prefix** (`HH:MM:SS`). Tail viewers can see when the rate
   dropped without scrolling.
3. **Compact identifier** instead of the full STF URL — full URL still
   in pdfs.log.jsonl. Frees ~60 chars per line for the actual outcome.
4. **Periodic progress** uses ``─── 132/404 (32.7%) · ... ───`` separator
   so the eye finds it instantly when scrolling.
5. **Color when TTY, plain when log file**. Auto-detects via
   `stream.isatty()`, same idiom as `judex/utils/cli_render.py`.
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from typing import Mapping, Optional, TextIO


# ---------------------------------------------------------------------------
# Status -> (glyph, ANSI color code) mapping
# ---------------------------------------------------------------------------

# ANSI colors — only emitted when use_color=True. Plain mode skips entirely.
_ANSI_RESET = "\x1b[0m"
_ANSI_GREEN = "\x1b[32m"
_ANSI_RED = "\x1b[31m"
_ANSI_YELLOW = "\x1b[33m"
_ANSI_CYAN = "\x1b[36m"
_ANSI_DIM = "\x1b[2m"
_ANSI_BOLD = "\x1b[1m"


_STATUS_STYLE: dict[str, tuple[str, str]] = {
    # success
    "ok":              ("✓", _ANSI_GREEN),
    "downloaded":      ("✓", _ANSI_GREEN),
    "extracted":       ("✓", _ANSI_GREEN),
    "complete":        ("✓", _ANSI_GREEN),
    # cached / skipped (already done — neutral, dim)
    "cached":          ("⊘", _ANSI_CYAN),
    "skipped":         ("⊘", _ANSI_CYAN),
    # benign empty / no-data / STF-side gaps (work cannot be done, not a failure)
    "empty":           ("·", _ANSI_DIM),
    "no_bytes":        ("·", _ANSI_DIM),
    "empty_response":  ("·", _ANSI_DIM),
    "unallocated":     ("·", _ANSI_DIM),
    # errors
    "fail":            ("✗", _ANSI_RED),
    "error":           ("✗", _ANSI_RED),
    "provider_error":  ("✗", _ANSI_RED),
    "http_error":      ("✗", _ANSI_RED),
    "unknown_type":    ("✗", _ANSI_RED),
    "non_document_response": ("✗", _ANSI_RED),
    # warning-ish
    "anomaly":         ("⚠", _ANSI_YELLOW),
}

_NEUTRAL_GLYPH = "?"
_NEUTRAL_COLOR = ""


def _style_for(status: str) -> tuple[str, str]:
    return _STATUS_STYLE.get(status, (_NEUTRAL_GLYPH, _NEUTRAL_COLOR))


def _now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


def compact_target_id(
    url: str,
    *,
    classe: Optional[str] = None,
    processo_id: Optional[int] = None,
    sha_chars: int = 7,
) -> str:
    """Build a `tail -f`-friendly identifier for a peça URL.

    Example: ``compact_target_id(url, classe="HC", processo_id=267323)``
    → ``"HC 267323 a3f5b2e"`` — STF URLs are 70-100 chars and dominate
    the screen if logged whole. The full URL is preserved in
    ``pdfs.log.jsonl`` for any downstream tooling that needs it.
    """
    sha = hashlib.sha1(url.encode("utf-8")).hexdigest()[:sha_chars]
    parts: list[str] = []
    if classe:
        parts.append(classe)
    if processo_id is not None:
        parts.append(str(processo_id))
    parts.append(sha)
    return " ".join(parts)


def should_use_color(stream: TextIO | None = None) -> bool:
    """Detect whether stdout supports color. False when redirected to a file."""
    target = stream if stream is not None else sys.stdout
    return bool(getattr(target, "isatty", lambda: False)())


# ---------------------------------------------------------------------------
# Public renderers
# ---------------------------------------------------------------------------


def render_target_line(
    *,
    n: int,
    total: int,
    status: str,
    identifier: str,
    detail: str,
    timestamp: str | None = None,
    extra: str | None = None,
    use_color: bool | None = None,
) -> str:
    """Render one per-target log line for `tail -f`-friendly stdout.

    Layout::

        13:48:23  ✓ ok      129/404  HC 267323 a3f5b2e   pypdf · 18,234 chars

    Fixed columns: timestamp, glyph+word, position, identifier, detail.
    The status word stays inline (alongside the glyph) so `grep ok` /
    `grep provider_error` workflows keep working.
    """
    ts = timestamp if timestamp is not None else _now_hms()
    color_mode = use_color if use_color is not None else should_use_color()
    glyph, color = _style_for(status)

    # Status block: glyph + word. Word padded to 8 chars so detail aligns.
    word = status
    status_block = f"{glyph} {word:<8}"
    if color_mode and color:
        status_block = f"{color}{status_block}{_ANSI_RESET}"

    # Position. Pad numerically to keep alignment as N grows.
    n_width = max(len(str(total)), 4)
    pos = f"{n:>{n_width}}/{total}"

    parts = [ts, status_block, pos, identifier, detail]
    if extra:
        parts.append(extra)
    return "  ".join(parts)


def render_progress_line(
    *,
    n: int,
    total: int,
    counters: Mapping[str, int],
    rate_per_sec: float,
    rate_label: str = "tgt/s",
    eta_min: float,
    use_color: bool | None = None,
) -> str:
    """Render the periodic ``[progress]``-equivalent separator.

    Layout::

        ─── 132/404 (32.7%) · ok=120 fail=10 cached=2 · 1.3 tgt/s · eta 4.5 min ───

    Bracketed by ``───`` so the eye finds it when scrolling. Zero-count
    statuses are suppressed (visual noise reduction).
    """
    color_mode = use_color if use_color is not None else should_use_color()

    pct = (100.0 * n / total) if total else 0.0
    counter_parts = [
        f"{name}={count}"
        for name, count in counters.items()
        if count  # suppress zero-count noise
    ]
    counter_str = " ".join(counter_parts) if counter_parts else "(no events yet)"

    body = (
        f"{n}/{total} ({pct:.1f}%) · {counter_str} · "
        f"{rate_per_sec:.2f} {rate_label} · eta {eta_min:.1f} min"
    )
    line = f"─── {body} ───"

    if color_mode:
        line = f"{_ANSI_BOLD}{line}{_ANSI_RESET}"
    return line


_PIPELINE_STATUS_ORDER: tuple[str, ...] = (
    "ok", "skipped_cached", "cached", "skipped",
    "empty", "no_bytes", "unallocated_pid",
    "fail", "error", "provider_error", "http_error",
)


def _fmt_stage_counts(c: Mapping[str, int]) -> str:
    """Render one stage's status mix as ``ok=440 unallocated_pid=60``,
    success classes first, anomalies last so the eye lands on errors."""
    items = [(k, v) for k, v in c.items() if v]
    if not items:
        return ""
    priority = {k: i for i, k in enumerate(_PIPELINE_STATUS_ORDER)}
    items.sort(key=lambda kv: priority.get(kv[0], len(_PIPELINE_STATUS_ORDER)))
    return " ".join(f"{k}={v}" for k, v in items)


def render_pipeline_progress_line(
    *,
    n_targets: int,
    meta: Mapping[str, int],
    bytes_st: Mapping[str, int],
    text_st: Mapping[str, int],
    prefix: Optional[str] = None,
    rate_per_sec: Optional[float] = None,
    eta_min: Optional[float] = None,
    eta_basis: Optional[str] = None,
    use_color: bool | None = None,
) -> str:
    """Three-stage progress line for the unified executar pipeline.

    Layout (with all optionals)::

        ─── [12:00:00 agg] meta 500/9137 (5.5%) ok=440 unallocated_pid=60 ·
            bytes 1500 ok=1450 empty=50 ·
            text 1100 ok=600 skipped_cached=489 provider_error=11 ·
            0.55 cases/s · eta(OCR) 4.2 min ───

    Differs from :func:`render_progress_line` in that no single
    ``n/total`` summary fits a three-stage pipeline (1 case → many
    PDFs → many texts; cardinalities diverge). Only meta has a static
    denominator (``n_targets``), so only meta carries a percentage —
    bytes/text show absolute counts to avoid implying a forecast that
    doesn't exist until meta finishes.

    All status counts render unconditionally (no zero suppression):
    a ``provider_error=0 → 1`` transition would otherwise materialise
    out of nowhere with no prior baseline, which makes errors easy
    to miss when scrolling.

    ``eta_basis`` is a short label for which stage drives the ETA
    (typically ``"OCR"`` since text extraction is the slowest); shown
    as ``eta(OCR)`` so the operator knows what the number means.
    """
    color_mode = use_color if use_color is not None else should_use_color()

    meta_done = sum(meta.values())
    pct = (100.0 * meta_done / n_targets) if n_targets else 0.0
    denom = str(n_targets) if n_targets else "?"
    pct_str = f" ({pct:.1f}%)" if n_targets else ""

    meta_mix = _fmt_stage_counts(meta)
    bytes_done = sum(bytes_st.values())
    bytes_mix = _fmt_stage_counts(bytes_st)
    text_done = sum(text_st.values())
    text_mix = _fmt_stage_counts(text_st)
    parts: list[str] = [
        f"meta {meta_done}/{denom}{pct_str}" + (f" {meta_mix}" if meta_mix else ""),
        f"bytes {bytes_done}" + (f" {bytes_mix}" if bytes_mix else ""),
        f"text {text_done}" + (f" {text_mix}" if text_mix else ""),
    ]
    if rate_per_sec is not None:
        parts.append(f"{rate_per_sec:.2f} cases/s")
    if eta_min is not None:
        eta_label = f"eta({eta_basis})" if eta_basis else "eta"
        parts.append(f"{eta_label} {eta_min:.1f} min")

    body = " · ".join(parts)
    if prefix:
        body = f"{prefix} {body}"
    line = f"─── {body} ───"
    if color_mode:
        line = f"{_ANSI_BOLD}{line}{_ANSI_RESET}"
    return line


def render_run_header(
    *,
    title: str,
    fields: Mapping[str, str],
    use_color: bool | None = None,
) -> str:
    """Optional run-startup banner.

    Layout::

        ═══ extrair-pecas · HC 267138-271139 · provedor=auto · --paralelo 10 ═══
           targets:  5,273 PDFs across 2,780 processes
           forecast: $0.03 · ~30 min
           output:   runs/active/.../extrair
        ══════════════════════════════════════════════════════════════════════════
    """
    color_mode = use_color if use_color is not None else should_use_color()
    bar = "═" * 78
    rows = [f"═══ {title} " + "═" * max(0, 75 - len(title))]
    for k, v in fields.items():
        rows.append(f"   {k}: {v}")
    rows.append(bar)

    out = "\n".join(rows)
    if color_mode:
        out = f"{_ANSI_BOLD}{out}{_ANSI_RESET}"
    return out
