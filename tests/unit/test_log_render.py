"""Behavior tests for the live-log line renderer.

Pins the format so `tail -f`-friendly stdout can evolve safely. Layout
is two-channel by design: this renderer is for *human* consumption
(stdout → launcher-stdout.log). Machine-readable channels (pdfs.log.jsonl,
state.json) are unaffected by anything tested here.
"""

from __future__ import annotations

import re

from collections import Counter

from judex.utils.log_render import (
    render_pipeline_progress_line,
    render_progress_line,
    render_target_line,
)


# ---------------------------------------------------------------------------
# render_target_line
# ---------------------------------------------------------------------------


def test_target_line_ok_contains_word_and_glyph():
    """Glyph for fast eye-scan AND status word for grep workflows."""
    line = render_target_line(
        n=129, total=404,
        status="ok", identifier="HC 267323 a3f5b2e",
        detail="pypdf · 18,234 chars",
        timestamp="13:48:23",
        use_color=False,
    )
    # Word survives so `grep ok` keeps working.
    assert " ok " in line, line
    # Glyph present.
    assert "✓" in line, line
    # Position info.
    assert "129/404" in line, line
    # Compact identifier.
    assert "HC 267323 a3f5b2e" in line, line
    # Detail.
    assert "pypdf" in line and "18,234" in line, line
    # Timestamp prefix.
    assert line.startswith("13:48:23"), line


def test_target_line_fail_uses_error_glyph_and_word():
    line = render_target_line(
        n=130, total=404,
        status="fail", identifier="HC 267323 b4e8c1d",
        detail="tesseract_fly · 502 Bad Gateway",
        timestamp="13:48:24",
        use_color=False,
    )
    assert "✗" in line
    assert " fail " in line, "preserve the status word for grep"
    assert "502 Bad Gateway" in line


def test_target_line_cached_and_no_bytes_use_distinct_glyphs():
    cached = render_target_line(
        n=131, total=404, status="cached",
        identifier="HC 267324 c8a92b1",
        detail="pypdf",
        timestamp="13:48:25", use_color=False,
    )
    no_bytes = render_target_line(
        n=132, total=404, status="no_bytes",
        identifier="HC 267325 d72e8f0",
        detail="-",
        timestamp="13:48:26", use_color=False,
    )
    assert "⊘" in cached
    assert "·" in no_bytes
    assert " cached " in cached
    assert " no_bytes " in no_bytes


def test_target_line_unknown_status_falls_back_to_neutral_glyph():
    """A new status type shouldn't crash — degrade gracefully."""
    line = render_target_line(
        n=1, total=1, status="some_new_status",
        identifier="HC 1 abc1234", detail="x",
        timestamp="00:00:00", use_color=False,
    )
    assert "some_new_status" in line
    # Doesn't raise; emits something readable.
    assert len(line) > 10


def test_target_line_known_sweep_statuses_have_non_neutral_glyph():
    """Pin every status the sweep drivers actually emit. Catches the
    `? unallocated` regression observed live in HC 2025 varrer where
    `unallocated` (legitimate STF-side dead PID) was rendering with the
    `?` fallback glyph because it wasn't in the style map.
    """
    sweep_statuses_with_glyph = [
        # HC year-ladder Stage A surfaces these
        ("ok", "✓"),
        ("fail", "✗"),
        ("error", "✗"),
        ("skipped", "⊘"),
        ("unallocated", "·"),  # the live-observed gap
        # peça pipeline (Stage B + C) surfaces these
        ("cached", "⊘"),
        ("no_bytes", "·"),
        ("empty", "·"),
        ("provider_error", "✗"),
        ("http_error", "✗"),
        ("unknown_type", "✗"),
        ("non_document_response", "✗"),
        ("empty_response", "·"),
    ]
    for status, expected_glyph in sweep_statuses_with_glyph:
        line = render_target_line(
            n=1, total=1, status=status,
            identifier="HC 1 abc1234", detail="x",
            timestamp="00:00:00", use_color=False,
        )
        assert expected_glyph in line, f"{status} should render {expected_glyph}, got: {line!r}"
        assert "?" not in line.split()[1:3], f"{status} fell back to ? glyph: {line!r}"


def test_target_line_no_color_when_use_color_false():
    """ANSI escape sequences must NOT appear when color is off (log files)."""
    line = render_target_line(
        n=1, total=1, status="ok", identifier="HC 1 abc1234",
        detail="x", timestamp="00:00:00", use_color=False,
    )
    # Strip-style assertion: no ESC sequences.
    assert "\x1b[" not in line, f"ANSI escape found in non-color mode: {line!r}"


def test_target_line_emits_color_when_use_color_true():
    """Smoke test: when colour is requested, ANSI sequences appear."""
    line = render_target_line(
        n=1, total=1, status="ok", identifier="HC 1 abc1234",
        detail="x", timestamp="00:00:00", use_color=True,
    )
    assert "\x1b[" in line, "expected ANSI escape in color mode"


# ---------------------------------------------------------------------------
# render_progress_line
# ---------------------------------------------------------------------------


def test_progress_line_separator_brackets_and_counters():
    line = render_progress_line(
        n=132, total=404,
        counters={"ok": 120, "fail": 10, "cached": 2},
        rate_per_sec=1.3, rate_label="tgt/s",
        eta_min=4.5, use_color=False,
    )
    # Bracketed separator for visual scan.
    assert "───" in line, line
    # Position + percent.
    assert "132/404" in line
    assert "32" in line  # 32.7% rounded -> contains "32"
    # Counters present.
    assert "ok=120" in line
    assert "fail=10" in line
    assert "cached=2" in line
    # Rate + ETA.
    assert "1.3" in line and "tgt/s" in line
    assert "4.5" in line


def test_progress_line_omits_zero_counters_to_reduce_noise():
    """Zero-count statuses are visual clutter; suppress them."""
    line = render_progress_line(
        n=10, total=100,
        counters={"ok": 10, "fail": 0, "cached": 0, "no_bytes": 0},
        rate_per_sec=0.5, rate_label="proc/s",
        eta_min=3.0, use_color=False,
    )
    assert "ok=10" in line
    # Zeros suppressed.
    assert "fail=" not in line
    assert "cached=" not in line


def test_progress_line_proc_s_label_for_varrer():
    """Varrer uses proc/s, baixar/extrair use tgt/s — preserve the label."""
    line = render_progress_line(
        n=1, total=1, counters={"ok": 1},
        rate_per_sec=7.5, rate_label="proc/s",
        eta_min=0.0, use_color=False,
    )
    assert "proc/s" in line
    assert "tgt/s" not in line


# ---------------------------------------------------------------------------
# render_pipeline_progress_line — three-stage executar pipeline
# ---------------------------------------------------------------------------


def test_pipeline_progress_processos_pct_only_when_no_totals_supplied():
    """Without pecas_total / text_total, only processos carries the
    `(X.X%)` ratio — its denominator (n_targets) is always known up
    front; pecas/text fall back to absolute counts so we don't show
    a wrong ratio for legacy state files."""
    line = render_pipeline_progress_line(
        n_targets=1000,
        processos=Counter({"ok": 500}),
        pecas=Counter({"ok": 1500}),
        text=Counter({"ok": 600}),
        use_color=False,
    )
    assert "(50.0%)" in line
    assert line.count("%") == 1


def test_pipeline_progress_pecas_total_renders_ratio():
    """Once `pecas_total` is known (post-meta-completion in new runs),
    pecas shows `pecas 1500/2300 ... (65.2%) ok=...` — the operator's
    answer to 'how many peca downloads are left'. Padding may sit
    between the number and the `(` so all stage `%` parens line up
    vertically (see test_pipeline_progress_pcts_align)."""
    line = render_pipeline_progress_line(
        n_targets=1000,
        processos=Counter({"ok": 1000}),
        pecas=Counter({"ok": 1450, "empty": 50}),
        text=Counter({"ok": 600}),
        pecas_total=2300,
        use_color=False,
    )
    assert "pecas 1500/2300" in line
    assert "(65.2%)" in line


def test_pipeline_progress_text_total_renders_ratio():
    """text_total = pecas["ok"] is always knowable from the live state
    (no n_pecas needed). Renderer surfaces it whenever the caller
    supplies the value, so even on legacy runs the operator gets
    a text ratio (which is the slowest stage and the real ETA driver)."""
    line = render_pipeline_progress_line(
        n_targets=1000,
        processos=Counter({"ok": 1000}),
        pecas=Counter({"ok": 2300, "empty": 50}),
        text=Counter({"ok": 1500, "skipped_cached": 600}),
        text_total=2300,
        use_color=False,
    )
    assert "text 2100/2300" in line
    assert "(91.3%)" in line


def test_pipeline_progress_pcts_align_vertically_across_stages():
    """The user's explicit ask: when multiple stages render a
    percentage, the ``(`` of each ``(X.X%)`` must line up vertically.
    Achieved by padding each ``label N/total`` segment to the longest
    among ratio-bearing stages."""
    line = render_pipeline_progress_line(
        n_targets=9137,
        processos=Counter({"ok": 8101, "unallocated_pid": 1036}),
        pecas=Counter({"ok": 24337}),
        text=Counter({"ok": 15173}),
        pecas_total=25164,
        text_total=24337,
        prefix="[12:00:00 agg]",
        use_color=False,
    )
    # Line column positions of the first '(' on each stage row.
    rows = line.split("\n")
    paren_cols = [r.index("(") for r in rows if "(" in r]
    assert len(paren_cols) == 3, rows
    assert len(set(paren_cols)) == 1, paren_cols  # all aligned


def test_pipeline_progress_renders_all_status_keys():
    """Every status with a non-zero count must appear — `provider_error=11`
    can't get folded into a `fail` bucket or hidden by zero suppression."""
    line = render_pipeline_progress_line(
        n_targets=571,
        processos=Counter({"ok": 500, "unallocated_pid": 70}),
        pecas=Counter({"ok": 1500, "empty": 50}),
        text=Counter({"ok": 600, "skipped_cached": 489, "provider_error": 11}),
        use_color=False,
    )
    assert "ok=500" in line
    assert "unallocated_pid=70" in line
    assert "ok=1500" in line and "empty=50" in line
    assert "skipped_cached=489" in line
    assert "provider_error=11" in line


def test_pipeline_progress_orders_failures_after_successes():
    """Within a stage, failure-class statuses sort after the success
    cluster so the operator's eye lands on errors at the rightmost
    position."""
    line = render_pipeline_progress_line(
        n_targets=0,
        processos=Counter(),
        pecas=Counter(),
        text=Counter({"provider_error": 5, "ok": 100}),
        use_color=False,
    )
    assert line.index("ok=100") < line.index("provider_error=5")


def test_pipeline_progress_eta_has_basis_label():
    """`eta(OCR) 4.2 min` so the operator knows the ETA is OCR-driven,
    not meta-driven (processos finishes first; quoting its rate would
    zero out the ETA prematurely)."""
    line = render_pipeline_progress_line(
        n_targets=100,
        processos=Counter({"ok": 100}),
        pecas=Counter({"ok": 250}),
        text=Counter({"ok": 50}),
        rate_per_sec=0.55,
        eta_min=4.2,
        eta_basis="OCR",
        use_color=False,
    )
    assert "0.55 cases/s" in line
    assert "eta(OCR) 4.2 min" in line


def test_pipeline_progress_handles_zero_targets_with_question_mark():
    """Pre-launch / pre-CSV-resolution edge: render without crashing,
    show `?` for the unknown processos denominator and omit the
    percentage."""
    line = render_pipeline_progress_line(
        n_targets=0,
        processos=Counter(),
        pecas=Counter(),
        text=Counter(),
        use_color=False,
    )
    assert "processos 0/?" in line
    assert "%" not in line


def test_pipeline_progress_prefix_renders_inline_with_space():
    """The shard aggregate prefix (`[12:00:00 agg]`) must read as a
    natural opening, not pretend to be a stage. Joined to the body
    with a space, not the stage `·` separator."""
    line = render_pipeline_progress_line(
        n_targets=100,
        processos=Counter({"ok": 50}),
        pecas=Counter(),
        text=Counter(),
        prefix="[12:00:00 agg]",
        use_color=False,
    )
    assert "[12:00:00 agg] processos" in line
    # Sanity: NOT joined as `[12:00:00 agg] · processos`.
    assert "[12:00:00 agg] · processos" not in line
