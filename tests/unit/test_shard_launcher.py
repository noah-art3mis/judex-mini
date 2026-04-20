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
    launch_sharded_sweep,
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


def test_launch_sharded_sweep_partitions_csv_and_spawns(tmp_path: Path) -> None:
    """Sibling of launch_sharded_download, targeting `scripts/run_sweep.py`.

    Each shard must get a distinct --label (so sweep.state.json /
    pgrep-by-label stay workable per-shard), the right --csv / --out /
    --proxy-pool, and any extra_args forwarded verbatim. PIDs file and
    driver.log location mirror launch_sharded_download's contract.
    """
    src_csv = tmp_path / "input.csv"
    with src_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["classe", "processo"])
        for i in range(8):
            w.writerow(["HC", 200 + i])

    pool_dir = tmp_path / "pools"
    pool_dir.mkdir()
    for letter in "ab":
        (pool_dir / f"proxies.{letter}.txt").write_text(f"{letter}1\n")

    saida = tmp_path / "out"
    spawns: list[tuple[list[str], Path]] = []

    def fake_spawn(argv: list[str], cwd: Path, driver_log: Path) -> int:
        spawns.append((argv, driver_log))
        return 20000 + len(spawns)

    pids_path = launch_sharded_sweep(
        csv_path=src_csv,
        shards=2,
        proxy_pool_dir=pool_dir,
        saida_root=saida,
        label_prefix="hc_backfill",
        extra_args=["--resume", "--items-dir", "data/cases/HC"],
        spawn=fake_spawn,
    )

    assert len(spawns) == 2
    lines = pids_path.read_text().strip().splitlines()
    assert len(lines) == 2
    # PIDs 20001 / 20002, tagged with shard letter
    assert "20001" in lines[0] and "shard-a" in lines[0]
    assert "20002" in lines[1] and "shard-b" in lines[1]

    for i, (argv, driver_log) in enumerate(spawns):
        letter = "ab"[i]
        joined = " ".join(argv)
        assert "scripts/run_sweep.py" in joined
        assert f"shard.{i}.csv" in joined
        assert f"proxies.{letter}.txt" in joined
        assert f"shard-{letter}" in joined
        # Per-shard label — critical for run_sweep (state + pgrep).
        assert "--label" in argv
        label_val = argv[argv.index("--label") + 1]
        assert label_val == f"hc_backfill_shard_{letter}"
        # extra_args forwarded verbatim and in order
        assert "--resume" in argv
        assert "--items-dir" in argv
        assert argv[argv.index("--items-dir") + 1] == "data/cases/HC"
        # driver.log lands under the shard's saida
        assert driver_log.name == "driver.log"
        assert f"shard-{letter}" in str(driver_log)


def test_varrer_processos_shards_cli_forwards_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI-level contract: `judex varrer-processos --shards N` partitions
    the CSV and spawns N children via launch_sharded_sweep. The Typer
    wrapper must forward --retomar (→ --resume), --diretorio-itens
    (→ --items-dir), and --rotulo (→ per-shard --label) correctly — that
    translation is the most likely regression point when cli.py evolves.
    """
    from typer.testing import CliRunner

    from judex.cli import app
    from judex.sweeps import shard_launcher

    src_csv = tmp_path / "input.csv"
    with src_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["classe", "processo"])
        for i in range(6):
            w.writerow(["HC", 500 + i])

    pool_dir = tmp_path / "pools"
    pool_dir.mkdir()
    (pool_dir / "proxies.a.txt").write_text("a1\n")
    (pool_dir / "proxies.b.txt").write_text("b1\n")

    saida = tmp_path / "out"
    spawned: list[list[str]] = []

    def fake_spawn(argv: list[str], cwd: Path, driver_log: Path) -> int:
        spawned.append(argv)
        return 30000 + len(spawned)

    monkeypatch.setattr(shard_launcher, "_real_spawn", fake_spawn)

    result = CliRunner().invoke(app, [
        "varrer-processos",
        "--csv", str(src_csv),
        "--saida", str(saida),
        "--rotulo", "hc_q2",
        "--shards", "2",
        "--proxy-pool-dir", str(pool_dir),
        "--retomar",
        "--diretorio-itens", "data/cases/HC",
    ])

    assert result.exit_code == 0, result.output
    assert "Lançou 2 shards" in result.output
    assert len(spawned) == 2

    # Per-shard argv must carry the English script-layer flags with
    # values translated from the Portuguese CLI flags.
    for i, argv in enumerate(spawned):
        letter = "ab"[i]
        assert "scripts/run_sweep.py" in " ".join(argv)
        assert argv[argv.index("--label") + 1] == f"hc_q2_shard_{letter}"
        assert "--resume" in argv
        assert argv[argv.index("--items-dir") + 1] == "data/cases/HC"
        assert argv[argv.index("--proxy-pool") + 1].endswith(
            f"proxies.{letter}.txt"
        )


def test_launch_sharded_sweep_requires_label_prefix(tmp_path: Path) -> None:
    """run_sweep's --label is mandatory; refuse to spawn without a prefix
    rather than synthesizing one silently."""
    src_csv = tmp_path / "input.csv"
    with src_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["classe", "processo"])
        w.writerow(["HC", 1])

    pool_dir = tmp_path / "pools"
    pool_dir.mkdir()
    (pool_dir / "proxies.a.txt").write_text("a1\n")
    (pool_dir / "proxies.b.txt").write_text("b1\n")

    with pytest.raises(ValueError, match="label"):
        launch_sharded_sweep(
            csv_path=src_csv,
            shards=2,
            proxy_pool_dir=pool_dir,
            saida_root=tmp_path / "out",
            label_prefix="",
            spawn=lambda *_: 0,
        )
