"""Unit tests for ``judex/sweeps/run_summary.py`` — the engine behind
``judex relatar`` and ``judex acompanhar --until-done``.

Coverage:

- ``is_run_done`` end-detection across mono and sharded layouts.
- ``summarize_run`` walker: counts cases, sums residuals across shards,
  classifies (kind, status) into recovery actions, parses wall + OCR
  cost from each shard's ``report.md``.
- Recovery-mapping coverage: every (kind, status) combination observed
  in real ``executar.errors.jsonl`` files is in ``STATUS_TO_RECOVERY``
  — pinned so a new failure mode can't slip through silently.
- ``render_summary`` produces operator-readable copy: DONE banner,
  RUNNING partial render, residual lines with copy-pasteable commands.
"""

from __future__ import annotations

import json
from pathlib import Path

from judex.sweeps.run_summary import (
    STATUS_TO_RECOVERY,
    RunState,
    is_run_done,
    render_summary,
    summarize_run,
)


# --- shared fixture helpers ------------------------------------------------


def _make_state(cases: dict[str, dict]) -> dict:
    return {
        "schema_version": 2,
        "started_at": "2026-05-03T09:00:00+00:00",
        "snapshot_at": "2026-05-03T13:00:00+00:00",
        "cases": cases,
    }


def _case(meta: str, *, peca_urls: dict[str, str] | None = None,
          text_urls: dict[str, str] | None = None,
          n_pecas: int | None = None) -> dict:
    fetch_meta: dict = {"status": meta, "ts": "2026-05-03T09:00:00+00:00"}
    if n_pecas is not None:
        fetch_meta["n_pecas"] = n_pecas
    return {
        "fetch_meta": fetch_meta,
        "fetch_bytes": {u: {"status": s} for u, s in (peca_urls or {}).items()},
        "extract_text": {u: {"status": s} for u, s in (text_urls or {}).items()},
    }


_DONE_TEMPLATE = (
    "executar: done. wall={wall}s · "
    "report={path}/report.md · errors={path}/executar.errors.jsonl\n"
)


def _write_done(driver_log: Path, *, wall: float = 100.0) -> None:
    """Append the canonical ``executar: done`` line a runner emits at exit."""
    driver_log.parent.mkdir(parents=True, exist_ok=True)
    driver_log.write_text(_DONE_TEMPLATE.format(wall=wall, path=driver_log.parent))


def _write_report(report_md: Path, *, cost_usd: float = 0.0) -> None:
    """Minimal ``report.md`` containing the OCR-cost row the parser keys on."""
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_md.write_text(
        "# Unified pipeline run\n"
        "\n"
        f"| OCR cost (USD, provedor=`auto`) | ${cost_usd:.4f} | ${cost_usd:.4f} |\n"
    )


def _write_error_row(errors_jsonl: Path, *, kind: str, status: str,
                     processo: int, url: str | None = None) -> None:
    """Append one row to a per-shard ``executar.errors.jsonl``."""
    errors_jsonl.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "kind": kind,
        "classe": "HC",
        "processo": processo,
        "status": status,
        "url": url,
        "doc_type": None,
        "extractor": None,
        "error": None,
    }
    with errors_jsonl.open("a") as f:
        f.write(json.dumps(row) + "\n")


def _make_finished_shard(shard_dir: Path, *, wall: float, cases: dict[str, dict],
                          cost_usd: float = 0.0) -> None:
    shard_dir.mkdir(parents=True, exist_ok=True)
    _write_done(shard_dir / "driver.log", wall=wall)
    _write_report(shard_dir / "report.md", cost_usd=cost_usd)
    (shard_dir / "executar.state.json").write_text(json.dumps(_make_state(cases)))


# --- is_run_done -----------------------------------------------------------


def test_is_run_done_sharded_all_shards_have_done_line(tmp_path: Path) -> None:
    """The contract ``acompanhar --until-done`` keys on: every shard's
    driver.log contains at least one ``executar: done`` line. Once that
    holds, the multitail can render the summary and exit."""
    for letter in ("a", "b"):
        _make_finished_shard(tmp_path / f"shard-{letter}", wall=100.0, cases={})

    assert is_run_done(tmp_path) == (True, 2, 2)


def test_is_run_done_sharded_partial_only_some_shards_done(tmp_path: Path) -> None:
    """Mid-run: some shards finished, others still working. Aggregator
    keeps tailing — no premature exit."""
    _make_finished_shard(tmp_path / "shard-a", wall=100.0, cases={})
    in_flight = tmp_path / "shard-b"; in_flight.mkdir()
    (in_flight / "driver.log").write_text("09:01:02 working...\n")

    assert is_run_done(tmp_path) == (False, 1, 2)


def test_is_run_done_sharded_re_resume_emits_two_done_lines(tmp_path: Path) -> None:
    """A shard that was re-resumed appends a SECOND ``executar: done``
    line (observed in real HC 2020 driver.logs). End-detection counts
    *shards with ≥1 done line*, not total done lines, so duplicates
    don't break the math."""
    sa = tmp_path / "shard-a"; sa.mkdir()
    (sa / "driver.log").write_text(
        _DONE_TEMPLATE.format(wall=5137.4, path=sa) +
        "executar: log newer than snapshot; recovering state from ...\n"
        "nothing to do (state already complete for every target)\n" +
        _DONE_TEMPLATE.format(wall=0.0, path=sa)
    )
    sb = tmp_path / "shard-b"; sb.mkdir()
    (sb / "driver.log").write_text(_DONE_TEMPLATE.format(wall=8000.0, path=sb))

    assert is_run_done(tmp_path) == (True, 2, 2)


def test_is_run_done_mono_with_done_line(tmp_path: Path) -> None:
    """Mono runs use the same ``executar: done`` anchor — single log,
    single check."""
    (tmp_path / "driver.log").write_text(_DONE_TEMPLATE.format(wall=42.0, path=tmp_path))

    assert is_run_done(tmp_path) == (True, 1, 1)


def test_is_run_done_mono_no_done_line_yet(tmp_path: Path) -> None:
    (tmp_path / "driver.log").write_text("09:01:02 still running...\n")

    assert is_run_done(tmp_path) == (False, 0, 1)


def test_is_run_done_mono_falls_back_to_launcher_log(tmp_path: Path) -> None:
    """``nohup ... > launcher.log`` mono runs (no internal driver.log)
    must still detect done. Same anchor, different file."""
    (tmp_path / "launcher.log").write_text(_DONE_TEMPLATE.format(wall=42.0, path=tmp_path))

    assert is_run_done(tmp_path) == (True, 1, 1)


def test_is_run_done_no_logs_means_not_done(tmp_path: Path) -> None:
    """Pre-launch dir or operator pointed at the wrong path: don't
    crash, just report not-done with zero shards."""
    assert is_run_done(tmp_path) == (False, 0, 0)


# --- summarize_run on a finished sharded run -------------------------------


def test_summarize_run_sharded_done_rolls_up_three_stages(tmp_path: Path) -> None:
    _make_finished_shard(tmp_path / "shard-a", wall=100.0, cases={
        "HC-100": _case("ok", peca_urls={"u1": "ok", "u2": "empty"},
                        text_urls={"u1": "ok"}, n_pecas=2),
        "HC-99":  _case("unallocated_pid"),
    })
    _make_finished_shard(tmp_path / "shard-b", wall=200.0, cases={
        "HC-50": _case("ok", peca_urls={"u3": "ok"},
                       text_urls={"u3": "provider_error"}, n_pecas=1),
    })

    s = summarize_run(tmp_path)

    assert s.state == RunState.DONE
    assert s.layout == "sharded"
    assert s.n_shards == 2
    assert s.n_done_shards == 2
    assert s.breakdown.processos == {"ok": 2, "unallocated_pid": 1}
    assert s.breakdown.pecas == {"ok": 2, "empty": 1}
    assert s.breakdown.text == {"ok": 1, "provider_error": 1}


def test_summarize_run_walls_pick_longest_and_total(tmp_path: Path) -> None:
    """Wall reporting answers two questions at once:
       longest = real wall-clock the operator waited;
       total   = sum-of-shards (a CPU-equivalent useful for cost math)."""
    _make_finished_shard(tmp_path / "shard-a", wall=100.0, cases={})
    _make_finished_shard(tmp_path / "shard-b", wall=300.0, cases={})
    _make_finished_shard(tmp_path / "shard-c", wall=200.0, cases={})

    s = summarize_run(tmp_path)

    assert s.longest_wall_s == 300.0
    assert s.total_wall_s == 600.0


def test_summarize_run_sums_ocr_cost_across_shards(tmp_path: Path) -> None:
    """Each shard's ``report.md`` carries one OCR-cost row; the run-wide
    cost is their sum. Parses the FIRST $-cell of the row (the 'this run'
    column, not the legacy comparison)."""
    _make_finished_shard(tmp_path / "shard-a", wall=100.0, cases={}, cost_usd=0.0125)
    _make_finished_shard(tmp_path / "shard-b", wall=100.0, cases={}, cost_usd=0.0211)

    s = summarize_run(tmp_path)

    assert abs(s.ocr_cost_usd - 0.0336) < 1e-6


def test_summarize_run_residuals_grouped_by_kind_and_status(tmp_path: Path) -> None:
    """The residuals list is the operator's primary output — it answers
    'what failed and what should I do about it?'. Grouping by
    (kind, status) collapses 600 individual error rows into a handful
    of actionable buckets, each with a copy-pasteable command."""
    sa = tmp_path / "shard-a"
    _make_finished_shard(sa, wall=100.0, cases={})
    for i in range(5):
        _write_error_row(sa / "executar.errors.jsonl",
                         kind="extract_text", status="provider_error",
                         processo=200 + i, url=f"https://x/{i}")
    _write_error_row(sa / "executar.errors.jsonl",
                     kind="fetch_bytes", status="empty", processo=205)

    sb = tmp_path / "shard-b"
    _make_finished_shard(sb, wall=100.0, cases={})
    for i in range(3):
        _write_error_row(sb / "executar.errors.jsonl",
                         kind="extract_text", status="provider_error",
                         processo=300 + i, url=f"https://y/{i}")
    _write_error_row(sb / "executar.errors.jsonl",
                     kind="fetch_meta", status="unallocated_pid", processo=399)

    s = summarize_run(tmp_path)

    by_kind_status = {(r.kind, r.status): r for r in s.residuals}
    assert by_kind_status[("extract_text", "provider_error")].count == 8
    assert by_kind_status[("fetch_bytes", "empty")].count == 1
    assert by_kind_status[("fetch_meta", "unallocated_pid")].count == 1


def test_summarize_run_terminal_residuals_marked_no_recovery(tmp_path: Path) -> None:
    """``unallocated_pid`` and ``empty`` are terminal STF gaps — no
    retry will ever change them. Operator needs to see them in the
    rollup (transparency) but the suggested-command field must be
    ``None`` so the renderer doesn't print a useless command."""
    sa = tmp_path / "shard-a"
    _make_finished_shard(sa, wall=100.0, cases={})
    _write_error_row(sa / "executar.errors.jsonl",
                     kind="fetch_meta", status="unallocated_pid", processo=1)
    _write_error_row(sa / "executar.errors.jsonl",
                     kind="fetch_bytes", status="empty", processo=2,
                     url="https://x/2")

    s = summarize_run(tmp_path)

    by_kind_status = {(r.kind, r.status): r for r in s.residuals}
    assert by_kind_status[("fetch_meta", "unallocated_pid")].suggested_command is None
    assert by_kind_status[("fetch_meta", "unallocated_pid")].is_terminal is True
    assert by_kind_status[("fetch_bytes", "empty")].is_terminal is True


def test_summarize_run_retryable_residuals_get_retentar_command(tmp_path: Path) -> None:
    """``provider_error`` (OCR) + ``http_error`` (transport) are the
    retryable classes. Their suggested command is the ``--retentar-de``
    re-run pointing at the per-shard errors file — copy-paste straight
    into the shell."""
    sa = tmp_path / "shard-a"
    _make_finished_shard(sa, wall=100.0, cases={})
    _write_error_row(sa / "executar.errors.jsonl",
                     kind="extract_text", status="provider_error", processo=1,
                     url="https://x/1")

    s = summarize_run(tmp_path)

    rec = next(r for r in s.residuals if (r.kind, r.status) == ("extract_text", "provider_error"))
    assert rec.is_terminal is False
    assert rec.suggested_command is not None
    # Must be runnable — references the errors file as the seed source.
    assert "--retentar-de" in rec.suggested_command
    assert "executar.errors.jsonl" in rec.suggested_command


# --- summarize_run on an in-flight sharded run -----------------------------


def test_summarize_run_in_flight_state_is_running(tmp_path: Path) -> None:
    """A live run has state.json snapshots but no ``executar: done`` lines.
    ``relatar`` should render a partial summary (state=RUNNING) with
    current counts but no residuals/next-steps (those would be wrong
    while the scheduler may still convert non-ok → ok)."""
    sa = tmp_path / "shard-a"; sa.mkdir()
    (sa / "driver.log").write_text("09:01:02 working...\n")
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-1": _case("ok", peca_urls={"u1": "ok"}, text_urls={"u1": "ok"}, n_pecas=1),
    })))
    sb = tmp_path / "shard-b"; sb.mkdir()
    (sb / "driver.log").write_text("09:01:02 working...\n")

    s = summarize_run(tmp_path)

    assert s.state == RunState.RUNNING
    assert s.n_done_shards == 0
    assert s.n_shards == 2
    assert s.breakdown.processos == {"ok": 1}


def test_summarize_run_partial_when_some_shards_silent(tmp_path: Path) -> None:
    """Mid-shard crash: PIDs dead, state file shows in-flight, no
    ``executar: done`` line. The rollup flags this so the operator
    knows to investigate before the next round of retries."""
    sa = tmp_path / "shard-a"; sa.mkdir()
    _write_done(sa / "driver.log", wall=100.0)
    sb = tmp_path / "shard-b"; sb.mkdir()
    (sb / "driver.log").write_text("09:01:02 was running...\n")

    s = summarize_run(tmp_path)

    assert s.state == RunState.RUNNING  # not yet DONE since b never finished
    assert s.n_done_shards == 1


# --- summarize_run on mono ------------------------------------------------


def test_summarize_run_mono_done(tmp_path: Path) -> None:
    """Mono = single log + state file at top level. Walker handles both
    layouts — operator can run ``judex relatar`` without thinking about
    which mode the run used."""
    _write_done(tmp_path / "driver.log", wall=42.0)
    _write_report(tmp_path / "report.md", cost_usd=0.005)
    (tmp_path / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-1": _case("ok", peca_urls={"u": "ok"}, text_urls={"u": "ok"}, n_pecas=1),
    })))

    s = summarize_run(tmp_path)

    assert s.layout == "mono"
    assert s.n_shards == 1
    assert s.state == RunState.DONE
    assert s.longest_wall_s == 42.0
    assert s.total_wall_s == 42.0
    assert abs(s.ocr_cost_usd - 0.005) < 1e-6


# --- recovery-mapping coverage --------------------------------------------


def test_recovery_mapping_covers_every_observed_status() -> None:
    """Pinned to the (kind, status) pairs surfaced by real HC sweeps as
    of 2026-05-03 — see ``runs/active/hc2020-sharded/shard-*/executar.errors.jsonl``.
    Adding a new failure mode = one row in ``STATUS_TO_RECOVERY`` + one
    row here. Without this test, a new status silently shows up in the
    rollup with empty recovery guidance."""
    observed_in_real_runs = {
        ("fetch_meta", "unallocated_pid"),
        ("fetch_meta", "http_error"),
        ("fetch_bytes", "empty"),
        ("fetch_bytes", "http_error"),
        ("extract_text", "provider_error"),
        ("extract_text", "outlier_skipped"),
    }

    missing = observed_in_real_runs - set(STATUS_TO_RECOVERY)

    assert not missing, f"unmapped (kind, status) pairs: {missing}"


def test_recovery_terminal_actions_have_no_template() -> None:
    """Invariant: ``is_terminal`` and ``template`` are mutually exclusive.
    A terminal action by definition has no recovery command; a
    retryable one must have one."""
    for key, action in STATUS_TO_RECOVERY.items():
        if action.is_terminal:
            assert action.template is None, f"terminal action {key} has template"
        else:
            assert action.template is not None, f"retryable action {key} has no template"


# --- render_summary -------------------------------------------------------


def test_render_summary_done_state_shows_status_banner(tmp_path: Path) -> None:
    """The banner is the operator's first read: green/done at the top
    so they don't have to scan for it."""
    _make_finished_shard(tmp_path / "shard-a", wall=100.0, cases={
        "HC-1": _case("ok", peca_urls={"u": "ok"}, text_urls={"u": "ok"}, n_pecas=1),
    })

    out = render_summary(summarize_run(tmp_path))

    assert "DONE" in out
    assert "1/1 shards" in out


def test_render_summary_running_state_omits_next_steps(tmp_path: Path) -> None:
    """Mid-run: residuals are still in motion. The rendered output
    must not suggest commands that would mis-target tasks the scheduler
    is still working on."""
    sa = tmp_path / "shard-a"; sa.mkdir()
    (sa / "driver.log").write_text("09:01:02 working...\n")
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-1": _case("ok", peca_urls={"u": "ok"}, text_urls={"u": "ok"}, n_pecas=1),
    })))

    out = render_summary(summarize_run(tmp_path))

    assert "RUNNING" in out
    assert "Next steps" not in out
    assert "--retentar-de" not in out


def test_render_summary_residual_emits_copypastable_command(tmp_path: Path) -> None:
    """A retryable residual must surface the shell command verbatim.
    Operators copy-paste; they should not have to read templates and
    fill in placeholders."""
    sa = tmp_path / "shard-a"
    _make_finished_shard(sa, wall=100.0, cases={})
    _write_error_row(sa / "executar.errors.jsonl",
                     kind="extract_text", status="provider_error", processo=1,
                     url="https://x/1")

    out = render_summary(summarize_run(tmp_path))

    assert "Next steps" in out
    assert "--retentar-de" in out
    # Must reference the actual shard's errors file, not a placeholder.
    assert str(sa / "executar.errors.jsonl") in out


def test_render_summary_wall_renders_human_units_alongside_seconds(
    tmp_path: Path,
) -> None:
    """A wall of 13983s reads as '3h 53m' before it reads as raw
    seconds. Both forms render so operators can grep the seconds for
    extrapolation while still reading the hours at a glance."""
    _make_finished_shard(tmp_path / "shard-a", wall=13983.0, cases={})

    out = render_summary(summarize_run(tmp_path))

    assert "3h 53m" in out
    assert "13983s" in out


def test_render_summary_no_residuals_says_clean(tmp_path: Path) -> None:
    """A perfectly clean run: ``ok`` everywhere, no errors.jsonl rows.
    Rollup should say so explicitly so the operator doesn't search
    the page for residuals that don't exist."""
    _make_finished_shard(tmp_path / "shard-a", wall=100.0, cases={
        "HC-1": _case("ok", peca_urls={"u": "ok"}, text_urls={"u": "ok"}, n_pecas=1),
    })

    out = render_summary(summarize_run(tmp_path))

    assert "DONE" in out
    assert "no residuals" in out.lower() or "all clean" in out.lower()
