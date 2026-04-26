"""Unit tests for ``scripts.analyze_regimes`` — the post-hoc CLI tool that
replaces hand-rolled jq queries over ``sweep.log.jsonl`` /
``pdfs.log.jsonl``.

Goal: pin the parser + transition-detector behavior on synthetic JSONL
fixtures so display-layer changes don't silently break the analysis.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.analyze_regimes import (
    RegimeEvent,
    cliff_first_seen,
    detect_log_kind,
    iter_regime_events,
    only_transitions,
    summarize,
)


def _write_log(p: Path, rows: list[dict]) -> None:
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


# ----- iter_regime_events ---------------------------------------------------


def test_iter_yields_events_for_case_sweep_log(tmp_path: Path) -> None:
    log = tmp_path / "sweep.log.jsonl"
    _write_log(log, [
        {"ts": "2026-04-25T22:14:33", "classe": "HC", "processo": 211144,
         "regime": "under_utilising", "regime_fail_rate": 0.0,
         "regime_p95_wall_s": 1.0, "regime_promoted_by": "default"},
        {"ts": "2026-04-25T22:14:34", "classe": "HC", "processo": 211145,
         "regime": "approaching_collapse", "regime_fail_rate": 0.22,
         "regime_p95_wall_s": 31.4, "regime_promoted_by": "axis_b"},
    ])
    events = list(iter_regime_events(log))
    assert len(events) == 2
    assert events[0].key == "HC_211144"
    assert events[0].regime == "under_utilising"
    assert events[1].promoted_by == "axis_b"
    assert events[1].p95_wall_s == 31.4


def test_iter_yields_events_for_pdf_sweep_log(tmp_path: Path) -> None:
    log = tmp_path / "pdfs.log.jsonl"
    _write_log(log, [
        {"ts": "2026-04-25T22:14:33", "url": "https://x.test/a.pdf",
         "regime": "under_utilising", "regime_fail_rate": 0.0,
         "regime_p95_wall_s": 1.0, "regime_promoted_by": "default"},
    ])
    events = list(iter_regime_events(log))
    assert events[0].key == "https://x.test/a.pdf"


def test_iter_skips_records_without_regime(tmp_path: Path) -> None:
    """Cache-hit rows in pdfs.log.jsonl carry regime=None — they didn't
    measure WAF and have no diagnostic to report.
    """
    log = tmp_path / "pdfs.log.jsonl"
    _write_log(log, [
        {"ts": "2026-04-25T22:14:33", "url": "https://x.test/a.pdf",
         "status": "cached", "regime": None},
        {"ts": "2026-04-25T22:14:34", "url": "https://x.test/b.pdf",
         "regime": "under_utilising", "regime_fail_rate": 0.0,
         "regime_p95_wall_s": 1.0, "regime_promoted_by": "default"},
    ])
    events = list(iter_regime_events(log))
    assert len(events) == 1
    assert events[0].key == "https://x.test/b.pdf"


def test_iter_tolerates_malformed_lines(tmp_path: Path) -> None:
    """Real-world logs have occasional truncated tail lines (a process
    killed mid-flush). The parser must skip them, not crash."""
    log = tmp_path / "sweep.log.jsonl"
    log.write_text(
        json.dumps({
            "ts": "2026-04-25T22:14:33", "classe": "HC", "processo": 1,
            "regime": "under_utilising", "regime_fail_rate": 0.0,
            "regime_p95_wall_s": 1.0, "regime_promoted_by": "default",
        }) + "\n"
        '{"ts": "broken JSON, no closing brace\n'
    )
    events = list(iter_regime_events(log))
    assert len(events) == 1


# ----- only_transitions -----------------------------------------------------


def test_only_transitions_yields_first_event_per_run() -> None:
    events = [
        RegimeEvent("t0", "k0", "warming", 0.0, 0.0, "warming"),
        RegimeEvent("t1", "k1", "warming", 0.0, 0.0, "warming"),
        RegimeEvent("t2", "k2", "under_utilising", 0.0, 1.0, "default"),
        RegimeEvent("t3", "k3", "under_utilising", 0.0, 1.0, "default"),
        RegimeEvent("t4", "k4", "l2_engaged", 0.12, 1.0, "axis_a"),
        RegimeEvent("t5", "k5", "l2_engaged", 0.12, 1.0, "axis_a"),
        RegimeEvent("t6", "k6", "approaching_collapse", 0.22, 31.4, "axis_b"),
    ]
    transitions = list(only_transitions(events))
    assert [e.regime for e in transitions] == [
        "warming", "under_utilising", "l2_engaged", "approaching_collapse",
    ]
    assert [e.key for e in transitions] == ["k0", "k2", "k4", "k6"]


def test_only_transitions_handles_oscillation() -> None:
    """A regime that toggles back-and-forth must produce one transition
    event for each toggle, not be deduplicated to one entry per label."""
    events = [
        RegimeEvent("t0", "k0", "under_utilising", 0.0, 1.0, "default"),
        RegimeEvent("t1", "k1", "l2_engaged", 0.12, 1.0, "axis_a"),
        RegimeEvent("t2", "k2", "under_utilising", 0.04, 1.0, "default"),
        RegimeEvent("t3", "k3", "l2_engaged", 0.12, 1.0, "axis_a"),
    ]
    transitions = list(only_transitions(events))
    assert len(transitions) == 4


# ----- cliff_first_seen -----------------------------------------------------


def test_cliff_first_seen_returns_first_event_per_severe_band() -> None:
    """`cliff_first_seen` highlights the first occurrence of each regime
    band at or above ``l2_engaged`` — the operationally interesting set."""
    events = [
        RegimeEvent("t0", "k0", "under_utilising", 0.0, 1.0, "default"),
        RegimeEvent("t1", "k1", "l2_engaged", 0.12, 1.0, "axis_a"),
        RegimeEvent("t2", "k2", "l2_engaged", 0.13, 1.0, "axis_a"),
        RegimeEvent("t3", "k3", "approaching_collapse", 0.22, 31.4, "axis_b"),
        RegimeEvent("t4", "k4", "collapse", 0.40, 62.0, "both"),
    ]
    seen = cliff_first_seen(events)
    assert seen["l2_engaged"].key == "k1"
    assert seen["approaching_collapse"].key == "k3"
    assert seen["collapse"].key == "k4"
    # Only severe bands are surfaced; healthy / under_utilising / warming are not.
    assert "under_utilising" not in seen
    assert "warming" not in seen


def test_cliff_first_seen_empty_when_no_severe_bands_hit() -> None:
    events = [
        RegimeEvent("t0", "k0", "under_utilising", 0.0, 1.0, "default"),
        RegimeEvent("t1", "k1", "healthy", 0.06, 1.0, "axis_a"),
    ]
    assert cliff_first_seen(events) == {}


# ----- summarize ------------------------------------------------------------


def test_summarize_counts_by_regime() -> None:
    events = [
        RegimeEvent("t0", "k0", "under_utilising", 0.0, 1.0, "default"),
        RegimeEvent("t1", "k1", "under_utilising", 0.0, 1.0, "default"),
        RegimeEvent("t2", "k2", "l2_engaged", 0.12, 1.0, "axis_a"),
    ]
    summary = summarize(events)
    assert summary["total"] == 3
    assert summary["by_regime"] == {"under_utilising": 2, "l2_engaged": 1}
    assert summary["by_promoter"] == {"default": 2, "axis_a": 1}


# ----- detect_log_kind ------------------------------------------------------


def test_detect_log_kind_case_sweep(tmp_path: Path) -> None:
    (tmp_path / "sweep.log.jsonl").write_text("")
    assert detect_log_kind(tmp_path) == ("case", tmp_path / "sweep.log.jsonl")


def test_detect_log_kind_pdf_sweep(tmp_path: Path) -> None:
    (tmp_path / "pdfs.log.jsonl").write_text("")
    assert detect_log_kind(tmp_path) == ("pdf", tmp_path / "pdfs.log.jsonl")


def test_detect_log_kind_prefers_case_when_both_present(tmp_path: Path) -> None:
    """A run dir that somehow holds both logs: prefer the case-sweep log
    (the WAF-hot one is what an operator usually wants to inspect)."""
    (tmp_path / "sweep.log.jsonl").write_text("")
    (tmp_path / "pdfs.log.jsonl").write_text("")
    assert detect_log_kind(tmp_path) == ("case", tmp_path / "sweep.log.jsonl")


def test_detect_log_kind_raises_when_no_log(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        detect_log_kind(tmp_path)
