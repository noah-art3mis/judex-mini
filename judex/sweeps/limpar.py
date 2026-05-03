"""`judex limpar`: one-command residual recovery for finished runs.

A finished ``judex executar`` run leaves a residual — rows in
``executar.errors.jsonl`` whose status is not ``ok``. ``limpar`` walks
the run dir (mono *or* sharded — auto-detects), partitions every row by
``(kind, classify_unified_error(row))`` plus a small ``(kind, status)``
override for the actionable terminals, and dispatches recoveries.

This module is **pure** for the planner half (``discover_run_dirs``,
``classify_residual``, ``plan_recoveries``, ``format_summary``) — no
subprocesses, no I/O beyond reading ``executar.errors.jsonl``. The
side-effecting half is :func:`execute_recoveries`, which spawns one
detached ``judex executar --retentar-de`` per source dir with at least
one transient row.

Spec: ``docs/superpowers/specs/2026-05-03-judex-limpar.md``.
"""

from __future__ import annotations

import enum
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from judex.pipeline.log import classify_unified_error, read_errors_file


ERRORS_FILENAME = "executar.errors.jsonl"


class Bucket(str, enum.Enum):
    """Recovery action assigned to one ``executar.errors.jsonl`` row.

    Order is the order columns appear in the summary line (kept stable
    so jq pipelines and humans can rely on it).
    """

    REPLAY = "transient"
    REFETCH_UPSTREAM = "cross_stage"
    PROVIDER_SWITCH = "provider_switched"
    CONFIRMED_UNALLOCATED = "confirmed_unallocated"
    TERMINAL_DROPPED = "terminal_dropped"


@dataclass(frozen=True)
class ErrorRow:
    """One row from an ``executar.errors.jsonl``, tagged with its source dir.

    ``source_dir`` is what tells :func:`plan_recoveries` which dir to
    spawn against — sharded inputs aggregate rows from many shards but
    the dispatch is per-shard.
    """

    source_dir: Path
    kind: str
    classe: str
    processo: int
    status: str
    url: Optional[str]
    raw: dict[str, Any]


@dataclass(frozen=True)
class Spawn:
    """One detached child invocation planned by :func:`plan_recoveries`.

    ``argv`` is what :func:`execute_recoveries` passes to
    ``subprocess.Popen``. ``saida`` is the per-shard run dir (where the
    child writes its log + state). ``source_errors_file`` is the input
    the child consumes via ``--retentar-de``.
    """

    argv: list[str]
    saida: Path
    source_errors_file: Path
    n_replay_rows: int


# Bucket order for summary line — matches the order in which Bucket
# was declared. Defined here so format_summary doesn't depend on
# enum-iteration order in unusual interpreters.
_BUCKET_ORDER: tuple[Bucket, ...] = (
    Bucket.REPLAY,
    Bucket.REFETCH_UPSTREAM,
    Bucket.PROVIDER_SWITCH,
    Bucket.CONFIRMED_UNALLOCATED,
    Bucket.TERMINAL_DROPPED,
)


# ---------------------------------------------------------------------------
# Discovery: mono vs sharded auto-detect
# ---------------------------------------------------------------------------


def discover_run_dirs(run_dir: Path) -> list[Path]:
    """Return the source dirs for a finished ``judex executar`` run.

    Sharded:    ``[run_dir/shard-a, run_dir/shard-b, ...]`` (sorted by
                directory name) — one entry per shard whose
                ``executar.errors.jsonl`` exists.
    Monolithic: ``[run_dir]`` if ``run_dir/executar.errors.jsonl`` exists.
    Empty residual: ``[]`` — caller treats as "nothing to recover".

    A shard subdir without an ``executar.errors.jsonl`` is dropped: not
    every shard necessarily produced a residual (some can finish with
    zero errors), and re-spawning ``--retentar-de`` against an absent
    file would fail.
    """
    shard_dirs = sorted(
        d for d in run_dir.glob("shard-*")
        if d.is_dir() and (d / ERRORS_FILENAME).exists()
    )
    if shard_dirs:
        return shard_dirs

    if (run_dir / ERRORS_FILENAME).exists():
        return [run_dir]

    return []


# ---------------------------------------------------------------------------
# Classification: rows → buckets
# ---------------------------------------------------------------------------


def _bucket_for(row: dict[str, Any]) -> Optional[Bucket]:
    """Return the Bucket for one errors.jsonl row, or ``None`` if the row
    should be dropped (status=ok / skipped_cached).

    Composes :func:`classify_unified_error` with the override table for
    actionable terminals. Two overrides:

    - ``(extract_text, "empty")`` — classifier says terminal, but
      ``--provedor chandra --forcar`` can recover it. Bucketed as
      ``PROVIDER_SWITCH`` so the summary line surfaces it.
    - ``(extract_text, "no_bytes")`` — classifier says cross_stage;
      bucketed as ``REFETCH_UPSTREAM`` (semantically the same; this
      override is just naming).
    - ``(fetch_meta, "unallocated_pid")`` — terminal, but a distinct
      bucket because the operator wants the count separately
      ("confirmed STF doesn't have these PIDs").
    """
    kind = row.get("kind")
    status = row.get("status")
    classified = classify_unified_error(row)

    if classified == "ok":
        return None

    if classified == "transient":
        return Bucket.REPLAY

    if classified == "cross_stage":
        return Bucket.REFETCH_UPSTREAM

    # classified == "terminal" — actionable overrides
    if kind == "extract_text" and status == "empty":
        return Bucket.PROVIDER_SWITCH
    if kind == "fetch_meta" and status == "unallocated_pid":
        return Bucket.CONFIRMED_UNALLOCATED
    return Bucket.TERMINAL_DROPPED


def _empty_buckets() -> dict[Bucket, list[ErrorRow]]:
    return {b: [] for b in _BUCKET_ORDER}


def classify_residual(dirs: list[Path]) -> dict[Bucket, list[ErrorRow]]:
    """Walk every dir's ``executar.errors.jsonl``, partition by bucket.

    The returned dict has one entry per :class:`Bucket` (every key
    populated, possibly empty). Rows that classify as ``ok`` /
    ``skipped_cached`` are dropped silently — they are snapshot
    artifacts of older code paths and have nothing to recover.
    """
    buckets = _empty_buckets()

    for source_dir in dirs:
        path = source_dir / ERRORS_FILENAME
        for raw in read_errors_file(path):
            bucket = _bucket_for(raw)
            if bucket is None:
                continue
            row = ErrorRow(
                source_dir=source_dir,
                kind=str(raw.get("kind") or ""),
                classe=str(raw.get("classe") or ""),
                processo=int(raw.get("processo") or 0),
                status=str(raw.get("status") or ""),
                url=raw.get("url"),
                raw=raw,
            )
            buckets[bucket].append(row)

    return buckets


# ---------------------------------------------------------------------------
# Planning: buckets → list of detached child invocations
# ---------------------------------------------------------------------------


def plan_recoveries(
    buckets: dict[Bucket, list[ErrorRow]],
    *,
    provedor: str,
) -> list[Spawn]:
    """Return one :class:`Spawn` per source dir with at least one REPLAY row.

    Only the REPLAY bucket is auto-dispatched in v1 (see spec § "Why
    replay is the only auto-dispatched action"). Source dirs whose
    residual is entirely terminal or cross_stage produce no spawn —
    ``--retentar-de`` would no-op there anyway, so spawning would just
    create empty children.

    Spawn order matches the order source dirs first appear in the
    REPLAY bucket; sorted only because ErrorRow rows themselves are
    appended in the order :func:`classify_residual` walked them, which
    was the alphabetic order from :func:`discover_run_dirs`.
    """
    rows_per_dir: dict[Path, list[ErrorRow]] = {}
    for row in buckets[Bucket.REPLAY]:
        rows_per_dir.setdefault(row.source_dir, []).append(row)

    plans: list[Spawn] = []
    for source_dir in sorted(rows_per_dir.keys()):
        rows = rows_per_dir[source_dir]
        errors_file = source_dir / ERRORS_FILENAME
        argv = [
            "uv", "run", "judex", "executar",
            "--retentar-de", str(errors_file),
            "--saida", str(source_dir),
            "--provedor", provedor,
            "--nao-perguntar",
        ]
        plans.append(Spawn(
            argv=argv,
            saida=source_dir,
            source_errors_file=errors_file,
            n_replay_rows=len(rows),
        ))
    return plans


# ---------------------------------------------------------------------------
# Summary line
# ---------------------------------------------------------------------------


def format_summary(
    buckets: dict[Bucket, list[ErrorRow]],
    *,
    dry_run: bool,
) -> str:
    """Render the one-line summary the spec calls for.

    ``recovered:`` under ``--apply``; ``would-recover:`` under
    ``--dry-run``. Counts in fixed bucket order; ``·`` separators
    (U+00B7) chosen to match ``judex acompanhar``'s aggregate prefix
    style.
    """
    prefix = "would-recover:" if dry_run else "recovered:"
    parts = [
        f"{len(buckets[bucket])} {bucket.value}"
        for bucket in _BUCKET_ORDER
    ]
    return f"{prefix} {' · '.join(parts)}"


# ---------------------------------------------------------------------------
# Execution: spawn detached children
# ---------------------------------------------------------------------------


@dataclass
class ExecuteResult:
    """Bookkeeping for :func:`execute_recoveries`."""

    pids_path: Path
    pids: list[int] = field(default_factory=list)


def execute_recoveries(
    plan: list[Spawn],
    pids_path: Path,
) -> ExecuteResult:
    """Spawn each :class:`Spawn` detached, write a ``limpar.pids`` file.

    Mirrors the existing ``shards.pids`` convention so monitoring tools
    (``pgrep -af`` + ``judex acompanhar``) work without modification.
    Each child's stdout/stderr is redirected to ``<saida>/limpar.log``
    (separate from ``driver.log`` so the cleanup pass stays
    distinguishable from the original run on disk).

    The parent does not wait — children are detached via
    ``start_new_session=True``. Returns immediately after recording
    PIDs.
    """
    result = ExecuteResult(pids_path=pids_path)

    pids_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    for spawn in plan:
        log_path = spawn.saida / "limpar.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Open in append mode so a re-run doesn't clobber prior tail.
        log_fh = log_path.open("ab")
        proc = subprocess.Popen(
            spawn.argv,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        log_fh.close()
        result.pids.append(proc.pid)
        lines.append(f"{proc.pid}  {spawn.saida.name}")

    pids_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return result


# ---------------------------------------------------------------------------
# Top-level orchestration (called by the Typer command)
# ---------------------------------------------------------------------------


def run_limpar(
    run_dir: Path,
    *,
    apply: bool,
    provedor: str,
) -> tuple[int, str]:
    """Compute the plan and (under ``apply``) execute it.

    Returns ``(exit_code, summary_line)``. The CLI prints the summary
    line and returns the exit code. Exit codes:

    - ``0`` — plan computed (and under ``apply``, all spawns succeeded).
    - ``2`` — invalid inputs (run_dir doesn't exist).
    - ``3`` — empty residual (no errors files anywhere). Distinct from
      0 so cron jobs can branch on "nothing to do".
    """
    if not run_dir.exists():
        return 2, f"limpar: run_dir {run_dir!s} does not exist"

    dirs = discover_run_dirs(run_dir)
    if not dirs:
        return 3, f"limpar: nothing to recover under {run_dir!s} (no executar.errors.jsonl found)"

    buckets = classify_residual(dirs)
    summary = format_summary(buckets, dry_run=not apply)

    if not apply:
        return 0, summary

    plan = plan_recoveries(buckets, provedor=provedor)
    if not plan:
        # Nothing to dispatch even under --apply (no transient rows)
        return 0, summary

    pids_path = run_dir / "limpar.pids"
    execute_recoveries(plan, pids_path)
    return 0, summary
