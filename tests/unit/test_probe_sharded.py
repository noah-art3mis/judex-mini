"""Unit tests for `scripts/probe_sharded.py`.

Behavior-level coverage of the pure probe() data collector + the
`judex probe` CLI plumbing. Rendering is excluded — rich output is
visual; regressions there are caught by eye, not by asserts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from judex.cli import app
from scripts.probe_sharded import probe, probe_shard


def _write_state(shard_dir: Path, records: list[dict]) -> None:
    shard_dir.mkdir(parents=True, exist_ok=True)
    state = {f"{r['classe']}_{r['processo']}": r for r in records}
    (shard_dir / "sweep.state.json").write_text(json.dumps(state))


def _record(pid: int, *, status: str = "ok", regime: str = "under_utilising",
            ts: str = "2026-04-20T10:00:00+00:00") -> dict:
    return {
        "ts": ts, "classe": "HC", "processo": pid, "attempt": 1,
        "wall_s": 5.0, "status": status, "error": None,
        "regime": regime,
    }


def test_probe_shard_counts_records_and_regimes(tmp_path: Path) -> None:
    shard = tmp_path / "shard-a"
    _write_state(shard, [
        _record(100, regime="warming"),
        _record(99, regime="under_utilising"),
        _record(98, regime="under_utilising"),
        _record(97, status="fail", regime="under_utilising"),
    ])

    st = probe_shard(shard, tmp_path)

    assert st.name == "shard-a"
    assert st.records == 4
    assert st.statuses["ok"] == 3
    assert st.statuses["fail"] == 1
    assert st.regimes["warming"] == 1
    assert st.regimes["under_utilising"] == 3
    assert st.min_processo == 97


def test_probe_shard_handles_missing_state_file(tmp_path: Path) -> None:
    """A shard with no sweep.state.json yet (just-launched) must not crash."""
    shard = tmp_path / "shard-a"
    shard.mkdir()

    st = probe_shard(shard, tmp_path)

    assert st.records == 0
    assert st.statuses == {}
    assert st.min_processo is None


def test_probe_shard_reads_target_from_shard_csv(tmp_path: Path) -> None:
    """When <out-root>/shards/*.shard.N.csv exists, target = row count."""
    shard = tmp_path / "shard-a"
    shard.mkdir()
    shards_dir = tmp_path / "shards"
    shards_dir.mkdir()
    # shard letter a → index 0
    (shards_dir / "foo.shard.0.csv").write_text(
        "classe,processo\nHC,100\nHC,99\nHC,98\n"
    )

    st = probe_shard(shard, tmp_path)

    assert st.target == 3


def test_probe_unions_across_shards(tmp_path: Path) -> None:
    _write_state(tmp_path / "shard-a", [_record(100), _record(99)])
    _write_state(tmp_path / "shard-b", [_record(50)])
    _write_state(tmp_path / "shard-c", [])  # empty state

    stats = probe(tmp_path)

    names = [s.name for s in stats]
    assert names == ["shard-a", "shard-b", "shard-c"]
    totals = {s.name: s.records for s in stats}
    assert totals == {"shard-a": 2, "shard-b": 1, "shard-c": 0}


def test_probe_computes_earliest_and_latest_ts(tmp_path: Path) -> None:
    """earliest_ts / latest_ts drive throughput + ETA — must be correct."""
    shard = tmp_path / "shard-a"
    _write_state(shard, [
        _record(100, ts="2026-04-20T10:00:00+00:00"),
        _record(99, ts="2026-04-20T10:01:30+00:00"),
        _record(98, ts="2026-04-20T10:00:45+00:00"),
    ])

    st = probe_shard(shard, tmp_path)

    assert st.earliest_ts == datetime(2026, 4, 20, 10, 0, 0, tzinfo=timezone.utc)
    assert st.latest_ts == datetime(2026, 4, 20, 10, 1, 30, tzinfo=timezone.utc)


def test_cli_probe_runs_once_and_prints_shard_name(tmp_path: Path) -> None:
    """`judex probe --out-root X` must invoke the underlying script and
    render every shard present in the output."""
    _write_state(tmp_path / "shard-a", [_record(100), _record(99)])
    _write_state(tmp_path / "shard-b", [_record(50)])

    result = CliRunner().invoke(app, ["probe", "--out-root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "shard-a" in result.output
    assert "shard-b" in result.output
    assert "TOTAL" in result.output


def test_cli_probe_errors_when_no_shards(tmp_path: Path) -> None:
    """An out-root with no shard-* subdirs must exit non-zero with a
    clear error — protects against silent misuse (typo in path, etc)."""
    empty = tmp_path / "empty"
    empty.mkdir()

    result = CliRunner().invoke(app, ["probe", "--out-root", str(empty)])

    assert result.exit_code != 0
    assert "no shard-*" in result.output
