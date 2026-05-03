"""Locate + tail the live-signal log files for a run, mono or sharded.

Two execution paths under ``judex acompanhar``:

- **Mono** (one log file): exec straight into ``tail -F``. Ctrl-C
  belongs to tail; no Python in the loop.
- **Sharded** (N per-shard ``driver.log`` files): Python-side multitail.
  Compacts the output by:
    1. Dropping ``tail -F``'s ``==> shard-X/driver.log <==`` separator
       headers and instead prefixing each data line with ``[X]``.
    2. Suppressing the per-shard ``─── 571/571 (100%) · ... ───``
       progress lines — those are misleading at the shard level
       (denominator is meta-only, not pipeline-wide) and 16× redundant
       across a 16-shard run. A single aggregator thread reads every
       shard's ``executar.state.json`` periodically and emits ONE
       cluster-wide ``─── ... ───`` line in their place.

The aggregator uses real per-stage status counts from state files,
which fixes the ``100%`` lie that the per-shard line shows when meta
finishes while bytes/text are still flowing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


_MONO_LOG_NAMES = ("driver.log", "launcher.log", "executar.log")

# tail -F prints `==> <path> <==` whenever the file being read switches.
# Capture the shard letter so we can prefix subsequent data lines with `[X]`.
_TAIL_HEADER_RE = re.compile(r"^==>\s+.*?/shard-([a-z]+)/driver\.log\s+<==\s*$")

# Per-shard periodic progress line written by `_periodic_progress`. Visually
# distinctive (─── … ───) so the regex is anchored on those bookends.
_PROGRESS_LINE_RE = re.compile(r"^─── .* ───\s*$")


def find_log_paths(run_dir: Path) -> list[Path]:
    """Return the log files to tail for ``run_dir``.

    Order: sharded > top-level. Within sharded, sorted by shard letter
    so ``tail -F`` headers and re-runs are stable.
    """
    sharded = sorted(run_dir.glob("shard-*/driver.log"))
    if sharded:
        return sharded
    for name in _MONO_LOG_NAMES:
        p = run_dir / name
        if p.is_file():
            return [p]
    return []


def transform_lines(lines: Iterable[str]) -> Iterable[str]:
    """Convert raw ``tail -F`` output to compact ``[X] <line>`` form.

    Pure (input → output) so it's testable without subprocess plumbing.
    The caller is responsible for feeding lines in arrival order; the
    function tracks the current shard letter via the most recent header.

    Drops:
      - blank lines (tail emits these between files)
      - per-shard ``─── ... ───`` progress lines (replaced by the
        cluster aggregator's single line)
    """
    current = "?"
    for raw in lines:
        line = raw.rstrip("\n").rstrip("\r")
        m = _TAIL_HEADER_RE.match(line)
        if m:
            current = m.group(1)
            continue
        if not line.strip():
            continue
        if _PROGRESS_LINE_RE.match(line):
            continue
        yield f"[{current}] {line}"


def _count_total_targets(run_dir: Path) -> int:
    """Sum CSV row counts across ``<run_dir>/shards/*.shard.N.csv``.

    The shard launcher writes one CSV per shard with the round-robin
    case slice; their row counts (minus header) sum to the run's
    ``n_targets``. Returns 0 if no shards CSVs exist (caller can still
    render the line — denominator just shows ``?``).
    """
    csvs = list((run_dir / "shards").glob("*.shard.*.csv"))
    total = 0
    for c in csvs:
        try:
            with c.open() as f:
                total += max(0, sum(1 for _ in f) - 1)
        except OSError:
            continue
    return total


def aggregate_state(run_dir: Path) -> dict[str, object]:
    """Roll up per-stage status counts + totals across every shard's
    state file.

    Returns ``{}`` (not a dict-of-empty-counters) when no state files
    exist yet — the aggregator thread uses this to skip emitting an
    "all zeros" line during the first few seconds after launch.

    Otherwise returns the same shape as
    :meth:`judex.pipeline.state.PipelineState.aggregate_status_counts`::

        {
            "processos": Counter,
            "pecas":     Counter,
            "text":      Counter,
            "pecas_total": Optional[int],   # sum of n_pecas across
                                              # processos=ok records
            "text_total":  int,             # = pecas["ok"]
        }

    ``pecas_total`` is None when ANY meta=ok record on ANY shard lacks
    the ``n_pecas`` field — the renderer then drops the pecas ratio
    rather than show a wrong number. (Legacy state files written
    before n_pecas existed will have this property; new runs will
    always populate it.)
    """
    state_files = sorted(run_dir.glob("shard-*/executar.state.json"))
    if not state_files:
        return {}

    processos: Counter = Counter()
    pecas: Counter = Counter()
    text: Counter = Counter()
    pecas_total: Optional[int] = 0
    for sf in state_files:
        try:
            d = json.loads(sf.read_text())
        except (OSError, json.JSONDecodeError):
            continue  # mid-write race; next tick will see it
        for case in d.get("cases", {}).values():
            if not isinstance(case, dict):
                continue
            meta = case.get("fetch_meta") or {}
            m_status = meta.get("status")
            if m_status:
                processos[m_status] += 1
            if m_status == "ok":
                n = meta.get("n_pecas")
                if n is None:
                    pecas_total = None
                elif pecas_total is not None:
                    pecas_total += n
            for v in (case.get("fetch_bytes") or {}).values():
                s = (v or {}).get("status")
                if s:
                    pecas[s] += 1
            for v in (case.get("extract_text") or {}).values():
                s = (v or {}).get("status")
                if s:
                    text[s] += 1
    return {
        "processos": processos,
        "pecas": pecas,
        "text": text,
        "pecas_total": pecas_total,
        "text_total": pecas.get("ok", 0),
    }


def format_aggregate_line(
    agg: dict[str, object],
    n_targets: int,
    *,
    now: Optional[datetime] = None,
) -> str:
    """Format the cluster-wide ``─── ... ───`` progress line.

    Delegates to :func:`judex.utils.log_render.render_pipeline_progress_line`
    so mono and sharded share one source of truth for the progress
    line shape — same status ordering, same zero-suppression rules,
    same denominator discipline. The shard aggregate adds the
    ``[HH:MM:SS agg]`` prefix so the operator can tell it apart from
    per-shard data lines at a glance, and omits the rate / ETA suffix
    because those are scheduler-runtime numbers that an out-of-process
    tail can't fabricate without instrumentation.
    """
    from judex.utils.log_render import render_pipeline_progress_line

    processos = agg.get("processos") or Counter()
    pecas = agg.get("pecas") or Counter()
    text = agg.get("text") or Counter()
    ts = (now or datetime.now()).strftime("%H:%M:%S")
    return render_pipeline_progress_line(
        n_targets=n_targets,
        processos=processos,  # type: ignore[arg-type]
        pecas=pecas,          # type: ignore[arg-type]
        text=text,            # type: ignore[arg-type]
        pecas_total=agg.get("pecas_total"),  # type: ignore[arg-type]
        text_total=agg.get("text_total"),    # type: ignore[arg-type]
        prefix=f"[{ts} agg]",
        use_color=False,
    )


def _run_sharded_multitail(
    run_dir: Path,
    log_paths: list[Path],
    initial_lines: int,
    agg_interval: float,
) -> int:
    """Multitail driver for sharded runs. See module docstring for shape."""
    print_lock = threading.Lock()
    stop = threading.Event()
    n_targets = _count_total_targets(run_dir)

    def aggregator() -> None:
        # First emission immediately so the user sees current state on
        # startup; subsequent ones every agg_interval. Sleep is on
        # ``stop`` so Ctrl-C wakes the thread for clean exit.
        first = True
        while True:
            if not first and stop.wait(agg_interval):
                return
            first = False
            agg = aggregate_state(run_dir)
            if not agg:
                continue
            line = format_aggregate_line(agg, n_targets)
            with print_lock:
                print(line, flush=True)
            if stop.is_set():
                return

    argv = ["tail", "-n", str(initial_lines), "-F", *(str(p) for p in log_paths)]
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, text=True, bufsize=1,
    )
    agg_thread = threading.Thread(target=aggregator, daemon=True)
    agg_thread.start()

    try:
        assert proc.stdout is not None
        for prefixed in transform_lines(proc.stdout):
            with print_lock:
                print(prefixed, flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


def run_follow(
    run_dir: Path,
    *,
    n: int = 20,
    agg_interval: float = 30.0,
) -> int:
    """Resolve logs and tail them. Mono → execvp; sharded → multitail."""
    paths = find_log_paths(run_dir)
    if not paths:
        print(
            f"no driver.log, launcher.log, or shard-*/driver.log under {run_dir}",
            file=sys.stderr,
        )
        return 1
    if len(paths) == 1:
        os.execvp("tail", ["tail", "-n", str(n), "-F", str(paths[0])])
        return 0  # unreachable; execvp replaces the process
    return _run_sharded_multitail(run_dir, paths, n, agg_interval)
