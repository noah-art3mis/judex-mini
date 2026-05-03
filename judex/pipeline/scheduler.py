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
    try:
        async with pool.semaphore:
            handler_t0 = time.monotonic()
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
) -> None:
    """Print a one-line progress summary every ``interval`` seconds.

    Shape mirrors the existing sweep logs:
    ``[progress] portal=ok/fail · sistemas=ok/fail · ocr=ok/fail · X.XXs``
    """
    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        elapsed = time.monotonic() - started_at
        parts = []
        for pool_name, c in runtime.counters.items():
            parts.append(f"{pool_name}={c.finished}/{c.failed}")
        log.info("[progress] %s · %.1fs", " · ".join(parts), elapsed)


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

    # Seed.
    for t in seed_tasks:
        runtime.in_flight[t.pool] += 1
        await runtime.queues[t.pool].put(t)

    started_at = time.monotonic()

    workers = [
        asyncio.create_task(_pool_worker(p, runtime, config.handlers, shutdown_event))
        for p in config.pools
    ]
    watcher = asyncio.create_task(_drain_watcher(runtime, shutdown_event))
    snapshotter = asyncio.create_task(
        _periodic_snapshotter(state, config.snapshot_interval_seconds, shutdown_event)
    )
    progress = asyncio.create_task(
        _periodic_progress(runtime, config.progress_interval_seconds, shutdown_event, started_at)
    )

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
