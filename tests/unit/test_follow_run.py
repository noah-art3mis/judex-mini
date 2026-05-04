"""Unit tests for `scripts/follow_run.py` — the engine behind `judex acompanhar`.

Behavior-level coverage of:

- ``find_log_paths`` resolver (mono vs sharded vs empty).
- ``transform_lines`` line-prefixer (compact ``[X]`` form, drops the
  polluting per-shard progress lines + tail's separator headers).
- ``aggregate_state`` cluster roll-up across multiple shard state files.
- ``format_aggregate_line`` rendering of the synthesised cluster line.

The actual subprocess plumbing (``_run_sharded_multitail``, ``run_follow``
with ``execvp``) is excluded — testing it would require subprocess /
threading mocks more brittle than the wrapper they protect.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from scripts.follow_run import (
    aggregate_state,
    find_log_paths,
    format_aggregate_line,
    transform_lines,
)


# --- find_log_paths --------------------------------------------------------


def test_find_log_paths_sharded_returns_per_shard_driver_logs(tmp_path: Path) -> None:
    for letter in ("a", "b"):
        d = tmp_path / f"shard-{letter}"
        d.mkdir()
        (d / "driver.log").touch()

    paths = find_log_paths(tmp_path)

    assert {p.parent.name for p in paths} == {"shard-a", "shard-b"}
    assert all(p.name == "driver.log" for p in paths)


def test_find_log_paths_sorted_by_shard_letter(tmp_path: Path) -> None:
    """Tail interleaves output across files; alphabetic ordering keeps
    headers stable across calls so a re-run lines up with prior screenfuls."""
    for letter in ("c", "a", "b"):
        d = tmp_path / f"shard-{letter}"
        d.mkdir()
        (d / "driver.log").touch()

    paths = find_log_paths(tmp_path)

    assert [p.parent.name for p in paths] == ["shard-a", "shard-b", "shard-c"]


def test_find_log_paths_mono_picks_driver_log(tmp_path: Path) -> None:
    (tmp_path / "driver.log").touch()
    assert find_log_paths(tmp_path) == [tmp_path / "driver.log"]


def test_find_log_paths_mono_falls_back_to_launcher_log(tmp_path: Path) -> None:
    """Operator-redirected mono (``nohup ... >> launcher.log``) is the
    current convention — no internal driver.log gets written."""
    (tmp_path / "launcher.log").touch()
    assert find_log_paths(tmp_path) == [tmp_path / "launcher.log"]


def test_find_log_paths_prefers_driver_log_over_launcher_log(tmp_path: Path) -> None:
    (tmp_path / "driver.log").touch()
    (tmp_path / "launcher.log").touch()
    assert find_log_paths(tmp_path) == [tmp_path / "driver.log"]


def test_find_log_paths_prefers_sharded_when_both_layouts_present(tmp_path: Path) -> None:
    """A stale ``launcher.log`` from a prior mono run + a current
    sharded layout: sharded wins because that's where live shards write."""
    (tmp_path / "launcher.log").touch()
    (tmp_path / "shard-a").mkdir()
    (tmp_path / "shard-a" / "driver.log").touch()

    paths = find_log_paths(tmp_path)

    assert [p.parent.name for p in paths] == ["shard-a"]


def test_find_log_paths_returns_empty_when_no_logs(tmp_path: Path) -> None:
    assert find_log_paths(tmp_path) == []


# --- transform_lines -------------------------------------------------------


def test_transform_lines_prefixes_data_lines_with_shard_letter() -> None:
    """``==> .../shard-X/driver.log <==`` headers act as state markers;
    every data line until the next header carries ``[X]``."""
    raw = [
        "==> /run/shard-a/driver.log <==",
        "09:01:02  ✓ ok        [portal  ]  HC 100",
        "09:01:03  ✓ ok        [sistemas]  HC 100 abc1234",
        "==> /run/shard-b/driver.log <==",
        "09:01:04  ✓ ok        [portal  ]  HC 99",
    ]
    out = list(transform_lines(raw))
    assert out == [
        "[a] 09:01:02  ✓ ok        [portal  ]  HC 100",
        "[a] 09:01:03  ✓ ok        [sistemas]  HC 100 abc1234",
        "[b] 09:01:04  ✓ ok        [portal  ]  HC 99",
    ]


def test_transform_lines_drops_per_shard_progress_lines() -> None:
    """The polluting ``─── 571/571 (100%) · ... ───`` lines disappear;
    the cluster aggregator's single line owns this slot now. Without
    this filter, a 16-shard run prints 16 of these every interval."""
    raw = [
        "==> /run/shard-a/driver.log <==",
        "─── 571/571 (100.0%) · meta_ok=571 · 0.55 cases/s · eta 0.0 min ───",
        "09:01:02  ✓ ok  [portal  ]  HC 100",
    ]
    out = list(transform_lines(raw))
    assert out == ["[a] 09:01:02  ✓ ok  [portal  ]  HC 100"]


def test_transform_lines_drops_blank_lines() -> None:
    """``tail -F`` emits blank lines between header switches; they're
    visual noise once we've replaced the headers with ``[X]`` prefixes."""
    raw = ["==> /run/shard-a/driver.log <==", "", "09:01:02  hi"]
    out = list(transform_lines(raw))
    assert out == ["[a] 09:01:02  hi"]


def test_transform_lines_handles_missing_initial_header() -> None:
    """If a data line arrives before any header (rare race in tail's
    first ms), prefix with ``?`` rather than crash. Caller will get
    a useful prefix on the next header."""
    raw = ["09:01:02  pre-header line", "==> /run/shard-a/driver.log <==", "after"]
    out = list(transform_lines(raw))
    assert out == ["[?] 09:01:02  pre-header line", "[a] after"]


# --- aggregate_state -------------------------------------------------------


def _make_state(cases: dict[str, dict]) -> dict:
    return {"schema_version": 2, "started_at": "2026-05-03T00:00:00+00:00",
            "snapshot_at": "2026-05-03T01:00:00+00:00", "cases": cases}


def _case(meta: str, peca_urls: dict[str, str] | None = None,
          text_urls: dict[str, str] | None = None,
          n_pecas: int | None = None) -> dict:
    fetch_meta: dict = {"status": meta, "ts": "2026-05-03T00:00:00+00:00"}
    if n_pecas is not None:
        fetch_meta["n_pecas"] = n_pecas
    return {
        "fetch_meta": fetch_meta,
        "fetch_bytes": {u: {"status": s} for u, s in (peca_urls or {}).items()},
        "extract_text": {u: {"status": s} for u, s in (text_urls or {}).items()},
    }


def test_aggregate_state_rolls_up_three_stages_across_shards(tmp_path: Path) -> None:
    """One number per stage-status across N shards, replacing N noisy
    per-shard lines."""
    sa = tmp_path / "shard-a"; sa.mkdir()
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-100": _case("ok", {"u1": "ok", "u2": "empty"}, {"u1": "ok"}, n_pecas=2),
        "HC-99": _case("unallocated_pid"),
    })))
    sb = tmp_path / "shard-b"; sb.mkdir()
    (sb / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-50": _case("ok", {"u3": "ok"}, {"u3": "provider_error"}, n_pecas=1),
    })))

    agg = aggregate_state(tmp_path)

    assert agg["processos"] == Counter({"ok": 2, "unallocated_pid": 1})
    assert agg["pecas"] == Counter({"ok": 2, "empty": 1})
    assert agg["text"] == Counter({"ok": 1, "provider_error": 1})


def test_aggregate_state_sums_pecas_total_across_shards(tmp_path: Path) -> None:
    """`pecas_total` is the cluster-wide denominator the operator
    needs once meta finishes — answers 'how many peca downloads
    are we expected to do?'. Sums n_pecas across every shard's
    meta=ok records."""
    sa = tmp_path / "shard-a"; sa.mkdir()
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-100": _case("ok", n_pecas=3),
        "HC-99": _case("ok", n_pecas=5),
    })))
    sb = tmp_path / "shard-b"; sb.mkdir()
    (sb / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-50": _case("ok", n_pecas=2),
        "HC-49": _case("unallocated_pid"),  # zero successors, not in total
    })))

    agg = aggregate_state(tmp_path)

    assert agg["pecas_total"] == 10  # 3 + 5 + 2


def test_aggregate_state_returns_none_pecas_total_for_legacy_shard(
    tmp_path: Path,
) -> None:
    """A legacy shard whose meta records lack n_pecas means we can't
    report a cluster-wide total without misleading. Renderer falls
    back to count-only for pecas — text still gets a ratio (derived
    from pecas['ok'])."""
    sa = tmp_path / "shard-a"; sa.mkdir()
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-100": _case("ok", n_pecas=3),  # new
    })))
    sb = tmp_path / "shard-b"; sb.mkdir()
    (sb / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-50": _case("ok"),  # legacy: no n_pecas
    })))

    agg = aggregate_state(tmp_path)

    assert agg["pecas_total"] is None


def test_aggregate_state_text_total_equals_pecas_ok_across_shards(
    tmp_path: Path,
) -> None:
    """text_total = pecas['ok'] (every successful pecas emits exactly
    one text successor). Computed at any moment; doesn't depend on
    n_pecas, so it works for legacy runs too."""
    sa = tmp_path / "shard-a"; sa.mkdir()
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-100": _case("ok", {"u1": "ok", "u2": "ok", "u3": "empty"}),
    })))
    sb = tmp_path / "shard-b"; sb.mkdir()
    (sb / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-50": _case("ok", {"u4": "ok"}),
    })))

    agg = aggregate_state(tmp_path)

    assert agg["text_total"] == 3  # 2 pecas-ok in shard-a + 1 in shard-b


def test_aggregate_state_returns_empty_when_no_state_files(tmp_path: Path) -> None:
    """Pre-launch (or right after launch, before first snapshot): the
    aggregator suppresses the line entirely instead of printing all
    zeros — pure noise."""
    assert aggregate_state(tmp_path) == {}


def test_aggregate_state_tolerates_corrupt_state_file(tmp_path: Path) -> None:
    """A shard mid-write may show as truncated JSON for a few ms.
    Skip the bad file; don't crash the whole acompanhar session."""
    sa = tmp_path / "shard-a"; sa.mkdir()
    (sa / "executar.state.json").write_text("{this is not json")
    sb = tmp_path / "shard-b"; sb.mkdir()
    (sb / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-50": _case("ok"),
    })))

    agg = aggregate_state(tmp_path)

    assert agg["processos"] == Counter({"ok": 1})


# --- format_aggregate_line -------------------------------------------------


def test_format_aggregate_line_shows_all_three_stages_with_counts() -> None:
    """Errors must be visible: ``provider_error=11`` cannot get
    suppressed at zero or folded into a generic ``fail`` bucket."""
    agg = {
        "processos": Counter({"ok": 500, "unallocated_pid": 70}),
        "pecas": Counter({"ok": 1500, "empty": 50}),
        "text": Counter({"ok": 600, "skipped_cached": 489, "provider_error": 11}),
        "pecas_total": None,
        "text_total": 1500,
    }
    line = format_aggregate_line(agg, n_targets=571, now=datetime(2026, 5, 3, 12, 0, 0))

    assert "[12:00:00 agg]" in line
    assert "processos 570/571" in line
    assert "ok=500" in line
    assert "unallocated_pid=70" in line
    assert "pecas" in line and "ok=1500" in line and "empty=50" in line
    assert "text" in line
    assert "provider_error=11" in line
    assert line.startswith("───") and line.endswith("───")


def test_format_aggregate_line_renders_pecas_ratio_when_total_known() -> None:
    """The deepening this commit ships: once n_pecas is recorded on
    meta, the aggregator surfaces a pecas denominator. Operator can
    finally read 'how many pecas downloads are left' at a glance."""
    agg = {
        "processos": Counter({"ok": 9137}),
        "pecas": Counter({"ok": 24337, "empty": 826, "http_error": 1}),
        "text": Counter({"ok": 12312}),
        "pecas_total": 28000,
        "text_total": 24337,
    }
    line = format_aggregate_line(agg, n_targets=9137)

    assert "pecas 25164/28000" in line
    assert "text 12312/24337" in line


def test_format_aggregate_line_drops_pecas_ratio_for_legacy(tmp_path: Path) -> None:
    """If pecas_total is None (legacy shard, mixed-version cluster),
    render count-only for pecas. text still shows a ratio because
    text_total = pecas['ok'] doesn't depend on the new field."""
    agg = {
        "processos": Counter({"ok": 9137}),
        "pecas": Counter({"ok": 24337, "empty": 826}),
        "text": Counter({"ok": 12312}),
        "pecas_total": None,
        "text_total": 24337,
    }
    line = format_aggregate_line(agg, n_targets=9137)

    # No pecas ratio:
    assert "pecas 25163/" not in line
    # text ratio still rendered:
    assert "text 12312/24337" in line


def test_format_aggregate_line_handles_zero_targets() -> None:
    """Pre-CSV-resolution edge: shards CSVs not present yet. Render
    without crashing; show ``?`` for the processos denominator."""
    agg = {
        "processos": Counter(),
        "pecas": Counter(),
        "text": Counter(),
        "pecas_total": None,
        "text_total": 0,
    }
    line = format_aggregate_line(agg, n_targets=0)

    assert "processos 0/?" in line
    assert "%" not in line


# --- run_follow auto-encerramento (default --until-done) ------------------


import pytest


def _seed_done_shard(shard_dir: Path, *, wall: float = 100.0) -> None:
    shard_dir.mkdir(parents=True, exist_ok=True)
    (shard_dir / "driver.log").write_text(
        f"executar: done. wall={wall}s · "
        f"report={shard_dir}/report.md · "
        f"errors={shard_dir}/executar.errors.jsonl\n"
    )
    (shard_dir / "executar.state.json").write_text(
        json.dumps({
            "schema_version": 2,
            "started_at": "2026-05-03T00:00:00+00:00",
            "snapshot_at": "2026-05-03T01:00:00+00:00",
            "cases": {},
        })
    )
    (shard_dir / "report.md").write_text(
        "# Unified pipeline run\n"
        "| OCR cost (USD, provedor=`auto`) | $0.0000 | $0.0000 |\n"
    )


@pytest.mark.timeout(10)
def test_run_follow_sharded_exits_when_all_shards_done(tmp_path: Path,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    """Default contract: every shard's driver.log has at least one
    ``executar: done`` line → run_follow returns 0 within one
    aggregator tick. Without auto-exit the test would block on tail
    -F forever and pytest-timeout would kill it after 10 s."""
    from scripts.follow_run import run_follow

    for letter in ("a", "b"):
        _seed_done_shard(tmp_path / f"shard-{letter}")

    rc = run_follow(tmp_path, n=5, agg_interval=0.1, persistir=False)

    assert rc == 0
    out = capsys.readouterr().out
    # The final summary block lands in stdout after the multitail drains.
    assert "DONE" in out
    assert "2/2 shards" in out


@pytest.mark.timeout(10)
def test_run_follow_mono_exits_when_done_line_present(tmp_path: Path,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    """Mono runs get the same auto-encerramento now that ``execvp`` was
    dropped — single driver.log, single anchor. End-detection works
    on both layouts so operators don't need to think about which mode
    a sweep used."""
    from scripts.follow_run import run_follow

    (tmp_path / "driver.log").write_text(
        f"executar: done. wall=42.0s · report={tmp_path}/report.md · "
        f"errors={tmp_path}/executar.errors.jsonl\n"
    )
    (tmp_path / "executar.state.json").write_text(
        json.dumps({
            "schema_version": 2,
            "started_at": "2026-05-03T00:00:00+00:00",
            "snapshot_at": "2026-05-03T01:00:00+00:00",
            "cases": {},
        })
    )

    rc = run_follow(tmp_path, n=5, agg_interval=0.1, persistir=False)

    assert rc == 0
    out = capsys.readouterr().out
    assert "DONE" in out
    assert "1/1 shard" in out  # singular for mono


@pytest.mark.timeout(10)
def test_run_follow_persistir_keeps_loop_alive_past_done(tmp_path: Path) -> None:
    """``--persistir`` opts out of auto-encerramento. A done-flagged dir
    should NOT cause an immediate return; the loop should keep tailing
    until externally interrupted. We start it in a thread, sleep past
    one aggregator interval, verify it's still running, then send a
    KeyboardInterrupt-equivalent via terminating the tail subprocess
    (the cleanest way to break the loop without SIGINT plumbing).

    This pins the contract that ``persistir=True`` makes
    ``is_run_done`` an unreachable branch — without that, the legacy
    "watch through to the next manual re-run" workflow would silently
    break."""
    import threading
    import time

    from scripts.follow_run import run_follow

    _seed_done_shard(tmp_path / "shard-a")

    result: list[int] = []

    def runner() -> None:
        result.append(run_follow(
            tmp_path, n=5, agg_interval=0.1, persistir=True,
        ))

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    time.sleep(0.5)  # > 4× the agg_interval; if persistir was honoured the
                    # auto-exit didn't fire.

    # If persistir is being honoured, the thread is still running.
    assert t.is_alive(), "persistir=True did not prevent auto-exit"

    # Don't wait for natural termination (would block forever) — the
    # test harness reaps the daemon thread when the test process exits.
    # If pytest-timeout fires, the assertion above already failed.
