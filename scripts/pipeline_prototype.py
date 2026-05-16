"""Throwaway prototype for the unified-pipeline kill/keep gate.

Step 3 of the migration plan in
``docs/superpowers/specs/2026-05-02-unified-pipeline.md``.

Goal: empirically validate that a DAG scheduler with three async pools
beats a sequential 3-command run by >=40% on a 50-case HC slice.

Kill criterion (locked in the design note): ``t_proto / t_baseline <= 0.60``.
Above 0.60, this branch dies and ``coletar`` is the final form.

This file is **disposable**. No persistence, no proxy, no breaker, no
status-aware retry, no per-pool gate. Three asyncio.Queues, three pool
worker coroutines, ``asyncio.Semaphore`` for per-pool concurrency,
``asyncio.to_thread`` to bridge the existing sync library code into the
event loop. If the prototype clears the kill bar, the real
``judex/pipeline/`` module replaces it; if not, this file gets deleted
along with the branch.

Modes
-----
``--modo mock``       no STF traffic; synthetic delays per task class
                      (validates the scheduler's correctness + the
                      pipelining math without spending WAF budget).
``--modo prototipo``  three-pool DAG against real STF endpoints.
``--modo baseline``   sequential ``judex varrer-processos`` ->
                      ``baixar-pecas`` -> ``extrair-pecas`` via
                      subprocess, on the same slice.

Both real-traffic modes (``prototipo`` and ``baseline``) require
``--ja-autorizado`` because they spend WAF budget on real endpoints.

Anchors used in mock mode (per ``judex/utils/cost.py`` and the
2026-04-19 OCR bakeoff):

* portal:   ~3.0 s/req direct-IP
* sistemas: ~3.0 s/req direct-IP
* ocr/pypdf: ~0.1 s/req local
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Literal


# ---------------------------------------------------------------------------
# Task model
# ---------------------------------------------------------------------------

PoolName = Literal["portal", "sistemas", "ocr"]


@dataclass(frozen=True)
class Task:
    kind: Literal["fetch_meta", "fetch_bytes", "extract_text"]
    pool: PoolName
    payload: dict
    case_key: tuple[str, int]


@dataclass
class Counters:
    started: int = 0
    finished: int = 0
    failed: int = 0
    busy_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Worker handlers
# ---------------------------------------------------------------------------
#
# Each handler returns a list of follow-up tasks (possibly empty).
# Handlers are SYNC — the scheduler wraps them in ``asyncio.to_thread``.


HandlerFn = Callable[[Task], list[Task]]


def _mock_handler(delay: float) -> HandlerFn:
    """Sleep ``delay`` seconds, then emit no follow-ups (mock-mode terminal).

    The ``payload['fanout']`` knob lets ``fetch_meta`` emit N
    ``fetch_bytes`` successors; ``fetch_bytes`` emits one
    ``extract_text``. Everything else is terminal.
    """

    def handle(task: Task) -> list[Task]:
        # Mocked work: jittered sleep around the anchor delay.
        time.sleep(max(0.0, delay * random.uniform(0.8, 1.2)))
        if task.kind == "fetch_meta":
            n = task.payload.get("fanout", 8)
            return [
                Task(
                    kind="fetch_bytes",
                    pool="sistemas",
                    payload={"url": f"mock://{task.case_key[1]}/peca-{i}"},
                    case_key=task.case_key,
                )
                for i in range(n)
            ]
        if task.kind == "fetch_bytes":
            return [
                Task(
                    kind="extract_text",
                    pool="ocr",
                    payload={"url": task.payload["url"]},
                    case_key=task.case_key,
                )
            ]
        return []

    return handle


def _real_handlers() -> dict[str, HandlerFn]:
    """Real handlers wired against existing library code.

    Imports are deferred to keep mock mode runnable without a venv that
    has the full extras installed.
    """
    from judex.scraping import scraper as _scraper
    from judex.scraping.http_session import _http_get_with_retry, new_session
    from judex.scraping.ocr import dispatch as ocr_dispatch
    from judex.scraping.ocr.base import OCRConfig
    from judex.sweeps.peca_classification import filter_substantive
    from judex.sweeps.peca_targets import _iter_case_pdf_targets
    from judex.utils import peca_cache

    # One session per pool keeps cookies + connection pool warm; the
    # prototype does not attempt proxy rotation (out of scope per the
    # design note's v1 lock).
    portal_session = new_session()
    sistemas_session = new_session()

    def handle_fetch_meta(task: Task) -> list[Task]:
        classe, processo = task.case_key
        item = _scraper.scrape_processo_http(
            classe, processo, session=portal_session, fetch_dje=False
        )
        # _iter_case_pdf_targets walks the in-memory dict directly.
        # filter_substantive drops tier-C procedural URLs.
        targets = list(_iter_case_pdf_targets(dict(item)))
        targets = filter_substantive(targets)
        return [
            Task(
                kind="fetch_bytes",
                pool="sistemas",
                payload={"url": t.url},
                case_key=task.case_key,
            )
            for t in targets
        ]

    def handle_fetch_bytes(task: Task) -> list[Task]:
        url = task.payload["url"]
        if peca_cache.has_bytes(url):
            return [
                Task(
                    kind="extract_text",
                    pool="ocr",
                    payload={"url": url},
                    case_key=task.case_key,
                )
            ]
        r = _http_get_with_retry(sistemas_session, url, timeout=60)
        peca_cache.write_bytes(url, r.content)
        return [
            Task(
                kind="extract_text",
                pool="ocr",
                payload={"url": url},
                case_key=task.case_key,
            )
        ]

    def handle_extract_text(task: Task) -> list[Task]:
        url = task.payload["url"]
        body = peca_cache.read_bytes(url)
        if not body:
            return []  # no_bytes residual; surfaced via counters.failed
        # OCRConfig signature varies by codebase version; pypdf is
        # parameter-free in practice. The prototype hard-codes pypdf.
        config = OCRConfig(provider="pypdf")
        result = ocr_dispatch.extract_pdf(body, config)
        if result.text:
            peca_cache.write(url, result.text, extractor="pypdf")
        return []

    return {
        "fetch_meta": handle_fetch_meta,
        "fetch_bytes": handle_fetch_bytes,
        "extract_text": handle_extract_text,
    }


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


@dataclass
class PoolConfig:
    name: PoolName
    concurrency: int


@dataclass
class SchedulerConfig:
    pools: list[PoolConfig]
    handlers: dict[str, HandlerFn]
    queue_maxsize: int = 1024


async def _run_one(
    task: Task,
    handler: HandlerFn,
    semaphore: asyncio.Semaphore,
    counters: dict[PoolName, Counters],
    queues: dict[PoolName, asyncio.Queue],
    in_flight: dict[str, int],
) -> None:
    """Runs ``task`` under ``semaphore``. Caller is responsible for the
    ``in_flight[task.pool] += 1`` *before* dispatching this coroutine; we
    only decrement on completion. Doing the increment in the caller
    closes the race where queue.get() returns a task but the bg
    coroutine hasn't been scheduled yet — without that, an empty queue
    plus a zero in-flight count would trip the drain watcher
    spuriously.
    """
    counters[task.pool].started += 1
    try:
        async with semaphore:
            handler_t0 = time.monotonic()
            successors = await asyncio.to_thread(handler, task)
            counters[task.pool].busy_seconds += time.monotonic() - handler_t0
        counters[task.pool].finished += 1
        for follow in successors:
            in_flight[follow.pool] += 1  # bump BEFORE put for the same race reason
            await queues[follow.pool].put(follow)
    except Exception as exc:  # noqa: BLE001 -- prototype, not production
        counters[task.pool].failed += 1
        print(f"[{task.pool}] FAIL {task.kind} {task.case_key}: {exc!r}", file=sys.stderr)
    finally:
        in_flight[task.pool] -= 1


async def _pool_worker(
    pool: PoolConfig,
    queue: asyncio.Queue,
    handlers: dict[str, HandlerFn],
    counters: dict[PoolName, Counters],
    queues: dict[PoolName, asyncio.Queue],
    in_flight: dict[str, int],
) -> None:
    semaphore = asyncio.Semaphore(pool.concurrency)
    pending: set[asyncio.Task] = set()
    while True:
        task = await queue.get()
        if task is None:
            break
        # in_flight was already bumped by whoever put() the task (seeds
        # in run_scheduler, follow-ups in _run_one). Don't re-bump here.
        coro = _run_one(task, handlers[task.kind], semaphore, counters, queues, in_flight)
        bg = asyncio.create_task(coro)
        pending.add(bg)
        bg.add_done_callback(pending.discard)
        queue.task_done()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _drain_watcher(
    queues: dict[PoolName, asyncio.Queue],
    in_flight: dict[str, int],
    poll_seconds: float = 0.25,
) -> None:
    """Watches for steady-state idle and pushes shutdown sentinels.

    Idle == every queue is empty AND every pool's in-flight count is 0.
    Once observed, send one ``None`` sentinel per pool's queue so the
    workers exit their main loops cleanly.
    """
    while True:
        await asyncio.sleep(poll_seconds)
        queues_empty = all(q.empty() for q in queues.values())
        no_inflight = all(v == 0 for v in in_flight.values())
        if queues_empty and no_inflight:
            for q in queues.values():
                await q.put(None)
            return


async def run_scheduler(
    seed_tasks: list[Task],
    config: SchedulerConfig,
) -> dict[PoolName, Counters]:
    queues: dict[PoolName, asyncio.Queue] = {
        p.name: asyncio.Queue(maxsize=config.queue_maxsize) for p in config.pools
    }
    counters: dict[PoolName, Counters] = {p.name: Counters() for p in config.pools}
    in_flight: dict[str, int] = defaultdict(int)

    for t in seed_tasks:
        in_flight[t.pool] += 1  # bump BEFORE put — workers don't re-bump
        await queues[t.pool].put(t)

    workers = [
        asyncio.create_task(
            _pool_worker(p, queues[p.name], config.handlers, counters, queues, in_flight)
        )
        for p in config.pools
    ]
    watcher = asyncio.create_task(_drain_watcher(queues, in_flight))

    await asyncio.gather(*workers)
    watcher.cancel()
    return counters


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def _mock_handlers(scale: float = 0.02) -> dict[str, HandlerFn]:
    """Mock handler delays. Real anchors are 3.0/3.0/0.1 s; the prototype
    mock scales them down (default 0.02 s portal/sistemas, 0.0007 s ocr)
    so smoke-test wall stays in seconds. The pipelining ratio is the
    same; only the absolute numbers shrink.
    """
    return {
        "fetch_meta": _mock_handler(scale),
        "fetch_bytes": _mock_handler(scale),
        "extract_text": _mock_handler(scale * 0.033),
    }


def _seed_tasks(cases: list[tuple[str, int]], fanout: int | None) -> list[Task]:
    seeds: list[Task] = []
    for classe, processo in cases:
        payload: dict = {}
        if fanout is not None:
            payload["fanout"] = fanout
        seeds.append(
            Task(
                kind="fetch_meta",
                pool="portal",
                payload=payload,
                case_key=(classe, processo),
            )
        )
    return seeds


def _read_slice(slice_path: Path) -> list[tuple[str, int]]:
    """Read a CSV with header ``classe,processo`` (or ``classe,processo_id``)."""
    out: list[tuple[str, int]] = []
    with slice_path.open() as fh:
        header = fh.readline().strip().split(",")
        idx_classe = header.index("classe")
        try:
            idx_proc = header.index("processo")
        except ValueError:
            idx_proc = header.index("processo_id")
        for line in fh:
            parts = line.strip().split(",")
            if not parts or not parts[0]:
                continue
            out.append((parts[idx_classe], int(parts[idx_proc])))
    return out


async def _run_prototipo(cases: list[tuple[str, int]], pool_concurrency: dict[PoolName, int]) -> dict:
    handlers = _real_handlers()
    config = SchedulerConfig(
        pools=[
            PoolConfig(name="portal", concurrency=pool_concurrency["portal"]),
            PoolConfig(name="sistemas", concurrency=pool_concurrency["sistemas"]),
            PoolConfig(name="ocr", concurrency=pool_concurrency["ocr"]),
        ],
        handlers=handlers,
    )
    seeds = _seed_tasks(cases, fanout=None)
    t0 = time.monotonic()
    counters = await run_scheduler(seeds, config)
    return {"wall": time.monotonic() - t0, "counters": {k: v.__dict__ for k, v in counters.items()}}


async def _run_mock(cases: list[tuple[str, int]], pool_concurrency: dict[PoolName, int], fanout: int) -> dict:
    handlers = _mock_handlers()
    config = SchedulerConfig(
        pools=[
            PoolConfig(name="portal", concurrency=pool_concurrency["portal"]),
            PoolConfig(name="sistemas", concurrency=pool_concurrency["sistemas"]),
            PoolConfig(name="ocr", concurrency=pool_concurrency["ocr"]),
        ],
        handlers=handlers,
    )
    seeds = _seed_tasks(cases, fanout=fanout)
    t0 = time.monotonic()
    counters = await run_scheduler(seeds, config)
    return {"wall": time.monotonic() - t0, "counters": {k: v.__dict__ for k, v in counters.items()}}


def _run_baseline(slice_path: Path, saida: Path) -> dict:
    """Sequential 3-command run via subprocess; measures wall."""
    saida.mkdir(parents=True, exist_ok=True)
    rotulo = "proto-baseline"
    t0 = time.monotonic()

    varrer_dir = saida / "varrer"
    subprocess.run(
        [
            "uv", "run", "judex", "varrer-processos",
            "--csv", str(slice_path),
            "--saida", str(varrer_dir),
            "--rotulo", rotulo,
            "--nao-perguntar",
        ],
        check=True,
    )
    t_varrer = time.monotonic() - t0

    baixar_dir = saida / "baixar"
    subprocess.run(
        [
            "uv", "run", "judex", "baixar-pecas",
            "--csv", str(slice_path),
            "--saida", str(baixar_dir),
            "--nao-perguntar",
        ],
        check=True,
    )
    t_baixar = time.monotonic() - t0 - t_varrer

    extrair_dir = saida / "extrair"
    subprocess.run(
        [
            "uv", "run", "judex", "extrair-pecas",
            "--csv", str(slice_path),
            "--saida", str(extrair_dir),
            "--provedor", "pypdf",
            "--nao-perguntar",
        ],
        check=True,
    )
    t_total = time.monotonic() - t0

    return {
        "wall": t_total,
        "stages": {
            "varrer": t_varrer,
            "baixar": t_baixar,
            "extrair": t_total - t_varrer - t_baixar,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--modo", choices=["mock", "prototipo", "baseline"], required=True)
    p.add_argument("--csv", type=Path, help="Slice CSV (classe,processo). Required for prototipo and baseline.")
    p.add_argument("--saida", type=Path, default=Path("scratch/pipeline_runs"))
    p.add_argument("--portal-concurrencia", type=int, default=1)
    p.add_argument("--sistemas-concurrencia", type=int, default=1)
    p.add_argument("--ocr-concurrencia", type=int, default=4)
    p.add_argument("--fanout-mock", type=int, default=8, help="Synthetic peças per case in mock mode.")
    p.add_argument("--n-mock", type=int, default=50, help="Synthetic case count in mock mode.")
    p.add_argument("--ja-autorizado", action="store_true",
                   help="Required for modes that hit real STF endpoints (prototipo, baseline). "
                        "Spends WAF budget; do not set without explicit user approval.")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    pool_concurrency: dict[PoolName, int] = {
        "portal": args.portal_concurrencia,
        "sistemas": args.sistemas_concurrencia,
        "ocr": args.ocr_concurrencia,
    }

    if args.modo in {"prototipo", "baseline"} and not args.ja_autorizado:
        print(
            "ERROR: --modo prototipo and --modo baseline hit real STF endpoints "
            "and spend WAF budget. Re-run with --ja-autorizado after confirming "
            "with the user.",
            file=sys.stderr,
        )
        return 2

    if args.modo == "mock":
        cases = [("HC", 100_000 + i) for i in range(args.n_mock)]
        result = asyncio.run(_run_mock(cases, pool_concurrency, args.fanout_mock))
    elif args.modo == "prototipo":
        if not args.csv:
            print("ERROR: --modo prototipo requires --csv", file=sys.stderr)
            return 2
        cases = _read_slice(args.csv)
        result = asyncio.run(_run_prototipo(cases, pool_concurrency))
    else:  # baseline
        if not args.csv:
            print("ERROR: --modo baseline requires --csv", file=sys.stderr)
            return 2
        result = _run_baseline(args.csv, args.saida)

    print(json.dumps({"modo": args.modo, **result}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
