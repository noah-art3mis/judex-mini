"""Locate + tail the live-signal log files for a run, mono or sharded.

Single execution path under ``judex acompanhar``: a Python multitail
that wraps ``tail -F`` for the actual byte stream and adds two run-aware
behaviours on top.

Behaviour 1 — line compaction (sharded only):
  - Drop ``tail -F``'s ``==> shard-X/driver.log <==`` separator headers
    and prefix each data line with a compact ``[X]`` instead.
  - Suppress the per-shard ``─── 571/571 (100%) · ... ───`` progress
    lines — those are misleading at the shard level (denominator is
    meta-only, not pipeline-wide) and 16× redundant across a 16-shard
    run. A single aggregator thread reads every shard's
    ``executar.state.json`` periodically and emits ONE cluster-wide
    ``─── ... ───`` line in their place. Same shape, real per-stage
    status counts, no ``100%`` lie.

Behaviour 2 — end-detection + auto-encerramento (default, mono + sharded):
  - The same aggregator tick (every ``agg_interval`` seconds) checks
    whether every shard's driver.log contains at least one
    ``executar: done`` line via :func:`judex.sweeps.run_summary.is_run_done`.
  - When the run is fully done, the aggregator stops the multitail,
    waits a short flush window so the last buffered tail lines drain,
    and then prints the consolidated rollup from ``relatar``. The
    process exits 0.
  - ``--persistir`` opts back into the legacy "tail forever" behaviour
    for operators who want to hold the connection open after a run
    finishes (e.g. to watch a manual re-launch from another shell
    against the same dir).

Mono and sharded share one loop. The previous ``execvp`` shortcut for
mono is dropped — its sole benefit was zero Python overhead, and the
cost of keeping it would be no end-detection on mono runs (since
``execvp`` replaces the Python process). The new default's auto-exit
+ summary is worth more than the ~50 ms Ctrl-C teardown delay.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
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

    # Optional sidecar from ``scripts/backfill_n_pecas.py``: maps
    # ``case_key -> n_pecas`` for cases whose live state.json record
    # lacks the field (legacy run, started before n_pecas existed).
    # Live shards never write this file, so the values survive
    # snapshot churn. Re-loaded each tick — the backfill script may
    # be re-run mid-session and we want fresh values.
    sidecar_path = run_dir / "n_pecas.json"
    sidecar: dict[str, int] = {}
    if sidecar_path.exists():
        try:
            raw = json.loads(sidecar_path.read_text())
            if isinstance(raw, dict):
                sidecar = {
                    k: v for k, v in raw.items()
                    if isinstance(k, str) and isinstance(v, int)
                }
        except (OSError, json.JSONDecodeError):
            pass  # corrupt sidecar; fall back to count-only

    processos: Counter = Counter()
    pecas: Counter = Counter()
    text: Counter = Counter()
    pecas_total: Optional[int] = 0
    for sf in state_files:
        try:
            d = json.loads(sf.read_text())
        except (OSError, json.JSONDecodeError):
            continue  # mid-write race; next tick will see it
        for case_key, case in (d.get("cases") or {}).items():
            if not isinstance(case, dict):
                continue
            meta = case.get("fetch_meta") or {}
            m_status = meta.get("status")
            if m_status:
                processos[m_status] += 1
            if m_status == "ok":
                n = meta.get("n_pecas")
                if n is None:
                    n = sidecar.get(case_key)
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


# --- end-detection + final-summary plumbing -------------------------------


# Time we let the multitail drain after `stop` is signalled. The tail
# subprocess buffers ~hundreds of lines; if we terminate it immediately
# the operator loses the last few seconds of activity (the very moment
# they care most about — that's when each shard's `executar: done`
# line lands). 0.5 s is enough on every box we've measured.
_DRAIN_FLUSH_S = 0.5


def _print_final_summary(run_dir: Path, *, lock: threading.Lock) -> None:
    """Render a `relatar`-style summary and print it under the lock so
    it doesn't interleave with stragglers from the tail subprocess."""
    from judex.sweeps.run_summary import render_summary, summarize_run

    summary = render_summary(summarize_run(run_dir))
    with lock:
        print()  # visual separator from the per-line stream
        print(summary, end="" if summary.endswith("\n") else "\n", flush=True)


def _run_multitail(
    run_dir: Path,
    log_paths: list[Path],
    initial_lines: int,
    agg_interval: float,
    *,
    persistir: bool,
) -> int:
    """Multitail driver shared by mono (1 log) and sharded (N logs).

    The aggregator thread does two jobs on each ``agg_interval`` tick:

    1. Sharded only — emit the cluster-wide ``─── ... ───`` line.
    2. Always — call :func:`is_run_done`. Once it returns True (and
       ``persistir`` is False), set ``done_detected`` and *terminate
       the tail subprocess*. Terminating the subprocess is what
       unblocks the main thread, which is otherwise blocked on its
       blocking read from the tail's stdout. ``stop.is_set()`` alone
       isn't enough — the main thread won't observe it until tail
       gives it a new line, which on a quiet finished run never
       happens.

    Mono runs skip step 1 (no per-shard noise to compress) but
    participate in step 2 — that's the whole reason the mono path
    moved off ``execvp``.
    """
    from judex.sweeps.run_summary import is_run_done

    print_lock = threading.Lock()
    stop = threading.Event()
    done_detected = threading.Event()
    n_targets = _count_total_targets(run_dir)
    is_sharded = len(log_paths) > 1 or (
        log_paths and log_paths[0].parent.name.startswith("shard-")
    )

    argv = ["tail", "-n", str(initial_lines), "-F", *(str(p) for p in log_paths)]
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, text=True, bufsize=1,
    )

    def aggregator() -> None:
        # First emission immediately so the operator sees current state
        # on startup; subsequent ones every agg_interval. Sleep is on
        # ``stop`` so Ctrl-C / done-detection wakes the thread for
        # clean exit.
        first = True
        while True:
            if not first and stop.wait(agg_interval):
                return
            first = False
            if is_sharded:
                agg = aggregate_state(run_dir)
                if agg:
                    line = format_aggregate_line(agg, n_targets)
                    with print_lock:
                        print(line, flush=True)
            if not persistir:
                all_done, _, n_shards = is_run_done(run_dir)
                if all_done and n_shards > 0:
                    done_detected.set()
                    stop.set()
                    # Closing the tail's stdout pipe is the only way
                    # to unblock the main thread's read loop — the
                    # ``stop`` event alone won't reach it until tail
                    # delivers a new line, which on a quiet finished
                    # run never happens. ``terminate`` is idempotent
                    # if the main thread's finally clause already
                    # called it.
                    try:
                        proc.terminate()
                    except (OSError, ProcessLookupError):
                        pass
                    return
            if stop.is_set():
                return

    agg_thread = threading.Thread(target=aggregator, daemon=True)
    agg_thread.start()

    # Main reader. Two ways out:
    # 1. Operator hits Ctrl-C → KeyboardInterrupt, normal teardown,
    #    no summary (we have nothing useful to summarise yet).
    # 2. Aggregator detected done → stdout pipe closes (tail killed),
    #    iterator hits EOF, loop exits. ``done_detected`` is True;
    #    main thread renders the final summary.
    try:
        assert proc.stdout is not None
        for prefixed in transform_lines(proc.stdout):
            with print_lock:
                print(prefixed, flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        if done_detected.is_set():
            time.sleep(_DRAIN_FLUSH_S)
        stop.set()
        try:
            proc.terminate()
        except (OSError, ProcessLookupError):
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    if done_detected.is_set():
        _print_final_summary(run_dir, lock=print_lock)
    return 0


def run_follow(
    run_dir: Path,
    *,
    n: int = 20,
    agg_interval: float = 30.0,
    persistir: bool = False,
) -> int:
    """Resolve logs and tail them with end-detection on by default.

    Mono and sharded share the same Python loop — the legacy
    ``execvp`` mono shortcut was dropped so end-detection works in
    both layouts. ``persistir=True`` restores the legacy "tail
    forever" behaviour by skipping the done-detection check.
    """
    paths = find_log_paths(run_dir)
    if not paths:
        print(
            f"no driver.log, launcher.log, or shard-*/driver.log under {run_dir}",
            file=sys.stderr,
        )
        return 1
    return _run_multitail(
        run_dir, paths, n, agg_interval, persistir=persistir,
    )
