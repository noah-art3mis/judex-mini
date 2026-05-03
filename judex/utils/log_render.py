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


def _stage_pre_pct(
    label: str,
    done: int,
    total: Optional[int],
    unknown_marker: Optional[str],
) -> tuple[str, bool, float]:
    """Compute the ``label N/total`` segment that PRECEDES the
    ``(X.X%)`` parenthetical.

    Returns ``(pre, has_ratio, pct_value)``. ``has_ratio`` flags whether
    a ``(pct%)`` follows — only stages with ``total`` set qualify; the
    ``unknown_marker`` path renders ``?`` instead of a number and has
    no percentage to pad-align.
    """
    if total:
        return f"{label} {done}/{total}", True, 100.0 * done / total
    if unknown_marker is not None:
        return f"{label} {done}/{unknown_marker}", False, 0.0
    return f"{label} {done}", False, 0.0


def render_pipeline_progress_line(
    *,
    n_targets: int,
    processos: Mapping[str, int],
    pecas: Mapping[str, int],
    text: Mapping[str, int],
    pecas_total: Optional[int] = None,
    text_total: Optional[int] = None,
    prefix: Optional[str] = None,
    rate_per_sec: Optional[float] = None,
    eta_min: Optional[float] = None,
    eta_basis: Optional[str] = None,
    use_color: bool | None = None,
) -> str:
    """Three-stage progress block for the unified executar pipeline.

    Layout (sharded, with all optionals)::

        ─── [12:00:00 agg] processos 500/9137 (5.5%) ok=440 unallocated_pid=60 ───
        ─── [12:00:00 agg]     pecas 1500/2300 (65.2%) ok=1450 empty=50 ───
        ─── [12:00:00 agg]      text 1100/1450 (75.9%) ok=600 skipped_cached=489 provider_error=11 · 0.55 cases/s · eta(OCR) 4.2 min ───

    Three lines, one per stage. Each line is self-bookended with
    ``───`` so it stays visually distinct from per-task tail lines and
    survives ``grep`` (every line carries the timestamp prefix when
    sharded). Labels are right-padded to 9 chars (``len("processos")``)
    so the data columns line up vertically.

    Three stages, three nouns: ``processos`` (case-meta scrape),
    ``pecas`` (peca PDF download), ``text`` (text extraction). Each
    stage's denominator is rendered when knowable:

    * ``processos`` — denominator is ``n_targets`` (CSV row count, known
      up front); falls back to ``?`` pre-CSV-resolution.
    * ``pecas`` — denominator is ``pecas_total``: sum of ``n_pecas``
      stamped on each meta=ok record at fan-out time. Becomes known the
      moment meta finishes; None on legacy state files (the renderer
      drops the ratio rather than show a fabricated number).
    * ``text`` — denominator is ``text_total``: equals ``pecas["ok"]`` at
      any moment, since every successful pecas download emits exactly
      one extract_text successor. Always knowable (grows during pecas;
      locks once pecas is done).

    All status counts render unconditionally (no zero suppression):
    a ``provider_error=0 → 1`` transition would otherwise materialise
    out of nowhere with no prior baseline, which makes errors easy
    to miss when scrolling.

    Rate / ETA, when present, ride along on the ``text`` line — text is
    the slowest stage and the actual ETA driver, so co-locating those
    numbers with the text counts puts the bottleneck signal in one
    place. ``eta_basis`` (e.g. ``"OCR"``) labels which stage's rate
    drove the ETA, so the operator knows what the number means.

    Returns a single string with embedded ``\\n`` separators (three
    lines). One ``log.info`` / ``print`` call emits all three; tail
    viewers see them in order.
    """
    color_mode = use_color if use_color is not None else should_use_color()

    # Build each stage's `label N/total` (pre-pct) + its mix separately
    # so we can pad the pre-pct strings to a uniform width, making the
    # `(X.X%)` parens line up vertically across the three lines.
    p_pre, p_has, p_pct = _stage_pre_pct(
        "processos", sum(processos.values()), n_targets or None, "?",
    )
    pe_pre, pe_has, pe_pct = _stage_pre_pct(
        "pecas", sum(pecas.values()), pecas_total, None,
    )
    t_pre, t_has, t_pct = _stage_pre_pct(
        "text", sum(text.values()), text_total, None,
    )

    # Width to pad to: the longest pre-pct among stages that DO render
    # a percentage. Stages without a ratio (legacy pecas, processos
    # pre-CSV-resolution) don't need to align — they have nothing to
    # align with — so they skip padding and read clean.
    aligned_w = max(
        (len(p) for p, has in [(p_pre, p_has), (pe_pre, pe_has), (t_pre, t_has)]
         if has),
        default=0,
    )

    def _assemble(pre: str, has_ratio: bool, pct_value: float, mix: str) -> str:
        if has_ratio:
            head = f"{pre.ljust(aligned_w)} ({pct_value:.1f}%)"
        else:
            head = pre
        return head + (f" {mix}" if mix else "")

    processos_body = _assemble(p_pre, p_has, p_pct, _fmt_stage_counts(processos))
    pecas_body = _assemble(pe_pre, pe_has, pe_pct, _fmt_stage_counts(pecas))
    text_body = _assemble(t_pre, t_has, t_pct, _fmt_stage_counts(text))

    # Rate / ETA glued to the text line (same `·` separator as the
    # within-block status mix uses, so visual continuity holds).
    if rate_per_sec is not None:
        text_body += f" · {rate_per_sec:.2f} cases/s"
    if eta_min is not None:
        eta_label = f"eta({eta_basis})" if eta_basis else "eta"
        text_body += f" · {eta_label} {eta_min:.1f} min"

    head = f"─── {prefix} " if prefix else "─── "
    bodies = [processos_body, pecas_body, text_body]
    if color_mode:
        lines = [f"{_ANSI_BOLD}{head}{b} ───{_ANSI_RESET}" for b in bodies]
    else:
        lines = [f"{head}{b} ───" for b in bodies]
    return "\n".join(lines)


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
