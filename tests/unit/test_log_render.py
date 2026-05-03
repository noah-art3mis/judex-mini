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


def test_pipeline_progress_meta_pct_only_bytes_text_no_pct():
    """Meta has a static denominator (n_targets, known up front); bytes
    and text denominators grow with meta, so a percentage there would
    lie until meta is fully done. Only meta carries `(X.X%)`."""
    line = render_pipeline_progress_line(
        n_targets=1000,
        meta=Counter({"ok": 500}),
        bytes_st=Counter({"ok": 1500}),
        text_st=Counter({"ok": 600}),
        use_color=False,
    )
    assert "(50.0%)" in line
    assert line.count("%") == 1


def test_pipeline_progress_renders_all_status_keys():
    """Every status with a non-zero count must appear — `provider_error=11`
    can't get folded into a `fail` bucket or hidden by zero suppression."""
    line = render_pipeline_progress_line(
        n_targets=571,
        meta=Counter({"ok": 500, "unallocated_pid": 70}),
        bytes_st=Counter({"ok": 1500, "empty": 50}),
        text_st=Counter({"ok": 600, "skipped_cached": 489, "provider_error": 11}),
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
        meta=Counter(),
        bytes_st=Counter(),
        text_st=Counter({"provider_error": 5, "ok": 100}),
        use_color=False,
    )
    assert line.index("ok=100") < line.index("provider_error=5")


def test_pipeline_progress_eta_has_basis_label():
    """`eta(OCR) 4.2 min` so the operator knows the ETA is OCR-driven,
    not meta-driven (meta finishes first; quoting its rate would zero
    out the ETA prematurely)."""
    line = render_pipeline_progress_line(
        n_targets=100,
        meta=Counter({"ok": 100}),
        bytes_st=Counter({"ok": 250}),
        text_st=Counter({"ok": 50}),
        rate_per_sec=0.55,
        eta_min=4.2,
        eta_basis="OCR",
        use_color=False,
    )
    assert "0.55 cases/s" in line
    assert "eta(OCR) 4.2 min" in line


def test_pipeline_progress_handles_zero_targets_with_question_mark():
    """Pre-launch / pre-CSV-resolution edge: render without crashing,
    show `?` for the unknown denominator and omit the percentage."""
    line = render_pipeline_progress_line(
        n_targets=0,
        meta=Counter(),
        bytes_st=Counter(),
        text_st=Counter(),
        use_color=False,
    )
    assert "meta 0/?" in line
    assert "%" not in line


def test_pipeline_progress_prefix_renders_inline_with_space():
    """The shard aggregate prefix (`[12:00:00 agg]`) must read as a
    natural opening, not pretend to be a stage. Joined to the body
    with a space, not the stage `·` separator."""
    line = render_pipeline_progress_line(
        n_targets=100,
        meta=Counter({"ok": 50}),
        bytes_st=Counter(),
        text_st=Counter(),
        prefix="[12:00:00 agg]",
        use_color=False,
    )
    assert "[12:00:00 agg] meta" in line
    # Sanity: NOT joined as `[12:00:00 agg] · meta`.
    assert "[12:00:00 agg] · meta" not in line
