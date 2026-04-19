"""shard_launcher — sharded-launch primitive for judex baixar-pecas.

Covers:
- `discover_proxy_pools(dir, n)` picks N alphabetically-ordered proxy files;
  errors clearly when fewer than N exist.
- `launch_sharded_download` partitions the CSV, spawns one subprocess per
  shard with the right argv, and writes a shards.pids file. Spawning is
  injected so the test doesn't fork real processes.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from judex.sweeps.shard_launcher import (
    ProxyPoolShortage,
    discover_proxy_pools,
    launch_sharded_download,
)


def test_discover_proxy_pools_returns_n_sorted(tmp_path: Path) -> None:
    (tmp_path / "proxies.b.txt").write_text("b1\n")
    (tmp_path / "proxies.a.txt").write_text("a1\n")
    (tmp_path / "proxies.c.txt").write_text("c1\n")

    pools = discover_proxy_pools(tmp_path, 2)

    assert [p.name for p in pools] == ["proxies.a.txt", "proxies.b.txt"]


def test_discover_proxy_pools_ignores_non_proxy_files(tmp_path: Path) -> None:
    (tmp_path / "proxies.a.txt").write_text("a1\n")
    (tmp_path / "notes.txt").write_text("unrelated\n")
    (tmp_path / "proxies.reserve.txt").write_text("reserve\n")

    pools = discover_proxy_pools(tmp_path, 1)

    # Only files matching proxies.<letter>.txt count; proxies.reserve.txt
    # doesn't match the single-letter convention.
    assert [p.name for p in pools] == ["proxies.a.txt"]


def test_discover_proxy_pools_errors_when_fewer_than_n(tmp_path: Path) -> None:
    (tmp_path / "proxies.a.txt").write_text("a1\n")
    (tmp_path / "proxies.b.txt").write_text("b1\n")

    with pytest.raises(ProxyPoolShortage) as excinfo:
        discover_proxy_pools(tmp_path, 5)
    assert "2" in str(excinfo.value) and "5" in str(excinfo.value)


def test_launch_sharded_download_partitions_csv_and_spawns(tmp_path: Path) -> None:
    """The launcher:
    - partitions the input CSV into N shards under <saida>/shards/
    - picks N sorted proxy files from --proxy-pool-dir
    - calls `spawn(argv, cwd)` exactly N times with the right args
    - writes shards.pids
    """
    src_csv = tmp_path / "input.csv"
    with src_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["classe", "processo"])
        for i in range(12):
            w.writerow(["HC", 100 + i])

    pool_dir = tmp_path / "pools"
    pool_dir.mkdir()
    for letter in "abc":
        (pool_dir / f"proxies.{letter}.txt").write_text(f"{letter}1\n")

    saida = tmp_path / "out"
    spawns: list[tuple[list[str], Path]] = []

    def fake_spawn(argv: list[str], cwd: Path, driver_log: Path) -> int:
        spawns.append((argv, driver_log))
        return 10000 + len(spawns)  # fake PID

    pids_path = launch_sharded_download(
        csv_path=src_csv,
        shards=3,
        proxy_pool_dir=pool_dir,
        saida_root=saida,
        extra_args=["--retomar", "--nao-perguntar"],
        spawn=fake_spawn,
    )

    # 3 subprocesses, 3 PIDs recorded
    assert len(spawns) == 3
    lines = pids_path.read_text().strip().splitlines()
    assert len(lines) == 3
    # PIDs are in order 10001, 10002, 10003
    assert all(str(10000 + i + 1) in lines[i] for i in range(3))

    # each spawn's argv carries the right shard CSV + proxy + saida,
    # and its driver.log points at the per-shard output dir
    for i, (argv, driver_log) in enumerate(spawns):
        assert f"shard.{i}.csv" in " ".join(argv)
        assert f"proxies.{'abc'[i]}.txt" in " ".join(argv)
        assert f"shard-{'abc'[i]}" in " ".join(argv)
        assert "--retomar" in argv
        assert "--nao-perguntar" in argv
        assert driver_log.name == "driver.log"
        assert f"shard-{'abc'[i]}" in str(driver_log)

    # shards exist on disk with the right row counts (12 rows / 3 = 4 each)
    shard_dir = saida / "shards"
    shard_files = sorted(shard_dir.glob("input.shard.*.csv"))
    assert len(shard_files) == 3
    for sf in shard_files:
        with sf.open() as f:
            rows = list(csv.reader(f))
        # header + 4 rows each
        assert len(rows) == 5
