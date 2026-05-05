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
    DISMISSED = "dismissed"
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
    ``source_errors_file`` is the input the child consumes (the
    pre-existing ``executar.errors.jsonl`` for REPLAY spawns; a
    materialised URL-list or CSV for PROVIDER_SWITCH / REFETCH_UPSTREAM
    spawns).

    ``materialized_content`` carries the *intended* file content for
    spawns that need to write a fresh input file before launch. When
    non-None, :func:`execute_recoveries` writes it to
    ``source_errors_file`` just before spawning. ``plan_recoveries``
    keeps this field as data only — no disk side effects under dry-run.
    """

    argv: list[str]
    saida: Path
    source_errors_file: Path
    n_replay_rows: int
    materialized_content: Optional[str] = None


# Bucket order for summary line — matches enum declaration order.
_BUCKET_ORDER: tuple[Bucket, ...] = (
    Bucket.REPLAY,
    Bucket.CAP_BURNT,
    Bucket.REFETCH_UPSTREAM,
    Bucket.PROVIDER_SWITCH,
    Bucket.DISMISSED,
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


# extract_text statuses that route to PROVIDER_SWITCH (kind=terminal in
# the classifier, but actionable via a different OCR provider). The
# destination provider depends on which status: ``empty`` → chandra
# (beefier OCR for scanned PDFs); ``outlier_skipped`` → tesseract local
# (the only provider without the cloud body cap).
_PROVIDER_SWITCH_STATUSES: frozenset[str] = frozenset({"empty", "outlier_skipped"})

# Status → destination provider for PROVIDER_SWITCH dispatch. Mirrors
# the recipe table in ``error_triage._EXTRAIR_STATUS_OVERRIDES`` but
# typed for direct lookup; keeping both in sync is pinned by the
# limpar dispatch tests + the error_triage recipe tests.
_PROVIDER_SWITCH_DESTINATIONS: dict[str, str] = {
    "empty": "chandra",
    "outlier_skipped": "tesseract",
}


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
    gate for transient rows + the DISMISSED short-circuit for URLs an
    operator marked as known-broken via ``judex peca-dismiss``.
    """
    # Dismissal short-circuit: if an operator marked this URL as
    # known-broken, route to DISMISSED regardless of underlying status.
    # Meta-stage rows have ``url=None`` and can't be dismissed.
    if row.url is not None:
        from judex.utils import peca_cache
        if peca_cache.is_dismissed(row.url):
            return Bucket.DISMISSED

        # Recovery short-circuit: if a previous PROVIDER_SWITCH dispatch
        # already wrote new text via re-extrair, the extractor sidecar
        # carries the destination provider for this status. The
        # state.json still records the old ``empty`` / ``outlier_skipped``
        # status (re-extrair doesn't touch state.json — it writes to
        # peca_cache directly), but the work is done. Drop the row so
        # the convergence loop in ``run_until_stable`` sees the bucket
        # shrink between passes.
        if (row.kind == "extract_text"
                and row.status in _PROVIDER_SWITCH_STATUSES):
            dest = _PROVIDER_SWITCH_DESTINATIONS.get(row.status)
            if dest and peca_cache.read_extractor(row.url) == dest:
                return None

    raw = {"status": row.status, "kind": row.kind}
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
    if row.kind == "extract_text" and row.status in _PROVIDER_SWITCH_STATUSES:
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


def _urls_file_path(source_dir: Path, status: str) -> Path:
    """Where the URL-list file *will* land for a (source_dir, status)."""
    return source_dir / f"limpar-{status}.urls.txt"


def _refetch_csv_path(source_dir: Path) -> Path:
    """Where the refetch CSV *will* land for a source_dir."""
    return source_dir / "limpar-refetch.csv"


def _build_urls_content(rows: list[ErrorRow]) -> str:
    """Render a URL-list payload: one URL per line, deduped, trailing newline."""
    seen: set[str] = set()
    lines: list[str] = []
    for row in rows:
        if row.url and row.url not in seen:
            seen.add(row.url)
            lines.append(row.url)
    return ("\n".join(lines) + "\n") if lines else ""


def _build_cases_csv_content(rows: list[ErrorRow]) -> str:
    """Render a (classe,processo) CSV payload, deduped on the pair."""
    seen: set[tuple[str, int]] = set()
    lines = ["classe,processo"]
    for row in rows:
        pair = (row.classe, row.processo)
        if pair not in seen:
            seen.add(pair)
            lines.append(f"{row.classe},{row.processo}")
    return "\n".join(lines) + "\n"


def _plan_replay_spawns(
    rows: list[ErrorRow], *, provedor: str,
) -> list[Spawn]:
    """REPLAY → one ``executar --retentar-de`` per source dir."""
    rows_per_dir: dict[Path, list[ErrorRow]] = {}
    for row in rows:
        rows_per_dir.setdefault(row.source_dir, []).append(row)

    plans: list[Spawn] = []
    for source_dir in sorted(rows_per_dir.keys()):
        bucket_rows = rows_per_dir[source_dir]
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
            n_replay_rows=len(bucket_rows),
        ))
    return plans


def _plan_provider_switch_spawns(rows: list[ErrorRow]) -> list[Spawn]:
    """PROVIDER_SWITCH → one ``re-extrair`` per (source_dir, status).

    Different statuses route to different providers (empty→chandra,
    outlier_skipped→tesseract), so a single dispatch can't cover both;
    we split per status. URL-scoped via re-extrair so meta + bytes
    cache-skips are honoured (only the text stage runs). The URL-list
    file contents are computed here as ``materialized_content``; the
    actual write happens in :func:`execute_recoveries` so dry-run stays
    side-effect-free.
    """
    grouped: dict[tuple[Path, str], list[ErrorRow]] = {}
    for row in rows:
        grouped.setdefault((row.source_dir, row.status), []).append(row)

    plans: list[Spawn] = []
    for (source_dir, status), group in sorted(
        grouped.items(), key=lambda kv: (kv[0][0], kv[0][1]),
    ):
        provider = _PROVIDER_SWITCH_DESTINATIONS.get(status)
        if provider is None:
            continue  # status not in the dispatch table — skip safely
        urls_file = _urls_file_path(source_dir, status)
        content = _build_urls_content(group)
        argv = [
            "uv", "run", "judex", "re-extrair", str(urls_file),
            "--provedor", provider,
            "--forcar",
        ]
        plans.append(Spawn(
            argv=argv,
            saida=source_dir,
            source_errors_file=urls_file,
            n_replay_rows=len(group),
            materialized_content=content,
        ))
    return plans


def _plan_refetch_upstream_spawns(rows: list[ErrorRow]) -> list[Spawn]:
    """REFETCH_UPSTREAM → one ``executar --csv`` per source dir.

    no_bytes means the bytes never landed; rerunning ``executar`` over
    the affected (classe, processo) cases lets the runner cache-skip
    meta + the bytes that *did* succeed and refetch only the missing
    ones. No --forcar (caches honoured). CSV contents computed as
    ``materialized_content``; written by :func:`execute_recoveries`."""
    rows_per_dir: dict[Path, list[ErrorRow]] = {}
    for row in rows:
        rows_per_dir.setdefault(row.source_dir, []).append(row)

    plans: list[Spawn] = []
    for source_dir in sorted(rows_per_dir.keys()):
        group = rows_per_dir[source_dir]
        csv_file = _refetch_csv_path(source_dir)
        content = _build_cases_csv_content(group)
        argv = [
            "uv", "run", "judex", "executar",
            "--csv", str(csv_file),
            "--saida", str(source_dir),
            "--nao-perguntar",
        ]
        plans.append(Spawn(
            argv=argv,
            saida=source_dir,
            source_errors_file=csv_file,
            n_replay_rows=len(group),
            materialized_content=content,
        ))
    return plans


def plan_recoveries(
    buckets: dict[Bucket, list[ErrorRow]],
    *,
    provedor: str,
) -> list[Spawn]:
    """Return one :class:`Spawn` per actionable bucket per source dir.

    Dispatched buckets (each materialises its own input file in the
    source dir before the spawn argv is constructed):

    - ``REPLAY`` → ``executar --retentar-de errors.jsonl`` (the
      original v1 path; ``provedor`` argument is plumbed here).
    - ``PROVIDER_SWITCH`` → ``re-extrair --provedor <X> --forcar``
      where X depends on status (chandra for empty, tesseract for
      outlier_skipped). Split per (dir, status) since different
      statuses can't share a provider.
    - ``REFETCH_UPSTREAM`` → ``executar --csv <built-from-rows>``
      (no --forcar; cache-skips honour the bytes that did land).

    Skipped buckets:

    - ``CAP_BURNT`` — re-seeding burns wall on tasks the seed builder
      filters out (``_is_retryable_status`` enforces
      ``retry_count < RETRY_CAP``); needs explicit cap-bypass.
    - ``CONFIRMED_UNALLOCATED`` / ``TERMINAL_DROPPED`` — terminal-
      confirmed; retry returns the same outcome.
    """
    plans: list[Spawn] = []
    plans.extend(_plan_replay_spawns(buckets[Bucket.REPLAY], provedor=provedor))
    plans.extend(_plan_provider_switch_spawns(buckets[Bucket.PROVIDER_SWITCH]))
    plans.extend(_plan_refetch_upstream_spawns(buckets[Bucket.REFETCH_UPSTREAM]))
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
        # Materialise the input file (URL list / CSV) for dispatches
        # that need a fresh one. REPLAY spawns leave this as None and
        # consume the pre-existing executar.errors.jsonl.
        if spawn.materialized_content is not None:
            spawn.source_errors_file.parent.mkdir(parents=True, exist_ok=True)
            spawn.source_errors_file.write_text(
                spawn.materialized_content, encoding="utf-8"
            )

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


# ---------------------------------------------------------------------------
# Loop-until-stable: dispatch + wait + re-classify until convergence
# ---------------------------------------------------------------------------


def wait_for_pids(pids: list[int], *, poll_interval: float = 5.0) -> None:
    """Block until none of ``pids`` are running. Polls with ``os.kill(pid, 0)``
    which returns silently if the process is alive and raises
    ``ProcessLookupError`` once it exits. No-op on an empty list.

    The poll-vs-wait choice is intentional: ``os.waitpid`` only works on
    direct children, but the ``execute_recoveries`` spawns are detached
    via ``start_new_session=True`` — the limpar parent isn't their
    parent any more, so ``waitpid`` would return immediately with
    ECHILD. ``kill -0`` works regardless of process tree.
    """
    import os
    import time

    remaining = set(pids)
    while remaining:
        time.sleep(poll_interval)
        for pid in list(remaining):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                remaining.discard(pid)


# Buckets that contribute to "actionable residual" — these are what the
# convergence loop tries to shrink. Terminal/dismissed/cap-burnt are
# excluded: they're stable-by-design, not work to do.
_ACTIONABLE_BUCKETS: tuple[Bucket, ...] = (
    Bucket.REPLAY,
    Bucket.REFETCH_UPSTREAM,
    Bucket.PROVIDER_SWITCH,
)


def _count_actionable(buckets: dict[Bucket, list[ErrorRow]]) -> int:
    return sum(len(buckets[b]) for b in _ACTIONABLE_BUCKETS)


@dataclass
class LoopResult:
    """Final state after :func:`run_until_stable` exits."""

    final_buckets: dict[Bucket, list[ErrorRow]]
    passes_run: int
    converged: bool        # True if final actionable count == 0
    stopped_for_no_progress: bool
    stopped_for_max_passes: bool


def run_until_stable(
    run_dir: Path,
    *,
    provedor: str = "auto",
    max_passes: int = 3,
    poll_interval: float = 5.0,
    on_pass_start=None,        # optional: callable(pass_n, actionable_count)
    on_pass_end=None,          # optional: callable(pass_n, n_dispatched, pids)
) -> LoopResult:
    """Run ``limpar --apply`` in a loop until residuals stop shrinking
    or ``max_passes`` is hit.

    Each pass: classify → plan → spawn detached children → wait for
    them → re-classify. Convergence is "non-empty actionable residual
    that didn't shrink between this pass and the previous." That stop
    condition catches both the success case (residual went to 0) and
    the stuck case (recovery dispatched but produced the same residual,
    so further passes won't help).

    ``provedor`` is forwarded to REPLAY's ``--retentar-de`` dispatches
    only — PROVIDER_SWITCH and REFETCH_UPSTREAM dispatches use their
    recipe-prescribed providers regardless.
    """
    last_actionable: Optional[int] = None
    last_buckets: Optional[dict[Bucket, list[ErrorRow]]] = None

    for pass_n in range(1, max_passes + 1):
        dirs = discover_run_dirs(run_dir)
        buckets = classify_residual(dirs)
        actionable = _count_actionable(buckets)
        last_buckets = buckets

        if on_pass_start is not None:
            on_pass_start(pass_n, actionable)

        if actionable == 0:
            return LoopResult(
                final_buckets=buckets, passes_run=pass_n,
                converged=True,
                stopped_for_no_progress=False,
                stopped_for_max_passes=False,
            )

        if last_actionable is not None and actionable >= last_actionable:
            return LoopResult(
                final_buckets=buckets, passes_run=pass_n,
                converged=False,
                stopped_for_no_progress=True,
                stopped_for_max_passes=False,
            )

        plan = plan_recoveries(buckets, provedor=provedor)
        if not plan:
            return LoopResult(
                final_buckets=buckets, passes_run=pass_n,
                converged=False,
                stopped_for_no_progress=True,
                stopped_for_max_passes=False,
            )

        pids_path = run_dir / f"limpar-pass-{pass_n}.pids"
        result = execute_recoveries(plan, pids_path)

        if on_pass_end is not None:
            on_pass_end(pass_n, len(result.pids), result.pids)

        wait_for_pids(result.pids, poll_interval=poll_interval)
        last_actionable = actionable

    return LoopResult(
        final_buckets=last_buckets or {b: [] for b in _BUCKET_ORDER},
        passes_run=max_passes,
        converged=False,
        stopped_for_no_progress=False,
        stopped_for_max_passes=True,
    )
