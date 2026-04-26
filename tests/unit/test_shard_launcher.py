"""shard_launcher — sharded-launch primitive for judex sweeps.

Covers:
- ``split_proxy_file(file, n, dir)`` round-robin-splits a flat proxy
  file into N per-shard pools and tolerates blank/comment lines.
- ``launch_sharded_download`` and ``launch_sharded_sweep`` partition
  the CSV, materialize the per-shard pools, and spawn one subprocess
  per shard with the right argv. Spawn is injected so the test
  doesn't fork real processes.
- The Typer CLI surface (``judex varrer-processos --shards N
  --proxy-pool FILE``) wires through to ``launch_sharded_sweep`` with
  the right flag translations.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from judex.sweeps.shard_launcher import (
    launch_sharded_download,
    launch_sharded_sweep,
    split_proxy_file,
)


# --- split_proxy_file ------------------------------------------------------


def test_split_proxy_file_interleaves_lines_across_pools(tmp_path: Path) -> None:
    """``split_proxy_file`` distributes proxies round-robin (line ``i`` →
    shard ``i % N``), so geographic/provider clustering in the source file
    doesn't concentrate in one pool."""
    src = tmp_path / "proxies.txt"
    src.write_text("".join(f"proxy{i}\n" for i in range(10)))

    out_dir = tmp_path / "pools"
    paths = split_proxy_file(src, n=4, out_dir=out_dir)

    assert [p.name for p in paths] == [
        "proxies.a.txt", "proxies.b.txt", "proxies.c.txt", "proxies.d.txt",
    ]
    # 10 lines across 4 pools via interleave: [0,4,8], [1,5,9], [2,6], [3,7]
    assert (out_dir / "proxies.a.txt").read_text() == "proxy0\nproxy4\nproxy8\n"
    assert (out_dir / "proxies.b.txt").read_text() == "proxy1\nproxy5\nproxy9\n"
    assert (out_dir / "proxies.c.txt").read_text() == "proxy2\nproxy6\n"
    assert (out_dir / "proxies.d.txt").read_text() == "proxy3\nproxy7\n"


def test_split_proxy_file_ignores_blank_and_comment_lines(tmp_path: Path) -> None:
    """Users paste imperfect lists — tolerate blank lines and ``#`` comments
    so the count-then-split math stays honest."""
    src = tmp_path / "proxies.txt"
    src.write_text(
        "# fresh batch from scrapegw 2026-04-21\n"
        "proxy1\n"
        "\n"
        "proxy2\n"
        "   \n"
        "# old\n"
        "proxy3\n"
    )

    paths = split_proxy_file(src, n=2, out_dir=tmp_path / "pools")

    assert (paths[0]).read_text() == "proxy1\nproxy3\n"
    assert (paths[1]).read_text() == "proxy2\n"


def test_split_proxy_file_errors_when_fewer_lines_than_shards(tmp_path: Path) -> None:
    """Need at least one proxy per pool — refuse to create empty pools that
    would starve a shard of transport."""
    src = tmp_path / "proxies.txt"
    src.write_text("onlyone\n")

    with pytest.raises(ValueError, match="at least 4"):
        split_proxy_file(src, n=4, out_dir=tmp_path / "pools")


# --- launch_sharded_download -----------------------------------------------


def test_launch_sharded_download_partitions_csv_and_spawns(tmp_path: Path) -> None:
    """The launcher:
    - partitions the input CSV into N shards under ``<saida>/shards/``
    - splits ``proxy_pool`` round-robin into ``<saida>/proxies/proxies.<letter>.txt``
    - calls ``spawn(argv, cwd, driver_log)`` exactly N times with the right args
    - writes ``shards.pids``
    """
    src_csv = tmp_path / "input.csv"
    with src_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["classe", "processo"])
        for i in range(12):
            w.writerow(["HC", 100 + i])

    proxy_pool = tmp_path / "proxies.txt"
    proxy_pool.write_text("".join(f"ip{i}\n" for i in range(6)))

    saida = tmp_path / "out"
    spawns: list[tuple[list[str], Path]] = []

    def fake_spawn(argv: list[str], cwd: Path, driver_log: Path) -> int:
        spawns.append((argv, driver_log))
        return 10000 + len(spawns)  # fake PID

    pids_path = launch_sharded_download(
        csv_path=src_csv,
        shards=3,
        proxy_pool=proxy_pool,
        saida_root=saida,
        extra_args=["--retomar", "--nao-perguntar"],
        spawn=fake_spawn,
    )

    # 3 subprocesses, 3 PIDs recorded.
    assert len(spawns) == 3
    lines = pids_path.read_text().strip().splitlines()
    assert len(lines) == 3
    # PIDs are in order 10001, 10002, 10003.
    assert all(str(10000 + i + 1) in lines[i] for i in range(3))

    # Per-shard pool files materialized under <saida>/proxies/.
    for letter in "abc":
        assert (saida / "proxies" / f"proxies.{letter}.txt").exists()

    # Each spawn's argv carries the right shard CSV + proxy + saida,
    # and its driver.log points at the per-shard output dir.
    for i, (argv, driver_log) in enumerate(spawns):
        letter = "abc"[i]
        joined = " ".join(argv)
        assert f"shard.{i}.csv" in joined
        assert f"proxies/proxies.{letter}.txt" in joined
        assert f"shard-{letter}" in joined
        assert "--retomar" in argv
        assert "--nao-perguntar" in argv
        assert driver_log.name == "driver.log"
        assert f"shard-{letter}" in str(driver_log)

    # Shards exist on disk with the right row counts (12 rows / 3 = 4 each).
    shard_dir = saida / "shards"
    shard_files = sorted(shard_dir.glob("input.shard.*.csv"))
    assert len(shard_files) == 3
    for sf in shard_files:
        with sf.open() as f:
            rows = list(csv.reader(f))
        # header + 4 rows each
        assert len(rows) == 5


# --- launch_sharded_sweep --------------------------------------------------


def test_launch_sharded_sweep_partitions_csv_and_spawns(tmp_path: Path) -> None:
    """Sibling of :func:`launch_sharded_download`, targeting
    ``scripts/run_sweep.py``.

    Each shard must get a distinct ``--label`` (so sweep.state.json /
    pgrep-by-label stay workable per-shard), the right ``--csv`` /
    ``--out`` / ``--proxy-pool``, and any ``extra_args`` forwarded
    verbatim. PIDs file and ``driver.log`` location mirror
    ``launch_sharded_download``'s contract.
    """
    src_csv = tmp_path / "input.csv"
    with src_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["classe", "processo"])
        for i in range(8):
            w.writerow(["HC", 200 + i])

    proxy_pool = tmp_path / "proxies.txt"
    proxy_pool.write_text("ip1\nip2\nip3\nip4\n")

    saida = tmp_path / "out"
    spawns: list[tuple[list[str], Path]] = []

    def fake_spawn(argv: list[str], cwd: Path, driver_log: Path) -> int:
        spawns.append((argv, driver_log))
        return 20000 + len(spawns)

    pids_path = launch_sharded_sweep(
        csv_path=src_csv,
        shards=2,
        proxy_pool=proxy_pool,
        saida_root=saida,
        label_prefix="hc_backfill",
        extra_args=["--resume", "--items-dir", "data/source/processos/HC"],
        spawn=fake_spawn,
    )

    assert len(spawns) == 2
    lines = pids_path.read_text().strip().splitlines()
    assert len(lines) == 2
    # PIDs 20001 / 20002, tagged with shard letter.
    assert "20001" in lines[0] and "shard-a" in lines[0]
    assert "20002" in lines[1] and "shard-b" in lines[1]

    for i, (argv, driver_log) in enumerate(spawns):
        letter = "ab"[i]
        joined = " ".join(argv)
        assert "scripts/run_sweep.py" in joined
        assert f"shard.{i}.csv" in joined
        assert f"proxies/proxies.{letter}.txt" in joined
        assert f"shard-{letter}" in joined
        # Per-shard label — critical for run_sweep (state + pgrep).
        assert "--label" in argv
        label_val = argv[argv.index("--label") + 1]
        assert label_val == f"hc_backfill_shard_{letter}"
        # extra_args forwarded verbatim and in order.
        assert "--resume" in argv
        assert "--items-dir" in argv
        assert argv[argv.index("--items-dir") + 1] == "data/source/processos/HC"
        # driver.log lands under the shard's saida.
        assert driver_log.name == "driver.log"
        assert f"shard-{letter}" in str(driver_log)


def test_launch_sharded_sweep_requires_label_prefix(tmp_path: Path) -> None:
    """``run_sweep``'s ``--label`` is mandatory; refuse to spawn without a
    prefix rather than synthesizing one silently."""
    src_csv = tmp_path / "input.csv"
    with src_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["classe", "processo"])
        w.writerow(["HC", 1])

    proxy_pool = tmp_path / "proxies.txt"
    proxy_pool.write_text("ip1\nip2\n")

    with pytest.raises(ValueError, match="label"):
        launch_sharded_sweep(
            csv_path=src_csv,
            shards=2,
            proxy_pool=proxy_pool,
            saida_root=tmp_path / "out",
            label_prefix="",
            spawn=lambda *_: 0,
        )


# --- Typer CLI integration -------------------------------------------------


def test_varrer_processos_shards_cli_forwards_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI-level contract: ``judex varrer-processos --shards N
    --proxy-pool FILE`` partitions the CSV and spawns N children via
    ``launch_sharded_sweep``. The Typer wrapper must forward
    ``--retomar`` (→ ``--resume``), ``--diretorio-itens`` (→
    ``--items-dir``), and ``--rotulo`` (→ per-shard ``--label``)
    correctly — that translation is the most likely regression point
    when ``cli.py`` evolves.
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

    proxy_pool = tmp_path / "proxies.txt"
    proxy_pool.write_text("ip1\nip2\n")

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
        "--proxy-pool", str(proxy_pool),
        "--retomar",
        "--diretorio-itens", "data/source/processos/HC",
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
        assert argv[argv.index("--items-dir") + 1] == "data/source/processos/HC"
        assert argv[argv.index("--proxy-pool") + 1].endswith(
            f"proxies/proxies.{letter}.txt"
        )


def test_varrer_processos_shards_requires_proxy_pool(tmp_path: Path) -> None:
    """``--shards > 1`` without ``--proxy-pool`` is a usage error: the
    sharded mode has no fallback to direct-IP because each shard needs
    its own pool. Catch this at CLI parse time, not at launcher time."""
    from typer.testing import CliRunner

    from judex.cli import app

    src_csv = tmp_path / "input.csv"
    with src_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["classe", "processo"])
        w.writerow(["HC", 1])

    result = CliRunner().invoke(app, [
        "varrer-processos",
        "--csv", str(src_csv),
        "--saida", str(tmp_path / "out"),
        "--rotulo", "hc_test",
        "--shards", "2",
    ])

    assert result.exit_code != 0
    assert "--proxy-pool" in result.output
