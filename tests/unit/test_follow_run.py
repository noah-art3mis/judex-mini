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


def _case(meta: str, bytes_urls: dict[str, str] | None = None,
          text_urls: dict[str, str] | None = None) -> dict:
    return {
        "fetch_meta": {"status": meta, "ts": "2026-05-03T00:00:00+00:00"},
        "fetch_bytes": {u: {"status": s} for u, s in (bytes_urls or {}).items()},
        "extract_text": {u: {"status": s} for u, s in (text_urls or {}).items()},
    }


def test_aggregate_state_rolls_up_three_stages_across_shards(tmp_path: Path) -> None:
    """The whole point of the synthetic aggregator: one number per
    stage-status across N shards, replacing N noisy per-shard lines."""
    sa = tmp_path / "shard-a"; sa.mkdir()
    (sa / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-100": _case("ok", {"u1": "ok", "u2": "empty"}, {"u1": "ok"}),
        "HC-99": _case("unallocated_pid"),
    })))
    sb = tmp_path / "shard-b"; sb.mkdir()
    (sb / "executar.state.json").write_text(json.dumps(_make_state({
        "HC-50": _case("ok", {"u3": "ok"}, {"u3": "provider_error"}),
    })))

    agg = aggregate_state(tmp_path)

    assert agg["meta"] == Counter({"ok": 2, "unallocated_pid": 1})
    assert agg["bytes"] == Counter({"ok": 2, "empty": 1})
    assert agg["text"] == Counter({"ok": 1, "provider_error": 1})


def test_aggregate_state_returns_empty_when_no_state_files(tmp_path: Path) -> None:
    """Pre-launch (or right after launch, before first snapshot): the
    aggregator suppresses the line entirely instead of printing
    ``meta 0/0 0 · bytes 0 · text 0`` — pure noise."""
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

    assert agg["meta"] == Counter({"ok": 1})


# --- format_aggregate_line -------------------------------------------------


def test_format_aggregate_line_shows_all_three_stages_with_counts() -> None:
    """The user's most explicit ask: errors visible. ``provider_error=11``
    must appear in the rendered line, not get suppressed at zero or
    folded into a generic ``fail`` bucket."""
    agg = {
        "meta": Counter({"ok": 500, "unallocated_pid": 70}),
        "bytes": Counter({"ok": 1500, "empty": 50}),
        "text": Counter({"ok": 600, "skipped_cached": 489, "provider_error": 11}),
    }
    line = format_aggregate_line(agg, n_targets=571, now=datetime(2026, 5, 3, 12, 0, 0))

    assert "[12:00:00 agg]" in line
    assert "meta 570/571" in line
    assert "ok=500" in line
    assert "unallocated_pid=70" in line
    assert "bytes" in line and "ok=1500" in line and "empty=50" in line
    assert "text" in line
    assert "provider_error=11" in line
    assert line.startswith("───") and line.endswith("───")


def test_format_aggregate_line_shows_meta_pct_only_not_bytes_text() -> None:
    """Bytes/text denominators grow with meta progress, so showing a
    percentage there would lie until meta is fully done. Only meta
    has a static, known denominator (``n_targets``)."""
    agg = {
        "meta": Counter({"ok": 500}),
        "bytes": Counter({"ok": 1500}),
        "text": Counter({"ok": 600}),
    }
    line = format_aggregate_line(agg, n_targets=1000)

    # meta has a percentage:
    assert "(50.0%)" in line
    # bytes/text don't — no other "(X.X%)" tokens than the meta one.
    assert line.count("%") == 1


def test_format_aggregate_line_orders_statuses_with_failures_last() -> None:
    """Eye should land on errors. Within a stage's ``(...)``, failure
    statuses sort after the success/cached/empty cluster so they're
    in the rightmost (last-read) position."""
    agg = {
        "meta": Counter(),
        "bytes": Counter(),
        "text": Counter({"provider_error": 5, "ok": 100}),
    }
    line = format_aggregate_line(agg, n_targets=0)

    ok_idx = line.index("ok=100")
    err_idx = line.index("provider_error=5")
    assert ok_idx < err_idx


def test_format_aggregate_line_handles_zero_targets() -> None:
    """Pre-CSV-resolution edge: shards CSVs not present yet. Render
    without crashing; show ``?`` for the denominator."""
    agg = {"meta": Counter(), "bytes": Counter(), "text": Counter()}
    line = format_aggregate_line(agg, n_targets=0)

    assert "meta 0/?" in line
    assert "%" not in line
