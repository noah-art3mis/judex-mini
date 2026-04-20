"""Sharded-launch primitive for PDF-download sweeps.

Used by ``judex baixar-pecas --shards N --proxy-pool-dir D`` to partition
an input CSV into N disjoint shards, each bound to a different proxy
pool, and spawn N detached child processes (one per shard).

The launcher is the Python analogue of ``scripts/launch_hc_backfill_sharded.sh`` —
except it targets ``scripts/baixar_pecas.py`` (PDF bytes) rather than
``scripts/run_sweep.py`` (case JSON), and it lives in ``src/`` so it
composes with the Typer CLI naturally.

Design:
- **Range-partition** the CSV via ``scripts.shard_csv.shard_csv`` (not
  hash) so each shard owns a contiguous slice of processo_ids. Preserves
  locality + matches the monolithic-sweep seeding logic.
- **Proxy pool discovery** picks the first N alphabetically-sorted files
  matching ``proxies.<letter>.txt`` (single-letter suffix) from
  ``--proxy-pool-dir``. ``proxies.reserve.txt`` and other names are
  ignored. Errors loudly if fewer than N pools are available.
- **Detached children** via ``subprocess.Popen(start_new_session=True)``
  with ``nohup``-equivalent semantics (stdin closed, stdout/stderr to a
  per-shard ``driver.log``). Parent returns immediately; PIDs recorded to
  ``<saida_root>/shards.pids`` for ``kill -TERM`` / ``pgrep -af``.
- **Spawn is injected** (``spawn`` kwarg) so unit tests don't fork real
  processes. Default is ``_real_spawn`` in this module.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

from scripts.shard_csv import shard_csv


_PROXY_FILE_RE = re.compile(r"^proxies\.[a-z]\.txt$")

SpawnFn = Callable[[list[str], Path, Path], int]
"""(argv, cwd, driver_log) -> pid. driver_log is the file where stdout+stderr
of the child should be written (create/truncate)."""


class ProxyPoolShortage(RuntimeError):
    """Raised when --proxy-pool-dir has fewer matching files than --shards."""


def discover_proxy_pools(proxy_pool_dir: Path, n: int) -> list[Path]:
    """Return the first N alphabetically-sorted ``proxies.<letter>.txt`` files.

    Raises ``ProxyPoolShortage`` if fewer than N are present. Rejects
    non-single-letter suffixes (``proxies.reserve.txt``, ``proxies.pool1.txt``)
    so it can't accidentally pick up the reserve pool.
    """
    if not proxy_pool_dir.is_dir():
        raise ProxyPoolShortage(
            f"--proxy-pool-dir {proxy_pool_dir} is not a directory"
        )
    candidates = sorted(
        p for p in proxy_pool_dir.iterdir()
        if p.is_file() and _PROXY_FILE_RE.match(p.name)
    )
    if len(candidates) < n:
        raise ProxyPoolShortage(
            f"--proxy-pool-dir {proxy_pool_dir} has only {len(candidates)} "
            f"proxies.<letter>.txt file(s); need {n}"
        )
    return candidates[:n]


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
    proxy_pool_dir: Path,
    saida_root: Path,
    label_prefix: str,
    extra_args: Optional[list[str]] = None,
    spawn: Optional[SpawnFn] = None,
) -> Path:
    """Partition CSV, spawn N detached run_sweep children, return PIDs file.

    Sibling of :func:`launch_sharded_download`, targeting
    ``scripts/run_sweep.py`` (case JSON scrape) instead of
    ``scripts/baixar_pecas.py`` (PDF bytes). Same partition rule, same
    per-shard directory layout, same pids-file contract — the differences
    are:

    - **Label is mandatory.** ``run_sweep`` requires ``--label`` to name
      its sweep.state.json + sweep.log.jsonl; per-shard label is
      ``<label_prefix>_shard_<letter>`` so ``pgrep -f <label>`` targets a
      single shard and so shard logs don't cross-contaminate.
    - **Target script** is ``scripts/run_sweep.py`` (the WAF-hot half).
    - ``extra_args`` typically includes ``--resume`` + ``--items-dir
      data/cases/<CLASSE>``; the caller owns the choice.

    Raises :class:`ValueError` if ``label_prefix`` is empty — we'd
    otherwise silently spawn shards with ambiguous labels.
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
    shard_files = shard_csv(csv_path, shards, shards_dir)

    pools = discover_proxy_pools(proxy_pool_dir, shards)

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
    proxy_pool_dir: Path,
    saida_root: Path,
    extra_args: Optional[list[str]] = None,
    spawn: SpawnFn = _real_spawn,
) -> Path:
    """Partition CSV, spawn N detached baixar_pecas children, return PIDs file.

    Steps:
      1. Create ``<saida_root>/shards/`` and call ``shard_csv`` to range-
         partition ``csv_path`` into N files.
      2. Resolve N proxy pools via ``discover_proxy_pools``.
      3. For each shard, mkdir ``<saida_root>/shard-<letter>/`` and spawn
         ``uv run python scripts/baixar_pecas.py --csv SHARD --saida
         SHARD_DIR --proxy-pool POOL [extra_args]``. Child is detached.
      4. Write one ``<pid>  shard-<letter>`` line per child to
         ``<saida_root>/shards.pids``.
      5. Return the pids-file path.

    Returns the path to the ``shards.pids`` file so the caller can print
    the monitoring commands back to the user.
    """
    if shards < 2:
        raise ValueError("launch_sharded_download requires shards >= 2")
    extra_args = list(extra_args or [])

    saida_root.mkdir(parents=True, exist_ok=True)
    shards_dir = saida_root / "shards"
    shard_files = shard_csv(csv_path, shards, shards_dir)

    pools = discover_proxy_pools(proxy_pool_dir, shards)

    repo_root = Path.cwd()
    pids_path = saida_root / "shards.pids"
    lines: list[str] = []

    for i, (shard_csv_path, pool_path) in enumerate(zip(shard_files, pools)):
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
