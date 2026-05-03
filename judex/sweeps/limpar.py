"""`judex limpar`: one-command residual recovery for finished runs.

A finished ``judex executar`` run leaves a residual — records in
``executar.state.json`` whose status is not ``ok`` /
``skipped_cached``. ``limpar`` walks the run dir (mono *or* sharded —
auto-detects), reads each shard's **state.json** (the canonical
record), partitions every non-ok record by
``(kind, classify_unified_error(record))`` plus a small
``(kind, status)`` override for actionable terminals, plus a
**cap-burnt gate** for transient rows whose ``retry_count`` already
hit :data:`judex.pipeline.scheduler.RETRY_CAP`. Then dispatches one
detached ``judex executar --retentar-de`` per source dir with at least
one *retryable* (REPLAY) row.

**Why state.json, not errors.jsonl?**  ``executar.errors.jsonl`` is a
*derived view* that gets narrowed to the targets of each
``--retentar-de`` pass — the original 1036 unallocated_pid rows can
silently disappear from it after a retry while still being present in
state.json. ``state.json`` is the canonical record (every status +
retry_count for every URL, snapshotted atomically + replayable from
``executar.log.jsonl`` if stale). Reading from canonical means limpar
can't be fooled by a narrowed errors.jsonl.

This module is **pure** for the planner half (``discover_run_dirs``,
``classify_residual``, ``plan_recoveries``, ``format_summary``) — no
subprocesses, no I/O beyond reading state.json. The side-effecting
half is :func:`execute_recoveries`, which spawns one detached child
per source dir.

Spec: ``docs/superpowers/specs/2026-05-03-judex-limpar.md``.
"""

from __future__ import annotations

import enum
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from judex.pipeline.log import classify_unified_error
from judex.pipeline.scheduler import RETRY_CAP
from judex.pipeline.state import PipelineState


STATE_FILENAME = "executar.state.json"
ERRORS_FILENAME = "executar.errors.jsonl"


class Bucket(str, enum.Enum):
    """Recovery action assigned to one non-ok state record.

    Order is the order columns appear in the summary line (kept stable
    so jq pipelines and humans can rely on it).
    """

    REPLAY = "transient"
    CAP_BURNT = "cap_burnt"
    REFETCH_UPSTREAM = "cross_stage"
    PROVIDER_SWITCH = "provider_switched"
    CONFIRMED_UNALLOCATED = "confirmed_unallocated"
    TERMINAL_DROPPED = "terminal_dropped"


@dataclass(frozen=True)
class ErrorRow:
    """One non-ok record from an ``executar.state.json``, tagged with
    its source dir and retry_count.

    ``source_dir`` tells :func:`plan_recoveries` which dir to spawn
    against. ``retry_count`` powers the CAP_BURNT routing.
    """

    source_dir: Path
    kind: str
    classe: str
    processo: int
    status: str
    url: Optional[str]
    retry_count: int


@dataclass(frozen=True)
class Spawn:
    """One detached child invocation planned by :func:`plan_recoveries`.

    ``argv`` is what :func:`execute_recoveries` passes to
    ``subprocess.Popen``. ``saida`` is the per-shard run dir.
    ``source_errors_file`` is the input the child consumes via
    ``--retentar-de``.
    """

    argv: list[str]
    saida: Path
    source_errors_file: Path
    n_replay_rows: int


# Bucket order for summary line — matches enum declaration order.
_BUCKET_ORDER: tuple[Bucket, ...] = (
    Bucket.REPLAY,
    Bucket.CAP_BURNT,
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

    Sharded:    ``[run_dir/shard-a, run_dir/shard-b, ...]`` — one entry
                per shard whose ``executar.state.json`` exists.
    Monolithic: ``[run_dir]`` if ``run_dir/executar.state.json`` exists.
    Empty:      ``[]`` — nothing to recover.

    A shard subdir without state.json is dropped (e.g. a half-launched
    sharded run where some shards never started).
    """
    shard_dirs = sorted(
        d for d in run_dir.glob("shard-*")
        if d.is_dir() and (d / STATE_FILENAME).exists()
    )
    if shard_dirs:
        return shard_dirs

    if (run_dir / STATE_FILENAME).exists():
        return [run_dir]

    return []


# ---------------------------------------------------------------------------
# Classification: state records → buckets
# ---------------------------------------------------------------------------


_TERMINAL_OK_STATUSES: frozenset[str] = frozenset({"ok", "skipped_cached"})


def _iter_non_ok_records(
    state: PipelineState,
    source_dir: Path,
) -> Iterator[ErrorRow]:
    """Yield one :class:`ErrorRow` per non-ok record in state.

    Walks meta → bytes → text per case. Mirrors the per-stage emit
    order used by :func:`judex.pipeline.log._iter_state_errors`, but
    here we don't filter by which targets were in the last
    ``--retentar-de`` scope — every non-ok record in state is yielded.

    ``status=ok`` and ``status=skipped_cached`` are dropped silently.
    """
    # Access internal _cases directly. PipelineState exposes per-record
    # query methods (meta_status, etc.) but no "iterate every case_key"
    # method; using _cases is the same shape ``aggregate_status_counts``
    # uses internally.
    for case_key_str, rec in state._cases.items():  # noqa: SLF001
        classe, _, processo_str = case_key_str.partition("-")
        try:
            processo = int(processo_str)
        except ValueError:
            continue

        if rec.meta is not None:
            status = rec.meta.get("status")
            if status and status not in _TERMINAL_OK_STATUSES:
                yield ErrorRow(
                    source_dir=source_dir,
                    kind="fetch_meta",
                    classe=classe,
                    processo=processo,
                    status=status,
                    url=None,
                    retry_count=int(rec.meta.get("retry_count") or 0),
                )

        for url, entry in (rec.bytes or {}).items():
            status = (entry or {}).get("status")
            if status and status not in _TERMINAL_OK_STATUSES:
                yield ErrorRow(
                    source_dir=source_dir,
                    kind="fetch_bytes",
                    classe=classe,
                    processo=processo,
                    status=status,
                    url=url,
                    retry_count=int(entry.get("retry_count") or 0),
                )

        for url, entry in (rec.text or {}).items():
            status = (entry or {}).get("status")
            if status and status not in _TERMINAL_OK_STATUSES:
                yield ErrorRow(
                    source_dir=source_dir,
                    kind="extract_text",
                    classe=classe,
                    processo=processo,
                    status=status,
                    url=url,
                    retry_count=int(entry.get("retry_count") or 0),
                )


def _bucket_for(row: ErrorRow) -> Optional[Bucket]:
    """Return the Bucket for one ErrorRow, or ``None`` to drop it.

    Composes :func:`classify_unified_error` (a row-shape adapter is
    used since classify_unified_error reads a dict, not an ErrorRow)
    with the override table for actionable terminals + the CAP_BURNT
    gate for transient rows.
    """
    raw = {"status": row.status}
    classified = classify_unified_error(raw)

    if classified == "ok":
        return None

    if classified == "transient":
        if row.retry_count >= RETRY_CAP:
            return Bucket.CAP_BURNT
        return Bucket.REPLAY

    if classified == "cross_stage":
        return Bucket.REFETCH_UPSTREAM

    # classified == "terminal" — actionable overrides
    if row.kind == "extract_text" and row.status == "empty":
        return Bucket.PROVIDER_SWITCH
    if row.kind == "fetch_meta" and row.status == "unallocated_pid":
        return Bucket.CONFIRMED_UNALLOCATED
    return Bucket.TERMINAL_DROPPED


def _empty_buckets() -> dict[Bucket, list[ErrorRow]]:
    return {b: [] for b in _BUCKET_ORDER}


def classify_residual(dirs: list[Path]) -> dict[Bucket, list[ErrorRow]]:
    """Walk every dir's ``executar.state.json``, partition by bucket.

    The returned dict has every Bucket key populated (possibly empty).
    """
    buckets = _empty_buckets()

    for source_dir in dirs:
        state = PipelineState.load(source_dir / STATE_FILENAME)
        for row in _iter_non_ok_records(state, source_dir):
            bucket = _bucket_for(row)
            if bucket is None:
                continue
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

    CAP_BURNT rows do **not** trigger a spawn — re-seeding them would
    burn portal/sistemas/ocr-pool wall on tasks the seed builder will
    immediately filter out (``_is_retryable_status`` enforces
    ``retry_count < RETRY_CAP``). They need explicit cap-bypass via
    the legacy ``extrair-pecas --forcar`` path or manual state surgery.

    Other terminal/cross_stage buckets are surfaced in the summary but
    not auto-dispatched in v1.
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
    ``--dry-run``. Counts in fixed bucket order; ``·`` (U+00B7)
    separators match ``judex acompanhar``'s aggregate prefix style.
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
    pids_path: Path
    pids: list[int] = field(default_factory=list)


def execute_recoveries(
    plan: list[Spawn],
    pids_path: Path,
) -> ExecuteResult:
    """Spawn each :class:`Spawn` detached, append to ``<saida>/driver.log``,
    write a ``limpar.pids`` file at ``pids_path``.

    **Why driver.log (append) instead of limpar.log:**
    ``judex acompanhar`` tails ``shard-*/driver.log``. If limpar wrote
    to ``limpar.log`` (separate file), the operator running
    ``acompanhar`` after a limpar pass would see only the *original*
    sweep's tail — blind to the recovery activity. Appending to
    driver.log keeps the run dir's monitoring contract uniform: one
    log file per shard, all activity (original + recovery passes)
    visible to existing tooling.

    Children are detached via ``start_new_session=True``. Returns
    immediately after recording PIDs.
    """
    result = ExecuteResult(pids_path=pids_path)

    pids_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    for spawn in plan:
        log_path = spawn.saida / "driver.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
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
