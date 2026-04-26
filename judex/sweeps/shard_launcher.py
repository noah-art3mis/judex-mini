"""Sharded-launch primitives for judex sweeps.

Used by:
- ``judex varrer-processos --shards N --proxy-pool FILE`` (case JSON,
  WAF-hot; routed through ``scripts/run_sweep.py``).
- ``judex baixar-pecas      --shards N --proxy-pool FILE`` (PDF bytes;
  routed through ``scripts/baixar_pecas.py``).

Both callers partition an input CSV into N disjoint shards and detach
one child process per shard, each bound to a slice of the proxy pool.

Design:
- **Single proxy input file.** The caller passes one flat file of
  proxy URLs (one per line; blank lines and ``#`` comments ignored).
  :func:`split_proxy_file` materializes N per-shard sub-files under
  ``<saida_root>/proxies/proxies.<letter>.txt`` via round-robin, so
  line ``i`` lands in pool ``i % N`` and any geographic/provider
  clustering is spread across shards instead of concentrated.
- **Shard partitioning** via :func:`scripts.shard_csv.shard_csv`.
  Default strategy is ``interleave`` (line ``i`` → shard ``i % N``),
  which spreads any correlation with CSV order across shards.
  ``range`` is still selectable for workloads where per-shard pid
  locality matters.
- **Detached children** via ``subprocess.Popen(start_new_session=True)``
  with ``nohup``-equivalent semantics (stdin closed, stdout/stderr to
  a per-shard ``driver.log``). Parent returns immediately; PIDs are
  recorded to ``<saida_root>/shards.pids`` for
  ``xargs -a ... kill -TERM`` / ``pgrep -af <label>``.
- **Spawn is injected** (``spawn`` kwarg) so unit tests don't fork
  real processes. Default is ``_real_spawn`` in this module.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional

from scripts.shard_csv import ShardStrategy, shard_csv


SpawnFn = Callable[[list[str], Path, Path], int]
"""(argv, cwd, driver_log) -> pid. driver_log is the file where stdout+stderr
of the child should be written (create/truncate)."""


def split_proxy_file(proxy_file: Path, n: int, out_dir: Path) -> list[Path]:
    """Split a flat proxy list into N pools via round-robin.

    The caller keeps a single source-of-truth file (e.g. freshly pasted
    from a proxy provider) containing one proxy URL per line; we split
    it at launch time into ``out_dir/proxies.{a..}.txt`` — line ``i``
    lands in pool ``i % n``, distributing any geographic/provider
    clustering across shards rather than concentrating it. Blank lines
    and ``#``-prefixed comments are ignored so pasted batches don't
    need polishing.

    Returns the list of per-pool file paths in alphabetical order,
    ready to hand to each shard's ``--proxy-pool`` arg.

    Raises ``ValueError`` if the source has fewer usable lines than
    ``n`` — we refuse to create empty pool files that would starve a
    shard.
    """
    lines = []
    for raw in proxy_file.read_text().splitlines():
        s = raw.strip()
        if s and not s.startswith("#"):
            lines.append(s)
    if len(lines) < n:
        raise ValueError(
            f"{proxy_file} has {len(lines)} usable proxies; need at least {n} "
            f"(one per shard). Add more proxies or reduce --shards."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    pools: list[list[str]] = [[] for _ in range(n)]
    for i, line in enumerate(lines):
        pools[i % n].append(line)
    paths: list[Path] = []
    for idx, pool_lines in enumerate(pools):
        letter = chr(ord("a") + idx)
        path = out_dir / f"proxies.{letter}.txt"
        path.write_text("\n".join(pool_lines) + "\n")
        paths.append(path)
    return paths


def _real_spawn(argv: list[str], cwd: Path, driver_log: Path) -> int:
    """Detached spawn that redirects child stdout+stderr to ``driver_log``.

    The log file is opened in append mode with line buffering so repeat
    launches append rather than clobber (matches run_sweep's driver.log
    contract). Child is placed in a new session so the parent Typer
    process can exit without taking it down.
    """
    log_fh = driver_log.open("a", buffering=1)
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    # The fd is duplicated into the child on fork; we can close ours.
    log_fh.close()
    return proc.pid


def launch_sharded_sweep(
    *,
    csv_path: Path,
    shards: int,
    proxy_pool: Path,
    saida_root: Path,
    label_prefix: str,
    extra_args: Optional[list[str]] = None,
    spawn: Optional[SpawnFn] = None,
    strategy: ShardStrategy = "interleave",
) -> Path:
    """Partition CSV, spawn N detached run_sweep children, return PIDs file.

    Sibling of :func:`launch_sharded_download`, targeting
    ``scripts/run_sweep.py`` (case JSON scrape) instead of
    ``scripts/baixar_pecas.py`` (PDF bytes). Same partition rule, same
    per-shard directory layout, same pids-file contract — the
    differences are:

    - **Label is mandatory.** ``run_sweep`` requires ``--label`` to
      name its sweep.state.json + sweep.log.jsonl; per-shard label is
      ``<label_prefix>_shard_<letter>`` so ``pgrep -f <label>`` targets
      a single shard and so shard logs don't cross-contaminate.
    - **Target script** is ``scripts/run_sweep.py`` (the WAF-hot half).
    - ``extra_args`` typically includes ``--resume`` + ``--items-dir
      data/source/processos/<CLASSE>``; the caller owns the choice.

    Raises :class:`ValueError` if ``label_prefix`` is empty, or if
    ``proxy_pool`` has fewer usable proxy lines than ``shards``.
    """
    if shards < 2:
        raise ValueError("launch_sharded_sweep requires shards >= 2")
    if not label_prefix:
        raise ValueError(
            "launch_sharded_sweep requires a non-empty label_prefix "
            "(run_sweep's --label is mandatory)"
        )
    # Resolve spawn at call time so monkeypatching _real_spawn (e.g. from
    # CLI integration tests) reaches this path without callers needing to
    # pass spawn= explicitly.
    if spawn is None:
        spawn = _real_spawn
    extra_args = list(extra_args or [])

    saida_root.mkdir(parents=True, exist_ok=True)
    shards_dir = saida_root / "shards"
    shard_files = shard_csv(csv_path, shards, shards_dir, strategy=strategy)

    pools = split_proxy_file(proxy_pool, shards, saida_root / "proxies")

    repo_root = Path.cwd()
    pids_path = saida_root / "shards.pids"
    lines: list[str] = []

    for shard_csv_path, pool_path in zip(shard_files, pools):
        letter = pool_path.stem.split(".")[1]  # proxies.a.txt -> "a"
        shard_saida = saida_root / f"shard-{letter}"
        shard_saida.mkdir(parents=True, exist_ok=True)

        argv = [
            "uv", "run", "python", "scripts/run_sweep.py",
            "--csv", str(shard_csv_path),
            "--label", f"{label_prefix}_shard_{letter}",
            "--out", str(shard_saida),
            "--proxy-pool", str(pool_path),
            *extra_args,
        ]
        driver_log = shard_saida / "driver.log"
        pid = spawn(argv, repo_root, driver_log)
        lines.append(f"{pid}  shard-{letter}")

    pids_path.write_text("\n".join(lines) + "\n")
    return pids_path


def launch_sharded_download(
    *,
    csv_path: Path,
    shards: int,
    proxy_pool: Path,
    saida_root: Path,
    extra_args: Optional[list[str]] = None,
    spawn: SpawnFn = _real_spawn,
    strategy: ShardStrategy = "interleave",
) -> Path:
    """Partition CSV, spawn N detached baixar_pecas children, return PIDs file.

    Steps:
      1. Create ``<saida_root>/shards/`` and call ``shard_csv`` to
         partition ``csv_path`` into N files (strategy-driven).
      2. Split ``proxy_pool`` round-robin into N per-shard files under
         ``<saida_root>/proxies/proxies.<letter>.txt``.
      3. For each shard, mkdir ``<saida_root>/shard-<letter>/`` and
         spawn ``uv run python scripts/baixar_pecas.py --csv SHARD
         --saida SHARD_DIR --proxy-pool POOL [extra_args]``. Child is
         detached.
      4. Write one ``<pid>  shard-<letter>`` line per child to
         ``<saida_root>/shards.pids``.
      5. Return the pids-file path.

    Raises :class:`ValueError` if ``proxy_pool`` has fewer usable proxy
    lines than ``shards``.
    """
    if shards < 2:
        raise ValueError("launch_sharded_download requires shards >= 2")
    extra_args = list(extra_args or [])

    saida_root.mkdir(parents=True, exist_ok=True)
    shards_dir = saida_root / "shards"
    shard_files = shard_csv(csv_path, shards, shards_dir, strategy=strategy)

    pools = split_proxy_file(proxy_pool, shards, saida_root / "proxies")

    repo_root = Path.cwd()
    pids_path = saida_root / "shards.pids"
    lines: list[str] = []

    for shard_csv_path, pool_path in zip(shard_files, pools):
        # Shard letter follows the pool's letter (a, b, c, ...) for easy
        # "shard-a uses proxies.a.txt" reasoning.
        letter = pool_path.stem.split(".")[1]  # proxies.a.txt -> "a"
        shard_saida = saida_root / f"shard-{letter}"
        shard_saida.mkdir(parents=True, exist_ok=True)

        argv = [
            "uv", "run", "python", "scripts/baixar_pecas.py",
            "--csv", str(shard_csv_path),
            "--saida", str(shard_saida),
            "--proxy-pool", str(pool_path),
            *extra_args,
        ]
        driver_log = shard_saida / "driver.log"
        pid = spawn(argv, repo_root, driver_log)
        lines.append(f"{pid}  shard-{letter}")

    pids_path.write_text("\n".join(lines) + "\n")
    return pids_path
