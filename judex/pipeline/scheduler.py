"""Three-pool asyncio scheduler for the unified pipeline.

Production version of the prototype in ``scratch/pipeline_prototype.py``.
The asyncio core is the same shape — three queues, three pool worker
coroutines, ``asyncio.to_thread`` to bridge sync handlers — but with
production concerns layered on:

* **State persistence.** Every task outcome lands in
  :class:`PipelineState` (the handler does this); a background
  snapshotter flushes it to disk every N seconds.
* **Signal handling.** SIGTERM/SIGINT trigger graceful shutdown via
  ``judex.sweeps.shared.install_signal_handlers``; workers check
  ``shutdown_requested`` between tasks and exit without dequeueing
  more.
* **Resume.** Seeds are filtered against state — meta tasks whose
  status is already ``ok`` are skipped, and so on.

The scheduler is single-event-loop. Concurrency comes from
``asyncio.Semaphore`` per pool. Sync work runs on the default
threadpool via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

from judex.pipeline.handlers import HandlerFn
from judex.pipeline.log import PipelineLog, make_log_record
from judex.pipeline.models import Counters, PoolConfig, PoolName, Task, TaskStatus
from judex.pipeline.pools import Pool, build_pools
from judex.pipeline.state import PipelineState
from judex.sweeps.shared import CliffDetector, regime_kwargs


log = logging.getLogger(__name__)


@dataclass
class SchedulerConfig:
    pools: list[PoolConfig]
    handlers: dict[str, HandlerFn]
    queue_maxsize: int = 1024
    snapshot_interval_seconds: float = 5.0
    progress_interval_seconds: float = 10.0
    n_targets: int = 0
    """Case-count denominator for the periodic progress line. The
    portal pool runs one fetch_meta task per case, so n_targets is the
    natural denominator for portal-pool progress. Setting this to zero
    (the unknown default) suppresses the percentage display."""
    log_path: Optional["Path"] = None
    """Path to ``executar.log.jsonl``. When set, every task outcome is
    appended (fsynced) to this file as one JSON row — the canonical
    durable record for hard-kill recovery and post-hoc analysis. When
    ``None`` (default), no log file is written; useful for unit tests
    that mock the scheduler in-memory."""
    cliff_window: int = 50
    """Rolling-window size for the per-pool CliffDetector. Mirrors the
    legacy varrer/baixar default. Set to 0 to disable regime stamping
    (cheap but loses the cliff-trajectory signal in
    ``executar.log.jsonl``)."""


@dataclass
class RunResult:
    counters: dict[PoolName, Counters]
    wall_seconds: float
    shutdown_requested: bool = False


RETRY_CAP = 2
"""Maximum number of retry cycles per task. Inherited from ADR-0004's
"cap of 2 retry cycles per stage" contract (now per-Task). After
``retry_count`` reaches ``RETRY_CAP``, the seed builder stops
re-seeding the task even if its status is otherwise transient — the
operator is expected to surface the systemic issue (proxy pool dead,
WAF rolling block, OCR cluster saturated) rather than burn a fourth
attempt. The breaker tripping at the per-Pool **Transient gate** (2%)
is the structural early-warning; the per-Task cap is the absolute
ceiling. See ``docs/adr/0005-unified-pipeline.md`` § Open issue #1
(now resolved)."""


def _is_retryable_status(
    kind: str,
    status: Optional[TaskStatus],
    retry_count: int = 0,
) -> bool:
    """Should the resume builder re-seed a task with this state status?

    Mirrors the policy in :mod:`judex.sweeps.error_triage` translated
    to the unified pipeline's ``TaskStatus`` vocabulary. The legacy
    classifier works on errors.jsonl row dicts; the unified pipeline
    has a typed status enum, so the rules collapse to a small table.

    * ``None`` (never attempted) → retry (first-time work).
    * ``ok`` → not retryable; caller filters before asking.
    * ``fetch_meta``: ``http_error`` (WAF / timeout / SSL) is transient;
      ``unallocated_pid`` is terminal (case genuinely doesn't exist).
    * ``fetch_bytes``: ``http_error`` is transient; ``empty``
      (unsupported magic bytes from STF) is terminal.
    * ``extract_text``: ``provider_error`` is transient (provider
      hiccups, network flakes); ``empty`` (PDF really has no text)
      and ``no_bytes`` (cross-stage — bytes side needs a re-fetch,
      not a re-extract) are terminal at this stage.
    * Anything unknown → terminal (conservative — error_triage's
      default-to-terminal rule: better to surface in the residual
      report than to churn the WAF on an unmapped failure).

    On top of the kind/status table, the per-Task **retry cap**
    (:data:`RETRY_CAP`, =2) gates: a task whose ``retry_count``
    has reached the cap is no longer retryable even if its status
    would otherwise be transient. This honors ADR-0004's "cap of 2
    retry cycles" contract, now scoped per-Task instead of per-stage.

    Without this filter, the seed builder re-enqueues every non-ok
    task on every resume, including terminal ones like
    ``unallocated_pid`` and indefinitely-retrying transient failures.
    At year-corpus scale that burns measurable portal-pool wall on
    cases that will never become ok.
    """
    if status is None:
        return True
    if status == "ok":
        return False
    is_retryable_status = (
        (kind == "fetch_meta" and status == "http_error")
        or (kind == "fetch_bytes" and status == "http_error")
        or (kind == "extract_text" and status == "provider_error")
    )
    if not is_retryable_status:
        return False
    return retry_count < RETRY_CAP


def seeds_from_targets(
    targets: list[tuple[str, int]],
    state: PipelineState,
) -> list[Task]:
    """Build the initial seed-task list, filtered by state.

    Cases whose ``fetch_meta`` is already ``ok`` are NOT seeded with
    a fetch_meta task — but the scheduler still needs to pick up
    their downstream work (bytes/text). That work is found by the
    handlers themselves on resume: the scheduler enqueues fresh
    ``fetch_bytes`` and ``extract_text`` tasks for every URL the
    state has seen whose status is non-ok AND classified retryable.
    Terminal failures (``unallocated_pid``, ``empty``, ``no_bytes``)
    are skipped — see ``_is_retryable_status``.
    """
    seeds: list[Task] = []

    for case_key in targets:
        meta_status = state.meta_status(case_key)
        if meta_status == "ok":
            for url in state.known_bytes_urls(case_key):
                # ``doc_type`` was tagged onto the bytes record by the
                # meta handler at first emission. Carry it forward into
                # any re-seeded successor so ``--provedor auto`` routes
                # consistently across resumes.
                doc_type = state.bytes_doc_type(case_key, url=url)
                bytes_status = state.bytes_status(case_key, url=url)
                if bytes_status != "ok":
                    bytes_rc = state.bytes_retry_count(case_key, url=url)
                    if _is_retryable_status("fetch_bytes", bytes_status, bytes_rc):
                        seeds.append(
                            Task(
                                kind="fetch_bytes",
                                pool="sistemas",
                                payload={"url": url, "doc_type": doc_type},
                                case_key=case_key,
                            )
                        )
                    # bytes is non-ok (whether retryable or terminal):
                    # there's no point checking text — text on top of
                    # non-ok bytes can't be ``ok`` either.
                    continue
                # bytes ok; check text. (No required_extractor here —
                # caller can use --forcar to invalidate.)
                text_status = state.text_status(case_key, url=url)
                text_rc = state.text_retry_count(case_key, url=url)
                if text_status != "ok" and _is_retryable_status(
                    "extract_text", text_status, text_rc,
                ):
                    seeds.append(
                        Task(
                            kind="extract_text",
                            pool="ocr",
                            payload={"url": url, "doc_type": doc_type},
                            case_key=case_key,
                        )
                    )
        else:
            meta_rc = state.meta_retry_count(case_key)
            if _is_retryable_status("fetch_meta", meta_status, meta_rc):
                seeds.append(
                    Task(
                        kind="fetch_meta",
                        pool="portal",
                        payload={},
                        case_key=case_key,
                    )
                )
            # else: meta status is non-ok and terminal (unallocated_pid,
            # or http_error past RETRY_CAP) — skip the case entirely.

    return seeds


# ---------------------------------------------------------------------------
# Scheduler internals
# ---------------------------------------------------------------------------


@dataclass
class _SchedulerRuntime:
    queues: dict[PoolName, asyncio.Queue]
    pools: dict[PoolName, Pool]
    counters: dict[PoolName, Counters]
    state: PipelineState  # for breaker readback after each task
    log: Optional[PipelineLog] = None
    """Append-only log writer. ``None`` in unit tests that don't want
    to materialise a log file; production runs always pass one through
    :class:`SchedulerConfig.log_path`."""
    cliff_detectors: dict[PoolName, CliffDetector] = field(default_factory=dict)
    """Per-pool CliffDetector. Stamped onto every log row so post-hoc
    ``analisar-regimes`` reconstructs the regime trajectory without
    hand-rolling jq queries against the log file."""
    in_flight: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def _read_task_outcome(state: PipelineState, task: Task) -> Optional[TaskStatus]:
    """Look up the status the handler just recorded for ``task``.

    The handler is expected to record exactly one outcome before
    returning (every code path in ``handlers.py`` does so). This
    function is the breaker's view of that record.
    """
    if task.kind == "fetch_meta":
        return state.meta_status(task.case_key)
    if task.kind == "fetch_bytes":
        return state.bytes_status(task.case_key, url=task.payload.get("url", ""))
    if task.kind == "extract_text":
        return state.text_status(task.case_key, url=task.payload.get("url", ""))
    return None


def _read_task_error(state: PipelineState, task: Task) -> Optional[str]:
    """Project the per-record ``error`` string from state into the log row.

    Symmetric with :func:`_read_task_outcome` — the same lookup, but
    pulling the ``error`` field instead of ``status``. Used by the
    log-emission path so each row carries the concrete failure message
    error_triage classifies on.
    """
    classe, processo = task.case_key
    rec = state._cases.get(f"{classe}-{processo}")  # noqa: SLF001
    if rec is None:
        return None
    if task.kind == "fetch_meta":
        return rec.meta.get("error") if rec.meta else None
    url = task.payload.get("url", "")
    if task.kind == "fetch_bytes":
        entry = rec.bytes.get(url)
        return entry.get("error") if entry else None
    if task.kind == "extract_text":
        entry = rec.text.get(url)
        return entry.get("error") if entry else None
    return None


def _read_task_extractor(state: PipelineState, task: Task) -> Optional[str]:
    """Project the per-record ``extractor`` label (extract_text only)."""
    if task.kind != "extract_text":
        return None
    classe, processo = task.case_key
    rec = state._cases.get(f"{classe}-{processo}")  # noqa: SLF001
    if rec is None:
        return None
    entry = rec.text.get(task.payload.get("url", ""))
    return entry.get("extractor") if entry else None


def _read_task_chars(state: PipelineState, task: Task) -> Optional[int]:
    """Project the per-record ``chars`` count (extract_text only).

    Set on ok / empty terminal outcomes by the OCR + RTF handlers; left
    None on no_bytes / provider_error and on cache-fast skipped_cached
    (we don't pay to decompress just for the tail line). The tail line
    renderer treats None as "omit the chars suffix".
    """
    if task.kind != "extract_text":
        return None
    classe, processo = task.case_key
    rec = state._cases.get(f"{classe}-{processo}")  # noqa: SLF001
    if rec is None:
        return None
    entry = rec.text.get(task.payload.get("url", ""))
    return entry.get("chars") if entry else None


def _read_task_retry_count(state: PipelineState, task: Task) -> int:
    """Project the per-record ``retry_count`` value the live mutator
    just wrote.

    The log row carries this so ADR-0006 § D4 / E1 replay can preserve
    it on resume rather than re-incrementing through the live mutator.
    """
    if task.kind == "fetch_meta":
        return state.meta_retry_count(task.case_key)
    url = task.payload.get("url")
    if url is None:
        return 0
    if task.kind == "fetch_bytes":
        return state.bytes_retry_count(task.case_key, url=url)
    if task.kind == "extract_text":
        return state.text_retry_count(task.case_key, url=url)
    return 0


def _short_identifier(task: Task) -> str:
    """Compact per-task id for the tail log, mirroring legacy
    ``judex.utils.log_render.compact_target_id`` shape:

    * ``fetch_meta``: ``"HC 187634"``
    * ``fetch_bytes`` / ``extract_text``: ``"HC 187634 a3f5b2e"`` —
      the sha7 of the URL is stable across resumes and short enough
      to keep tail-log lines aligned.

    Full URL stays in ``executar.state.json`` for any downstream
    tooling that needs it.
    """
    classe, processo = task.case_key
    if task.kind == "fetch_meta":
        return f"{classe} {processo}"
    from judex.utils.log_render import compact_target_id
    return compact_target_id(
        task.payload.get("url", ""), classe=classe, processo_id=processo,
    )


async def _run_one(
    task: Task,
    handler: HandlerFn,
    runtime: _SchedulerRuntime,
) -> None:
    """Run one task under its pool semaphore. Records timing,
    emits successors, feeds the per-pool circuit breaker, stamps the
    CliffDetector regime onto the log row, and appends one JSONL row
    to ``executar.log.jsonl`` (when configured). Handlers do not raise
    — they record their own error outcomes to state.
    """
    pool = runtime.pools[task.pool]
    runtime.counters[task.pool].started += 1
    try:
        async with pool.semaphore:
            # Start the clock AFTER the semaphore so wall_s reflects
            # handler wall, not handler wall + queue-wait. The legacy
            # error-was a `t0` captured before `async with sem:` — every
            # task in a backed-up queue then carried its queue-position
            # as inflated wall, which falsely promoted the CliffDetector
            # regime and double-counted into busy_seconds.
            handler_t0 = time.monotonic()
            successors = await asyncio.to_thread(handler, task)
            elapsed = time.monotonic() - handler_t0
            runtime.counters[task.pool].busy_seconds += elapsed
        runtime.counters[task.pool].finished += 1

        # Feed the breaker. ``ok`` if the handler recorded "ok" for
        # this task; anything else (http_error, no_bytes, empty,
        # provider_error, unallocated_pid) counts as an error from
        # the breaker's perspective. None means the handler didn't
        # record (shouldn't happen given the handlers.py contract);
        # we treat None as "error" defensively.
        outcome = _read_task_outcome(runtime.state, task)
        pool.record_outcome(ok=(outcome == "ok"))

        # Feed the per-pool CliffDetector. ``observe`` takes a status
        # string + wall_s; we use the typed outcome to map onto the
        # legacy "ok" / non-"ok" axis the detector knows. The reading
        # is then stamped onto the log row so analisar-regimes can
        # reconstruct the trajectory post-hoc.
        regime_reading = None
        detector = runtime.cliff_detectors.get(task.pool)
        if detector is not None:
            detector.observe(outcome or "error", elapsed)
            regime_reading = detector.regime()

        # Per-task tail line. Format mirrors legacy
        # ``judex.utils.log_render.render_target_line``:
        #   HH:MM:SS  ✓ ok        [portal]    HC 187634          ·  3.21s
        # Timestamp first, glyph + status word (padded to 8 chars so
        # most lines align), pool tag, compact identifier, wall.
        # extract_text rows extend with `· {extractor} {chars}ch` so the
        # operator sees provider routing + OCR output volume in real time
        # without having to read the JSONL log.
        from judex.utils.log_render import _style_for, _now_hms
        glyph, _ = _style_for(outcome or "?")
        line_extractor = _read_task_extractor(runtime.state, task)
        line_chars = _read_task_chars(runtime.state, task)
        suffix = ""
        if task.kind == "extract_text" and line_extractor:
            if line_chars is not None:
                suffix = f"  ·  {line_extractor} {line_chars:,}ch"
            else:
                suffix = f"  ·  {line_extractor}"
        log.info(
            "%s  %s %-8s  [%-8s]  %-20s  ·  %.2fs%s",
            _now_hms(), glyph, outcome or "?",
            task.pool, _short_identifier(task), elapsed, suffix,
        )

        # Append-only log row. Carries everything analisar-regimes,
        # error_triage, and --retentar-de need. fsynced per row.
        if runtime.log is not None:
            error_msg = _read_task_error(runtime.state, task)
            retry_count = _read_task_retry_count(runtime.state, task)
            rkw = regime_kwargs(regime_reading)
            record = make_log_record(
                task=task,
                run_id=runtime.state.run_id,
                status=outcome or "error",
                wall_s=elapsed,
                retry_count=retry_count,
                error=error_msg,
                extractor=line_extractor,
                chars=line_chars,
                regime=rkw["regime"],
                regime_fail_rate=rkw["regime_fail_rate"],
                regime_p95_wall_s=rkw["regime_p95_wall_s"],
                regime_promoted_by=rkw["regime_promoted_by"],
            )
            try:
                await asyncio.to_thread(runtime.log.append, record)
            except Exception:  # noqa: BLE001
                # Log-write failures are surfaced but never raised: the
                # in-memory state still records the outcome, the
                # snapshotter will flush it, and the next run can pick
                # up. Losing the log row is a degraded mode, not a fail.
                log.exception("[%s] log append failed for %s", task.pool, task.id)

        for follow in successors:
            runtime.in_flight[follow.pool] += 1
            await runtime.queues[follow.pool].put(follow)
    except Exception as exc:  # noqa: BLE001 -- defensive; handlers shouldn't raise
        runtime.counters[task.pool].failed += 1
        pool.record_outcome(ok=False)
        log.exception("[%s] handler raised for %s: %r", task.pool, task.id, exc)
    finally:
        runtime.in_flight[task.pool] -= 1


async def _pool_worker(
    pool: PoolConfig,
    runtime: _SchedulerRuntime,
    handlers: dict[str, HandlerFn],
    shutdown_event: asyncio.Event,
) -> None:
    """Drain this pool's queue until shutdown sentinel. Each task is
    dispatched as a background ``asyncio.Task`` so the pool worker
    doesn't block on the handler's wall — concurrency comes from the
    semaphore inside ``_run_one``.
    """
    queue = runtime.queues[pool.name]
    pending: set[asyncio.Task] = set()
    while True:
        if shutdown_event.is_set():
            break
        try:
            # Bounded wait so the worker can periodically observe
            # shutdown_event even when the queue is idle.
            task = await asyncio.wait_for(queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        if task is None:
            break
        coro = _run_one(task, handlers[task.kind], runtime)
        bg = asyncio.create_task(coro)
        pending.add(bg)
        bg.add_done_callback(pending.discard)
        queue.task_done()

    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _drain_watcher(
    runtime: _SchedulerRuntime,
    shutdown_event: asyncio.Event,
    poll_seconds: float = 0.25,
) -> None:
    """Push shutdown sentinels once every queue is empty and no tasks
    are in flight. Stops the workers from blocking on ``queue.get``
    forever once the DAG is fully drained.
    """
    while not shutdown_event.is_set():
        await asyncio.sleep(poll_seconds)
        queues_empty = all(q.empty() for q in runtime.queues.values())
        no_inflight = all(v == 0 for v in runtime.in_flight.values())
        if queues_empty and no_inflight:
            for q in runtime.queues.values():
                await q.put(None)
            return


async def _periodic_snapshotter(
    state: PipelineState,
    interval: float,
    shutdown_event: asyncio.Event,
) -> None:
    """Flush state to disk every ``interval`` seconds, plus once on
    shutdown. The on-shutdown flush is also called by ``run_pipeline``
    in a finally block, so a process kill during the sleep doesn't
    lose the most-recent in-memory state.
    """
    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        try:
            await asyncio.to_thread(state.snapshot)
        except Exception:  # noqa: BLE001
            log.exception("snapshot failed; will retry next interval")


async def _periodic_progress(
    runtime: _SchedulerRuntime,
    interval: float,
    shutdown_event: asyncio.Event,
    started_at: float,
    n_targets: int = 0,
) -> None:
    """Print a multi-stage progress summary every ``interval`` seconds.

    Renders via ``render_pipeline_progress_line`` so meta / bytes / text
    each show their full status mix (``ok``, ``empty``, ``provider_error``,
    …) instead of collapsing to ``finished/failed``. Same shape as the
    sharded ``follow_run.format_aggregate_line``: meta carries a
    percentage (denominator is ``n_targets``, known up front); bytes and
    text show absolute counts (their denominators grow as meta progresses,
    so a percentage there would lie until meta finishes).

    ETA is OCR-driven — text extraction is the slowest stage in practice;
    the meta-rate ETA the legacy renderer used would zero out the moment
    meta completed even when 6,000 PDFs are still queued for OCR.
    """
    from judex.utils.log_render import render_pipeline_progress_line

    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        elapsed = time.monotonic() - started_at
        portal = runtime.counters["portal"]
        ocr_c = runtime.counters["ocr"]

        # OCR rate drives ETA — text is the slowest stage. Backlog is
        # whatever has been seen by OCR but not finished, plus whatever
        # bytes have completed and will become text tasks. We use OCR's
        # own (started - finished) as a conservative backlog proxy:
        # accurate once meta is done, optimistic-but-monotone otherwise.
        ocr_rate = ocr_c.finished / elapsed if elapsed > 0 else 0.0
        ocr_remaining = max(0, ocr_c.started - ocr_c.finished)
        eta_min: Optional[float]
        if ocr_rate > 0:
            eta_min = ocr_remaining / ocr_rate / 60.0
        else:
            eta_min = None

        # Cases/s = portal rate (meta-finish per second). Operator
        # already reads cases/s as the cross-pipeline cadence number.
        cases_rate = portal.finished / elapsed if elapsed > 0 else 0.0

        agg = runtime.state.aggregate_status_counts()
        log.info(
            render_pipeline_progress_line(
                n_targets=n_targets,
                processos=agg["processos"],
                pecas=agg["pecas"],
                text=agg["text"],
                pecas_total=agg["pecas_total"],
                text_total=agg["text_total"],
                rate_per_sec=cases_rate,
                eta_min=eta_min,
                eta_basis="OCR" if eta_min is not None else None,
                use_color=False,  # log goes to file, not tty
            )
        )


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------


async def run_scheduler(
    seed_tasks: list[Task],
    config: SchedulerConfig,
    state: PipelineState,
    shutdown_check: Optional[Callable[[], bool]] = None,
) -> RunResult:
    """Run the scheduler to completion or until shutdown.

    ``shutdown_check`` is polled once per worker tick; if it returns
    ``True``, all workers wind down gracefully (in-flight tasks
    finish, state is flushed). The default implementation reads
    ``judex.sweeps.shared.shutdown_requested`` so SIGTERM/SIGINT
    trip the same flag the legacy sweeps use.
    """
    if shutdown_check is None:
        from judex.sweeps.shared import shutdown_requested
        shutdown_check = shutdown_requested

    queues: dict[PoolName, asyncio.Queue] = {
        p.name: asyncio.Queue(maxsize=config.queue_maxsize) for p in config.pools
    }
    pools = build_pools(config.pools)
    counters: dict[PoolName, Counters] = {p.name: Counters() for p in config.pools}

    # Materialise the append-only log if a path is configured. The log
    # writer is constructed once and shared across coroutines via the
    # runtime — its per-row fsync is what gives us hard-kill durability.
    log_writer = PipelineLog(config.log_path) if config.log_path is not None else None

    # One CliffDetector per pool. Each pool's WAF/load posture is
    # independent (portal hits portal.stf.jus.br, sistemas hits
    # sistemas.stf.jus.br, ocr is local-or-API), so cliff trajectory
    # has to be tracked per-pool. ``cliff_window=0`` disables stamping.
    detectors: dict[PoolName, CliffDetector] = {}
    if config.cliff_window > 0:
        detectors = {p.name: CliffDetector(window=config.cliff_window) for p in config.pools}

    runtime = _SchedulerRuntime(
        queues=queues, pools=pools, counters=counters, state=state,
        log=log_writer, cliff_detectors=detectors,
    )

    shutdown_event = asyncio.Event()
    started_at = time.monotonic()

    # Workers first, THEN seed. Seed bulk-puts can exceed queue_maxsize
    # (a year-corpus sweep can have ~10k+ initial fetch_meta tasks
    # against the 1024-deep default queue). If the seeding loop ran
    # before any workers existed, ``await queue.put(t)`` would block on
    # item ``maxsize+1`` forever — no consumer to drain. Spawning the
    # workers first makes the seed loop's awaits yield productively to
    # the worker coroutines that drain the queue. ``in_flight`` is
    # bumped by the seeder *before* each put, so the drain watcher
    # never observes a falsely-empty state mid-seed.
    workers = [
        asyncio.create_task(_pool_worker(p, runtime, config.handlers, shutdown_event))
        for p in config.pools
    ]
    watcher = asyncio.create_task(_drain_watcher(runtime, shutdown_event))
    snapshotter = asyncio.create_task(
        _periodic_snapshotter(state, config.snapshot_interval_seconds, shutdown_event)
    )
    progress = asyncio.create_task(
        _periodic_progress(
            runtime, config.progress_interval_seconds, shutdown_event,
            started_at, n_targets=config.n_targets,
        )
    )

    # Seed. Now safe to bulk-put even when seed_count > queue_maxsize:
    # the awaits yield to the running workers when the queue fills.
    for t in seed_tasks:
        runtime.in_flight[t.pool] += 1
        await runtime.queues[t.pool].put(t)

    # External shutdown poller. Lives in this coroutine so it can be
    # cancelled cleanly when the scheduler exits normally.
    async def _shutdown_poller() -> None:
        while not shutdown_event.is_set():
            await asyncio.sleep(0.5)
            if shutdown_check():
                log.info("shutdown requested; draining")
                shutdown_event.set()
                # Push sentinels so workers don't block on queue.get.
                for q in runtime.queues.values():
                    await q.put(None)
                return

    shutdown_poller = asyncio.create_task(_shutdown_poller())

    try:
        await asyncio.gather(*workers)
    finally:
        shutdown_event.set()
        for aux in (watcher, snapshotter, progress, shutdown_poller):
            aux.cancel()
        await asyncio.gather(*[watcher, snapshotter, progress, shutdown_poller], return_exceptions=True)
        # Final snapshot — guarantee the latest in-memory state lands.
        await asyncio.to_thread(state.snapshot)

    return RunResult(
        counters=counters,
        wall_seconds=time.monotonic() - started_at,
        shutdown_requested=shutdown_check(),
    )
