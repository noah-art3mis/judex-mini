"""Tests for scripts.shard_csv — interleave (default) vs range partitioning.

The interleave default exists to defeat load skew when the input CSV is
sorted by a dimension correlated with workload (e.g., pid ascending +
fresh-vs-cached URL mix). Range is retained as an opt-in for cases
where pid locality matters.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.shard_csv import shard_csv


def _write_csv(path: Path, rows: list[tuple[str, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["classe", "processo"])
        for classe, pid in rows:
            w.writerow([classe, pid])


def _read_shard(path: Path) -> list[tuple[str, int]]:
    with path.open(newline="") as f:
        reader = csv.reader(f)
        next(reader)  # header
        return [(c, int(p)) for c, p in reader]


# ---------------------------------------------------------------------------
# Invariants that must hold for every strategy


@pytest.mark.parametrize("strategy", ["interleave", "range"])
def test_union_equals_input(strategy: str, tmp_path: Path) -> None:
    """The union of all shards must equal the input (header excluded)."""
    rows = [("HC", i) for i in range(100)]
    csv_path = tmp_path / "in.csv"
    _write_csv(csv_path, rows)

    out_dir = tmp_path / "out"
    paths = shard_csv(csv_path, shards=4, out_dir=out_dir, strategy=strategy)

    all_rows: list[tuple[str, int]] = []
    for p in paths:
        all_rows.extend(_read_shard(p))
    assert sorted(all_rows) == sorted(rows)


@pytest.mark.parametrize("strategy", ["interleave", "range"])
def test_shards_disjoint(strategy: str, tmp_path: Path) -> None:
    """No row appears in more than one shard."""
    rows = [("HC", i) for i in range(50)]
    csv_path = tmp_path / "in.csv"
    _write_csv(csv_path, rows)

    paths = shard_csv(csv_path, shards=8, out_dir=tmp_path / "out", strategy=strategy)

    seen: set[tuple[str, int]] = set()
    for p in paths:
        for r in _read_shard(p):
            assert r not in seen, f"row {r} duplicated across shards"
            seen.add(r)


@pytest.mark.parametrize("strategy", ["interleave", "range"])
def test_produces_exactly_n_files(strategy: str, tmp_path: Path) -> None:
    rows = [("HC", i) for i in range(30)]
    csv_path = tmp_path / "in.csv"
    _write_csv(csv_path, rows)

    paths = shard_csv(csv_path, shards=5, out_dir=tmp_path / "out", strategy=strategy)
    assert len(paths) == 5


@pytest.mark.parametrize("strategy", ["interleave", "range"])
def test_header_replicated_in_each_shard(strategy: str, tmp_path: Path) -> None:
    rows = [("HC", i) for i in range(20)]
    csv_path = tmp_path / "in.csv"
    _write_csv(csv_path, rows)

    paths = shard_csv(csv_path, shards=4, out_dir=tmp_path / "out", strategy=strategy)
    for p in paths:
        with p.open(newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == ["classe", "processo"]


# ---------------------------------------------------------------------------
# Strategy-specific behavior


def test_range_produces_contiguous_slices(tmp_path: Path) -> None:
    """Range strategy keeps pids contiguous within a shard — the property
    the historical range default was built for."""
    rows = [("HC", i) for i in range(20)]
    csv_path = tmp_path / "in.csv"
    _write_csv(csv_path, rows)

    paths = shard_csv(csv_path, shards=4, out_dir=tmp_path / "out", strategy="range")
    # shard 0 → [0..4], shard 1 → [5..9], etc.
    pids_by_shard = [[pid for _, pid in _read_shard(p)] for p in paths]
    assert pids_by_shard[0] == [0, 1, 2, 3, 4]
    assert pids_by_shard[1] == [5, 6, 7, 8, 9]
    assert pids_by_shard[2] == [10, 11, 12, 13, 14]
    assert pids_by_shard[3] == [15, 16, 17, 18, 19]


def test_interleave_round_robins_by_index(tmp_path: Path) -> None:
    """Interleave assigns row i to shard (i % N). Same row, same strategy,
    same shard — deterministic."""
    rows = [("HC", i) for i in range(20)]
    csv_path = tmp_path / "in.csv"
    _write_csv(csv_path, rows)

    paths = shard_csv(csv_path, shards=4, out_dir=tmp_path / "out", strategy="interleave")
    pids_by_shard = [[pid for _, pid in _read_shard(p)] for p in paths]
    assert pids_by_shard[0] == [0, 4, 8, 12, 16]
    assert pids_by_shard[1] == [1, 5, 9, 13, 17]
    assert pids_by_shard[2] == [2, 6, 10, 14, 18]
    assert pids_by_shard[3] == [3, 7, 11, 15, 19]


def test_default_strategy_is_interleave(tmp_path: Path) -> None:
    """Changing the default is the whole point — pin it so a future
    refactor doesn't silently flip it back."""
    rows = [("HC", i) for i in range(8)]
    csv_path = tmp_path / "in.csv"
    _write_csv(csv_path, rows)

    paths = shard_csv(csv_path, shards=4, out_dir=tmp_path / "out")  # no strategy kwarg
    pids_by_shard = [[pid for _, pid in _read_shard(p)] for p in paths]
    # Interleave: shard 0 gets rows 0, 4
    assert pids_by_shard[0] == [0, 4]


# ---------------------------------------------------------------------------
# The balance property that motivates the new default


def test_interleave_beats_range_on_correlated_workload(tmp_path: Path) -> None:
    """When the input is sorted by a workload dimension (e.g. fresh-then-cached),
    range concentrates fresh work in the first few shards. Interleave spreads
    it evenly. This is the skew that bit us in the 2026-04-19 PDF sweep.

    Model: rows 0..49 carry workload=1 (fresh downloads), rows 50..99 carry
    workload=0 (cache hits). Range puts all the work in shards 0-1;
    interleave spreads it across all shards.
    """
    rows = [("HC", i) for i in range(100)]
    csv_path = tmp_path / "in.csv"
    _write_csv(csv_path, rows)

    # "Workload" attached via pid: pid < 50 = 1 unit, else 0
    def workload(pid: int) -> int:
        return 1 if pid < 50 else 0

    def per_shard_workload(paths: list[Path]) -> list[int]:
        return [sum(workload(pid) for _, pid in _read_shard(p)) for p in paths]

    range_paths = shard_csv(csv_path, shards=4, out_dir=tmp_path / "range", strategy="range")
    interleave_paths = shard_csv(csv_path, shards=4, out_dir=tmp_path / "interleave", strategy="interleave")

    range_workloads = per_shard_workload(range_paths)
    interleave_workloads = per_shard_workload(interleave_paths)

    # Range concentrates: shards 0,1 get all 50 units; shards 2,3 get 0.
    assert max(range_workloads) - min(range_workloads) == 25  # 25 vs 0 extreme

    # Interleave balances: every shard gets ~12–13 units.
    assert max(interleave_workloads) - min(interleave_workloads) <= 1


def test_unknown_strategy_raises(tmp_path: Path) -> None:
    rows = [("HC", 1)]
    csv_path = tmp_path / "in.csv"
    _write_csv(csv_path, rows)
    with pytest.raises(ValueError, match="strategy"):
        shard_csv(csv_path, shards=2, out_dir=tmp_path / "out", strategy="random")  # type: ignore[arg-type]
