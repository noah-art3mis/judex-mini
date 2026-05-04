"""shard_launcher — sharded-launch primitive for judex sweeps.

Covers:
- ``split_proxy_file(file, n, dir)`` round-robin-splits a flat proxy
  file into N per-shard pools and tolerates blank/comment lines.
- ``launch_sharded(command=..., ...)`` partitions the CSV, materializes
  the per-shard pools, and spawns one subprocess per shard with the
  right argv. Spawn is injected so the test doesn't fork real processes.
  Tested for both supported commands (``baixar-pecas``, which has no
  ``--rotulo``, and ``varrer-processos``, which requires one).
- The Typer CLI surface (``judex varrer-processos --shards N
  --proxy-pool FILE``) wires through to ``launch_sharded`` with the
  right per-command argv shape.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from judex.sweeps.shard_launcher import launch_sharded, split_proxy_file


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


# --- launch_sharded for baixar-pecas (no --rotulo) ------------------------


def test_launch_sharded_baixar_pecas_partitions_csv_and_spawns(tmp_path: Path) -> None:
    """For ``command="baixar-pecas"`` the launcher:
    - partitions the input CSV into N shards under ``<saida>/shards/``
    - splits ``proxy_pool`` round-robin into ``<saida>/proxies/proxies.<letter>.txt``
    - calls ``spawn(argv, cwd, driver_log)`` exactly N times with the right args
    - writes ``shards.pids``
    No ``--rotulo`` flag is emitted (baixar-pecas doesn't have one).
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

    pids_path = launch_sharded(
        command="baixar-pecas",
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
        # Typer command, not --rotulo (baixar-pecas has no --rotulo).
        assert argv[:4] == ["uv", "run", "judex", "baixar-pecas"]
        assert "--rotulo" not in argv
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


# --- launch_sharded for varrer-processos (with --rotulo) -------------------


def test_launch_sharded_varrer_processos_partitions_csv_and_spawns(tmp_path: Path) -> None:
    """For ``command="varrer-processos"`` the launcher emits per-shard
    ``--rotulo`` (synthesised from ``label_prefix``) since
    ``judex varrer-processos`` requires it. Same partition rule, same
    per-shard directory layout, same pids-file contract as the
    ``baixar-pecas`` path; the per-command differences are isolated to
    the argv (command name + ``--rotulo`` flag).
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

    pids_path = launch_sharded(
        command="varrer-processos",
        csv_path=src_csv,
        shards=2,
        proxy_pool=proxy_pool,
        saida_root=saida,
        label_prefix="hc_backfill",
        extra_args=["--retomar", "--diretorio-itens", "data/source/processos/HC"],
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
        # Typer command via uv run, not the deprecated python scripts/ path.
        assert argv[:4] == ["uv", "run", "judex", "varrer-processos"]
        assert f"shard.{i}.csv" in joined
        assert f"proxies/proxies.{letter}.txt" in joined
        assert f"shard-{letter}" in joined
        # Per-shard rótulo — critical for varrer-processos (state + pgrep).
        assert "--rotulo" in argv
        label_val = argv[argv.index("--rotulo") + 1]
        assert label_val == f"hc_backfill_shard_{letter}"
        # extra_args forwarded verbatim and in order.
        assert "--retomar" in argv
        assert "--diretorio-itens" in argv
        assert argv[argv.index("--diretorio-itens") + 1] == "data/source/processos/HC"
        # driver.log lands under the shard's saida.
        assert driver_log.name == "driver.log"
        assert f"shard-{letter}" in str(driver_log)


def test_launch_sharded_varrer_requires_label_prefix(tmp_path: Path) -> None:
    """``judex varrer-processos`` requires ``--rotulo``; the launcher refuses
    to spawn without a non-empty ``label_prefix`` rather than synthesizing
    one silently. Other commands (e.g. ``baixar-pecas``) don't need it."""
    src_csv = tmp_path / "input.csv"
    with src_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["classe", "processo"])
        w.writerow(["HC", 1])

    proxy_pool = tmp_path / "proxies.txt"
    proxy_pool.write_text("ip1\nip2\n")

    with pytest.raises(ValueError, match="label_prefix"):
        launch_sharded(
            command="varrer-processos",
            csv_path=src_csv,
            shards=2,
            proxy_pool=proxy_pool,
            saida_root=tmp_path / "out",
            label_prefix="",
            spawn=lambda *_: 0,
        )


