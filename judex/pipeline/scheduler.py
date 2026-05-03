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
from typing import Awaitable, Callable, Optional

from judex.pipeline.handlers import HandlerFn
from judex.pipeline.models import Counters, PoolConfig, PoolName, Task, TaskStatus
from judex.pipeline.pools import Pool, build_pools
from judex.pipeline.state import PipelineState


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


@dataclass
class RunResult:
    counters: dict[PoolName, Counters]
    wall_seconds: float
    shutdown_requested: bool = False


def _is_retryable_status(kind: str, status: Optional[TaskStatus]) -> bool:
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

    Without this filter, the seed builder re-enqueues every non-ok
    task on every resume, including terminal ones like
    ``unallocated_pid``. At year-corpus scale that burns measurable
    portal-pool wall on cases that will never become ok. This is the
    operational gap that ``coletar`` closes via its status-aware
    retry passes; lifting the policy here gives the unified pipeline
    parity.
    """
    if status is None:
        return True
    if status == "ok":
        return False
    if kind == "fetch_meta":
        return status == "http_error"
    if kind == "fetch_bytes":
        return status == "http_error"
    if kind == "extract_text":
        return status == "provider_error"
    return False


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
                    if _is_retryable_status("fetch_bytes", bytes_status):
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
                if text_status != "ok" and _is_retryable_status(
                    "extract_text", text_status
                ):
                    seeds.append(
                        Task(
                            kind="extract_text",
                            pool="ocr",
                            payload={"url": url, "doc_type": doc_type},
                            case_key=case_key,
                        )
                    )
        elif _is_retryable_status("fetch_meta", meta_status):
            seeds.append(
                Task(
                    kind="fetch_meta",
                    pool="portal",
                    payload={},
                    case_key=case_key,
                )
            )
        # else: meta status is non-ok and terminal (e.g. unallocated_pid)
        # — skip the case entirely.

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
    emits successors, and feeds the per-pool circuit breaker the
    state-side outcome. Handlers do not raise — they record their
    own error outcomes to state.
    """
    pool = runtime.pools[task.pool]
    runtime.counters[task.pool].started += 1
    handler_t0 = time.monotonic()
    try:
        async with pool.semaphore:
            successors = await asyncio.to_thread(handler, task)
            runtime.counters[task.pool].busy_seconds += time.monotonic() - handler_t0
        runtime.counters[task.pool].finished += 1

        # Feed the breaker. ``ok`` if the handler recorded "ok" for
        # this task; anything else (http_error, no_bytes, empty,
        # provider_error, unallocated_pid) counts as an error from
        # the breaker's perspective. None means the handler didn't
        # record (shouldn't happen given the handlers.py contract);
        # we treat None as "error" defensively.
        outcome = _read_task_outcome(runtime.state, task)
        pool.record_outcome(ok=(outcome == "ok"))

        # Per-task tail line. Format mirrors legacy
        # ``judex.utils.log_render.render_target_line``:
        #   HH:MM:SS  ✓ ok        [portal]    HC 187634          ·  3.21s
        # Timestamp first, glyph + status word (padded to 8 chars so
        # most lines align), pool tag, compact identifier, wall.
        elapsed = time.monotonic() - handler_t0
        from judex.utils.log_render import _style_for, _now_hms
        glyph, _ = _style_for(outcome or "?")
        log.info(
            "%s  %s %-8s  [%-8s]  %-20s  ·  %.2fs",
            _now_hms(), glyph, outcome or "?",
            task.pool, _short_identifier(task), elapsed,
        )

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
    """Print a one-line progress summary every ``interval`` seconds.

    Format mirrors legacy ``render_progress_line``:
    ``─── 132/9137 (1.4%) · portal_ok=130 portal_fail=2 bytes_ok=240 ... · 0.31 cases/s · eta 8h ───``

    ``n_targets`` is the case-count denominator for the portal pool's
    progress fraction (portal is meta-only, 1 task per case). When
    zero (unknown), the percentage is omitted.
    """
    from judex.utils.log_render import render_progress_line

    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        elapsed = time.monotonic() - started_at
        portal = runtime.counters["portal"]
        sistemas = runtime.counters["sistemas"]
        ocr_c = runtime.counters["ocr"]

        # Portal is the bottleneck (case-rate); use its rate for ETA.
        rate = portal.finished / elapsed if elapsed > 0 else 0.0
        denom = n_targets or max(portal.started, 1)
        remaining = max(0, denom - portal.finished)
        eta_min = (remaining / rate / 60.0) if rate > 0 else 0.0

        log.info(
            render_progress_line(
                n=portal.finished,
                total=denom,
                counters={
                    "meta_ok": portal.finished - portal.failed,
                    "meta_fail": portal.failed,
                    "bytes_ok": sistemas.finished - sistemas.failed,
                    "bytes_fail": sistemas.failed,
                    "text_ok": ocr_c.finished - ocr_c.failed,
                    "text_fail": ocr_c.failed,
                },
                rate_per_sec=rate,
                rate_label="cases/s",
                eta_min=eta_min,
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
    runtime = _SchedulerRuntime(queues=queues, pools=pools, counters=counters, state=state)

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
