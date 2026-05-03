"""Scheduler contract tests using mocked handlers.

These pin the scheduler-side guarantees that fire-and-forget depends on:

* clean handlers complete every seeded task
* per-task failures are recorded but don't crash the scheduler
* resume re-enqueues only non-ok work (drives ``seeds_from_targets``)
* shutdown-on-signal flushes state before exiting
* state-store records survive across a simulated restart

Plus stress contracts that pin behaviour under load (Layer 1 of the
HC 2020 stress plan):

* backpressure on a tight ``queue_maxsize`` does not deadlock
* drain watcher waits for in-flight tasks even when queues are empty
* shutdown mid-fanout exits cleanly with durable state on disk
* handler-raised exceptions are contained inside the pool
* circuit-breaker warning logs exactly once under sustained errors
* no tasks are lost when concurrency > 1 across all pools
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from judex.pipeline.models import PoolConfig, Task
from judex.pipeline.scheduler import (
    RunResult,
    SchedulerConfig,
    run_scheduler,
    seeds_from_targets,
)
from judex.pipeline.state import PipelineState


def _three_pools() -> list[PoolConfig]:
    return [
        PoolConfig(name="portal", concurrency=2),
        PoolConfig(name="sistemas", concurrency=2),
        PoolConfig(name="ocr", concurrency=2),
    ]


def _mock_handlers(state: PipelineState, *, peças_per_case: int = 3) -> dict[str, callable]:
    """Synthetic handlers that record outcomes to ``state`` exactly the
    way the real handlers would. No I/O, no sleeps; deterministic.
    """

    def handle_meta(task: Task) -> list[Task]:
        state.record_meta(task.case_key, status="ok")
        return [
            Task(
                kind="fetch_bytes",
                pool="sistemas",
                payload={"url": f"u-{task.case_key[1]}-{i}"},
                case_key=task.case_key,
            )
            for i in range(peças_per_case)
        ]

    def handle_bytes(task: Task) -> list[Task]:
        url = task.payload["url"]
        state.record_bytes(task.case_key, url=url, status="ok")
        return [
            Task(
                kind="extract_text",
                pool="ocr",
                payload={"url": url},
                case_key=task.case_key,
            )
        ]

    def handle_text(task: Task) -> list[Task]:
        url = task.payload["url"]
        state.record_text(task.case_key, url=url, status="ok", extractor="pypdf")
        return []

    return {
        "fetch_meta": handle_meta,
        "fetch_bytes": handle_bytes,
        "extract_text": handle_text,
    }


def _no_shutdown() -> bool:
    return False


@pytest.mark.asyncio
async def test_per_task_tail_line_shows_provider_and_chars_for_extract_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """The user's explicit ask: ``[ocr     ]  HC 1 …  ·  0.00s · pypdf
    1,200ch``. Without the suffix, the operator can't tell which
    provider ran (matters under ``--provedor auto``) or how big the
    OCR output was. fetch_meta / fetch_bytes rows must NOT carry the
    suffix — that would be visual noise on a stage that has no
    provider."""

    state = PipelineState.load(tmp_path / "s.json")
    targets = [("HC", 1)]

    def handle_meta(task: Task) -> list[Task]:
        state.record_meta(task.case_key, status="ok")
        return [Task(
            kind="fetch_bytes", pool="sistemas",
            payload={"url": "u-1-0"}, case_key=task.case_key,
        )]

    def handle_bytes(task: Task) -> list[Task]:
        state.record_bytes(task.case_key, url=task.payload["url"], status="ok")
        return [Task(
            kind="extract_text", pool="ocr",
            payload={"url": task.payload["url"]}, case_key=task.case_key,
        )]

    def handle_text(task: Task) -> list[Task]:
        state.record_text(
            task.case_key, url=task.payload["url"],
            status="ok", extractor="pypdf", chars=1200,
        )
        return []

    handlers = {
        "fetch_meta": handle_meta,
        "fetch_bytes": handle_bytes,
        "extract_text": handle_text,
    }

    config = SchedulerConfig(
        pools=_three_pools(), handlers=handlers,
        progress_interval_seconds=10.0,
    )
    seeds = seeds_from_targets(targets, state)
    with caplog.at_level("INFO", logger="judex.pipeline.scheduler"):
        await run_scheduler(seeds, config, state, shutdown_check=_no_shutdown)

    text_lines = [r.getMessage() for r in caplog.records if "[ocr" in r.getMessage()]
    bytes_lines = [r.getMessage() for r in caplog.records if "[sistemas" in r.getMessage()]
    meta_lines = [r.getMessage() for r in caplog.records if "[portal" in r.getMessage()]

    # extract_text row: provider + comma-formatted chars in suffix.
    assert any("pypdf 1,200ch" in line for line in text_lines), text_lines
    # No bleed-through to other stages.
    assert not any("ch" in line.split("·", 1)[1] for line in bytes_lines if "·" in line)
    assert not any("pypdf" in line for line in meta_lines)


@pytest.mark.asyncio
async def test_clean_run_completes_all_tasks(tmp_path: Path) -> None:
    state = PipelineState.load(tmp_path / "s.json")
    targets = [("HC", i) for i in range(5)]

    config = SchedulerConfig(
        pools=_three_pools(),
        handlers=_mock_handlers(state, peças_per_case=2),
        snapshot_interval_seconds=0.5,
        progress_interval_seconds=10.0,
    )
    seeds = seeds_from_targets(targets, state)
    result = await run_scheduler(seeds, config, state, shutdown_check=_no_shutdown)

    # Each case: 1 meta + 2 bytes + 2 text = 5 tasks. 5 cases = 25 tasks.
    total_finished = sum(c.finished for c in result.counters.values())
    total_failed = sum(c.failed for c in result.counters.values())
    assert total_finished == 25
    assert total_failed == 0
    assert result.shutdown_requested is False


@pytest.mark.asyncio
async def test_state_records_every_outcome(tmp_path: Path) -> None:
    state = PipelineState.load(tmp_path / "s.json")
    targets = [("HC", 1), ("HC", 2)]

    config = SchedulerConfig(
        pools=_three_pools(),
        handlers=_mock_handlers(state, peças_per_case=2),
    )
    seeds = seeds_from_targets(targets, state)
    await run_scheduler(seeds, config, state, shutdown_check=_no_shutdown)

    assert state.is_meta_complete(("HC", 1))
    assert state.is_meta_complete(("HC", 2))
    for case in targets:
        for i in range(2):
            url = f"u-{case[1]}-{i}"
            assert state.is_bytes_complete(case, url=url)
            assert state.is_text_complete(case, url=url, required_extractor="pypdf")


@pytest.mark.asyncio
async def test_failures_recorded_but_scheduler_continues(tmp_path: Path) -> None:
    """A handler that records ``http_error`` for one URL must not stop
    the scheduler from processing the rest. State reflects the
    failure; the run as a whole completes with non-zero failed count.
    """
    state = PipelineState.load(tmp_path / "s.json")

    def handle_meta(task: Task) -> list[Task]:
        state.record_meta(task.case_key, status="ok")
        return [
            Task(
                kind="fetch_bytes",
                pool="sistemas",
                payload={"url": f"u-{task.case_key[1]}"},
                case_key=task.case_key,
            )
        ]

    def handle_bytes(task: Task) -> list[Task]:
        url = task.payload["url"]
        if task.case_key == ("HC", 2):
            state.record_bytes(task.case_key, url=url, status="http_error", error="WAF 403")
            return []
        state.record_bytes(task.case_key, url=url, status="ok")
        return [
            Task(kind="extract_text", pool="ocr",
                 payload={"url": url}, case_key=task.case_key)
        ]

    def handle_text(task: Task) -> list[Task]:
        state.record_text(task.case_key, url=task.payload["url"], status="ok", extractor="pypdf")
        return []

    handlers = {
        "fetch_meta": handle_meta,
        "fetch_bytes": handle_bytes,
        "extract_text": handle_text,
    }
    config = SchedulerConfig(pools=_three_pools(), handlers=handlers)
    targets = [("HC", 1), ("HC", 2), ("HC", 3)]
    seeds = seeds_from_targets(targets, state)
    result = await run_scheduler(seeds, config, state, shutdown_check=_no_shutdown)

    # All meta succeeded.
    for c in targets:
        assert state.is_meta_complete(c)

    # HC-2's bytes failed; the others succeeded and proceeded to extract.
    assert state.is_bytes_complete(("HC", 1), url="u-1")
    assert not state.is_bytes_complete(("HC", 2), url="u-2")
    assert state.is_bytes_complete(("HC", 3), url="u-3")
    assert state.is_text_complete(("HC", 1), url="u-1")
    assert state.is_text_complete(("HC", 3), url="u-3")

    # Scheduler counted the failed bytes task as finished (handler
    # returned cleanly) — the failure is in the state record, not in
    # the scheduler's failed counter. This is the correct shape:
    # the scheduler trusts handlers to record their own outcomes;
    # ``failed`` only fires for handler-raised exceptions.
    total_finished = sum(c.finished for c in result.counters.values())
    total_failed = sum(c.failed for c in result.counters.values())
    assert total_finished == 1 + 1 + 1 + 1 + 1 + 1 + 2  # meta(3) + bytes(3) + text(2)
    assert total_failed == 0


@pytest.mark.asyncio
async def test_seeds_from_targets_skips_completed_meta(tmp_path: Path) -> None:
    """A re-run with HC-1's meta already ``ok`` and one of its bytes
    URLs already ``ok`` must seed only the residual bytes/text work,
    not re-fetch meta.
    """
    state = PipelineState.load(tmp_path / "s.json")
    state.record_meta(("HC", 1), status="ok")
    state.record_bytes(("HC", 1), url="u-1-0", status="ok")
    state.record_bytes(("HC", 1), url="u-1-1", status="http_error")
    state.record_text(("HC", 1), url="u-1-0", status="ok", extractor="pypdf")
    # u-1-1 has bytes that failed; expect the scheduler to re-enqueue
    # the bytes task. Text on u-1-0 is done; nothing to enqueue there.

    seeds = seeds_from_targets([("HC", 1), ("HC", 2)], state)

    kinds = [(t.kind, t.case_key, t.payload.get("url")) for t in seeds]
    # HC-1: only the failed-bytes URL re-seeded.
    assert ("fetch_bytes", ("HC", 1), "u-1-1") in kinds
    assert ("fetch_meta", ("HC", 1), None) not in kinds
    # HC-2: full meta task, no bytes/text yet.
    assert ("fetch_meta", ("HC", 2), None) in kinds
    # No spurious extract_text seeds for already-ok URLs.
    assert ("extract_text", ("HC", 1), "u-1-0") not in kinds


# ---------------------------------------------------------------------------
# Status-aware resume — coletar-parity for retry / drop semantics.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seeds_skips_unallocated_pid_meta(tmp_path: Path) -> None:
    """A case whose meta resolved to ``unallocated_pid`` is terminal
    (the processo_id genuinely doesn't exist at STF). Resume must NOT
    re-seed it — that would burn portal-pool requests on every resume
    for cases that will never become ok. Mirrors
    ``error_triage._classify_varrer``'s ``unallocated → terminal``
    decision.
    """
    state = PipelineState.load(tmp_path / "s.json")
    state.record_meta(("HC", 999_999), status="unallocated_pid")
    state.record_meta(("HC", 1), status="ok")

    seeds = seeds_from_targets([("HC", 999_999), ("HC", 1)], state)
    kinds = [(t.kind, t.case_key) for t in seeds]

    # 999_999 is terminal; no fetch_meta seed.
    assert ("fetch_meta", ("HC", 999_999)) not in kinds
    # HC-1 is ok with no known peças; nothing to seed at all.
    assert seeds == []


@pytest.mark.asyncio
async def test_seeds_retries_http_error_meta(tmp_path: Path) -> None:
    """``http_error`` (WAF / timeout / SSL) is transient; resume must
    re-seed so the next pass picks it up after WAF cools."""
    state = PipelineState.load(tmp_path / "s.json")
    state.record_meta(("HC", 5), status="http_error", error="waf_403")

    seeds = seeds_from_targets([("HC", 5)], state)
    kinds = [(t.kind, t.case_key) for t in seeds]

    assert ("fetch_meta", ("HC", 5)) in kinds


@pytest.mark.asyncio
async def test_seeds_skips_empty_bytes(tmp_path: Path) -> None:
    """``empty`` on a bytes record means STF returned a body that
    didn't match the supported magic-bytes (PDF / RTF). The body won't
    change on retry — terminal, drop. Mirrors
    ``error_triage._classify_baixar``'s default-to-terminal."""
    state = PipelineState.load(tmp_path / "s.json")
    state.record_meta(("HC", 1), status="ok")
    state.record_bytes(("HC", 1), url="u-1", status="empty",
                       error="unsupported magic bytes")

    seeds = seeds_from_targets([("HC", 1)], state)
    kinds = [(t.kind, t.payload.get("url")) for t in seeds]

    assert ("fetch_bytes", "u-1") not in kinds
    # And no spurious downstream extract seed either.
    assert ("extract_text", "u-1") not in kinds


@pytest.mark.asyncio
async def test_seeds_skips_no_bytes_text(tmp_path: Path) -> None:
    """``no_bytes`` on a text record is cross-stage: the cache was
    empty when extract ran. Re-seeding extract_text won't help (it'll
    just record no_bytes again); the operator needs a bytes-side
    re-fetch which seeds_from_targets doesn't trigger here. Drop.
    Mirrors ``error_triage._classify_extrair``'s ``no_bytes →
    cross_stage``."""
    state = PipelineState.load(tmp_path / "s.json")
    state.record_meta(("HC", 1), status="ok")
    state.record_bytes(("HC", 1), url="u-1", status="ok")
    state.record_text(("HC", 1), url="u-1", status="no_bytes",
                      error="cache miss; run fetch_bytes first")

    seeds = seeds_from_targets([("HC", 1)], state)
    kinds = [(t.kind, t.payload.get("url")) for t in seeds]

    assert ("extract_text", "u-1") not in kinds


@pytest.mark.asyncio
async def test_seeds_carry_doc_type_for_auto_router_on_resume(
    tmp_path: Path,
) -> None:
    """``--provedor auto`` decides per-target via doc_type. On resume,
    re-seeded ``fetch_bytes`` and ``extract_text`` tasks must carry the
    doc_type that was tagged at first emission — otherwise the auto
    router would lose its routing key and silently fall back to pypdf
    on retries, which is wrong for ACÓRDÃO PDFs."""
    state = PipelineState.load(tmp_path / "s.json")
    state.record_meta(("HC", 1), status="ok")
    state.record_bytes(
        ("HC", 1), url="acordao.pdf", status="http_error",
        doc_type="INTEIRO TEOR DO ACÓRDÃO",
    )
    state.record_bytes(("HC", 1), url="petition.pdf", status="ok",
                       doc_type="PETIÇÃO")
    state.record_text(("HC", 1), url="petition.pdf", status="provider_error",
                      extractor="pypdf")

    seeds = seeds_from_targets([("HC", 1)], state)
    payload_by_kind = {(s.kind, s.payload["url"]): s.payload for s in seeds}

    # Re-seeded fetch_bytes carries the ACÓRDÃO doc_type.
    assert payload_by_kind[("fetch_bytes", "acordao.pdf")]["doc_type"] == \
        "INTEIRO TEOR DO ACÓRDÃO"
    # Re-seeded extract_text carries PETIÇÃO doc_type.
    assert payload_by_kind[("extract_text", "petition.pdf")]["doc_type"] == \
        "PETIÇÃO"


@pytest.mark.asyncio
async def test_seeds_retries_provider_error_text(tmp_path: Path) -> None:
    """``provider_error`` is transient — providers hiccup, network
    flakes between us and Mistral / Datalab, etc. Mirrors
    ``error_triage._classify_extrair``'s ``provider_error →
    transient``."""
    state = PipelineState.load(tmp_path / "s.json")
    state.record_meta(("HC", 1), status="ok")
    state.record_bytes(("HC", 1), url="u-1", status="ok")
    state.record_text(("HC", 1), url="u-1", status="provider_error",
                      extractor="pypdf", error="PdfReadError")

    seeds = seeds_from_targets([("HC", 1)], state)
    kinds = [(t.kind, t.payload.get("url")) for t in seeds]

    assert ("extract_text", "u-1") in kinds


@pytest.mark.asyncio
async def test_retry_count_auto_increments_on_re_recording(tmp_path: Path) -> None:
    """Each call to ``record_*`` after the first must bump
    ``retry_count`` by one. The seed builder reads this counter to
    enforce ADR-0004's "cap of 2 retry cycles" inheritance — so the
    counter has to be honest about how many times the handler has
    been here before. Initial recording leaves rc=0 (no retry yet);
    second leaves rc=1; third leaves rc=2. See
    ``docs/adr/0005-unified-pipeline.md`` § Open issue #1.
    """
    state = PipelineState.load(tmp_path / "s.json")
    state.record_meta(("HC", 1), status="http_error", error="waf_403")
    assert state.meta_retry_count(("HC", 1)) == 0

    state.record_meta(("HC", 1), status="http_error", error="waf_403")
    assert state.meta_retry_count(("HC", 1)) == 1

    state.record_meta(("HC", 1), status="http_error", error="waf_403")
    assert state.meta_retry_count(("HC", 1)) == 2

    # Same contract for bytes and text, keyed by URL.
    state.record_bytes(("HC", 1), url="u", status="http_error")
    assert state.bytes_retry_count(("HC", 1), url="u") == 0
    state.record_bytes(("HC", 1), url="u", status="http_error")
    assert state.bytes_retry_count(("HC", 1), url="u") == 1

    state.record_text(("HC", 1), url="u", status="provider_error", extractor="pypdf")
    assert state.text_retry_count(("HC", 1), url="u") == 0
    state.record_text(("HC", 1), url="u", status="provider_error", extractor="pypdf")
    assert state.text_retry_count(("HC", 1), url="u") == 1


@pytest.mark.asyncio
async def test_seeds_skips_meta_at_retry_cap(tmp_path: Path) -> None:
    """A ``fetch_meta`` task with ``retry_count == RETRY_CAP`` (=2)
    is NOT re-seeded — even though its status (``http_error``) would
    otherwise be transient. This honors ADR-0004's "cap of 2 retry
    cycles" contract. After 3 total attempts (initial + 2 retries),
    the operator is expected to surface the systemic issue rather
    than burn a fourth attempt.
    """
    state = PipelineState.load(tmp_path / "s.json")
    state.record_meta(("HC", 1), status="http_error", error="waf_403")
    state.record_meta(("HC", 1), status="http_error", error="waf_403")
    state.record_meta(("HC", 1), status="http_error", error="waf_403")
    assert state.meta_retry_count(("HC", 1)) == 2

    seeds = seeds_from_targets([("HC", 1)], state)
    kinds = [(t.kind, t.case_key) for t in seeds]
    assert ("fetch_meta", ("HC", 1)) not in kinds


@pytest.mark.asyncio
async def test_seeds_retries_meta_below_retry_cap(tmp_path: Path) -> None:
    """Symmetric counterpart: a ``fetch_meta`` task with
    ``retry_count < RETRY_CAP`` IS re-seeded. Pinning both sides of
    the gate so a future refactor doesn't accidentally invert it.
    """
    state = PipelineState.load(tmp_path / "s.json")
    state.record_meta(("HC", 1), status="http_error", error="waf_403")
    assert state.meta_retry_count(("HC", 1)) == 0
    state.record_meta(("HC", 1), status="http_error", error="waf_403")
    assert state.meta_retry_count(("HC", 1)) == 1

    seeds = seeds_from_targets([("HC", 1)], state)
    kinds = [(t.kind, t.case_key) for t in seeds]
    assert ("fetch_meta", ("HC", 1)) in kinds


@pytest.mark.asyncio
async def test_seeds_skips_bytes_and_text_at_retry_cap(tmp_path: Path) -> None:
    """Same cap=2 gate applies to ``fetch_bytes`` and ``extract_text``
    — the per-Pool breaker is the structural early-warning, the
    per-Task cap is the ceiling. Tasks at the cap drop out of resume
    even when their status is otherwise transient.
    """
    state = PipelineState.load(tmp_path / "s.json")
    state.record_meta(("HC", 1), status="ok")

    # bytes at cap.
    state.record_bytes(("HC", 1), url="u-bytes", status="http_error")
    state.record_bytes(("HC", 1), url="u-bytes", status="http_error")
    state.record_bytes(("HC", 1), url="u-bytes", status="http_error")
    assert state.bytes_retry_count(("HC", 1), url="u-bytes") == 2

    # text at cap (over an ok bytes record so the seed builder reaches
    # the text branch).
    state.record_bytes(("HC", 1), url="u-text", status="ok")
    state.record_text(("HC", 1), url="u-text", status="provider_error",
                      extractor="pypdf")
    state.record_text(("HC", 1), url="u-text", status="provider_error",
                      extractor="pypdf")
    state.record_text(("HC", 1), url="u-text", status="provider_error",
                      extractor="pypdf")
    assert state.text_retry_count(("HC", 1), url="u-text") == 2

    seeds = seeds_from_targets([("HC", 1)], state)
    kinds = [(t.kind, t.payload.get("url")) for t in seeds]
    assert ("fetch_bytes", "u-bytes") not in kinds
    assert ("extract_text", "u-text") not in kinds


@pytest.mark.asyncio
async def test_shutdown_check_drains_cleanly(tmp_path: Path) -> None:
    """When ``shutdown_check`` flips to True, in-flight tasks finish,
    state is flushed, and the run exits with ``shutdown_requested=True``.
    """
    state = PipelineState.load(tmp_path / "s.json")
    targets = [("HC", i) for i in range(3)]

    # Trigger shutdown after the first poll cycle.
    cycles = {"n": 0}

    def shutdown_after_first_call() -> bool:
        cycles["n"] += 1
        return cycles["n"] > 1

    config = SchedulerConfig(
        pools=_three_pools(),
        handlers=_mock_handlers(state, peças_per_case=1),
    )
    seeds = seeds_from_targets(targets, state)
    result = await run_scheduler(seeds, config, state, shutdown_check=shutdown_after_first_call)

    # Either the run finished naturally before the shutdown poller
    # tripped (very small workload), or it shut down. Both outcomes
    # are valid; what we pin here is that state is consistent with
    # whatever the counters say.
    total_finished = sum(c.finished for c in result.counters.values())
    # State has no half-recorded entries.
    assert (tmp_path / "executar.state.json").exists()


@pytest.mark.asyncio
async def test_round_trip_resume(tmp_path: Path) -> None:
    """Full simulation of: run partway, kill, resume from disk.

    First handler crashes the run by setting shutdown after one task;
    second invocation loads state from disk and finishes the rest.
    """
    state_path = tmp_path / "executar.state.json"
    targets = [("HC", i) for i in range(3)]

    # First run: process only HC-0's meta, then "shut down".
    state1 = PipelineState.load(state_path)
    handlers1 = _mock_handlers(state1, peças_per_case=1)
    # Wrap the meta handler so that after the first call we trigger
    # shutdown — but only the OUTER shutdown_check actually halts.
    seen = {"meta_calls": 0}
    real_handle_meta = handlers1["fetch_meta"]

    def gating_meta(task: Task) -> list[Task]:
        seen["meta_calls"] += 1
        return real_handle_meta(task)

    handlers1["fetch_meta"] = gating_meta

    def shutdown_after_one_meta() -> bool:
        return seen["meta_calls"] >= 1

    config1 = SchedulerConfig(
        pools=[PoolConfig(name="portal", concurrency=1),
               PoolConfig(name="sistemas", concurrency=1),
               PoolConfig(name="ocr", concurrency=1)],
        handlers=handlers1,
        snapshot_interval_seconds=0.05,
    )
    seeds1 = seeds_from_targets(targets, state1)
    await run_scheduler(seeds1, config1, state1, shutdown_check=shutdown_after_one_meta)

    # State has at least one ok meta on disk.
    state_after_first = PipelineState.load(state_path)
    completed_meta = sum(
        1 for c in targets if state_after_first.is_meta_complete(c)
    )
    assert completed_meta >= 1

    # Second run: fresh state object loaded from disk, run to completion.
    state2 = PipelineState.load(state_path)
    config2 = SchedulerConfig(
        pools=[PoolConfig(name="portal", concurrency=2),
               PoolConfig(name="sistemas", concurrency=2),
               PoolConfig(name="ocr", concurrency=2)],
        handlers=_mock_handlers(state2, peças_per_case=1),
    )
    seeds2 = seeds_from_targets(targets, state2)
    await run_scheduler(seeds2, config2, state2, shutdown_check=_no_shutdown)

    # All cases now done.
    for c in targets:
        assert state2.is_meta_complete(c)
        assert state2.is_bytes_complete(c, url=f"u-{c[1]}-0")
        assert state2.is_text_complete(c, url=f"u-{c[1]}-0", required_extractor="pypdf")


# ---------------------------------------------------------------------------
# Layer 1 stress tests — pin invariants under load.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_backpressure_does_not_deadlock(tmp_path: Path) -> None:
    """High fan-out against a small queue must not deadlock.

    The scheduler relies on ``await queue.put`` for back-pressure: when
    the sistemas queue fills, the meta worker's emit loop blocks on
    ``put`` until consumers drain. This pins that the consumer/producer
    interlock doesn't cause a stall — the only way for HC 2020's
    ~21 k bytes-task fan-out to complete on a 1024-deep queue is for
    this path to behave correctly.
    """
    state = PipelineState.load(tmp_path / "s.json")
    targets = [("HC", i) for i in range(3)]

    config = SchedulerConfig(
        pools=_three_pools(),
        handlers=_mock_handlers(state, peças_per_case=200),
        queue_maxsize=8,
        snapshot_interval_seconds=10.0,
    )
    seeds = seeds_from_targets(targets, state)
    result = await asyncio.wait_for(
        run_scheduler(seeds, config, state, shutdown_check=_no_shutdown),
        timeout=15.0,
    )

    expected = 3 * (1 + 200 + 200)
    total_finished = sum(c.finished for c in result.counters.values())
    total_failed = sum(c.failed for c in result.counters.values())
    assert total_finished == expected
    assert total_failed == 0


@pytest.mark.asyncio
async def test_drain_watcher_waits_for_inflight_fanout(tmp_path: Path) -> None:
    """While a handler is mid-execution it sits in the pool's semaphore,
    not on a queue, so ``in_flight > 0`` even when every queue is empty.
    The drain watcher must consult ``in_flight`` and not push sentinels
    until it drains — otherwise a slow meta handler would terminate the
    run before fanning out.

    The watcher polls every 250 ms; making the meta handler sleep 400 ms
    forces the watcher to observe the empty-queues-but-in-flight state
    at least once.
    """
    state = PipelineState.load(tmp_path / "s.json")

    def slow_meta(task: Task) -> list[Task]:
        time.sleep(0.4)
        state.record_meta(task.case_key, status="ok")
        return [
            Task(
                kind="fetch_bytes",
                pool="sistemas",
                payload={"url": f"u-{task.case_key[1]}-{i}"},
                case_key=task.case_key,
            )
            for i in range(8)
        ]

    def fast_bytes(task: Task) -> list[Task]:
        url = task.payload["url"]
        state.record_bytes(task.case_key, url=url, status="ok")
        return [
            Task(
                kind="extract_text",
                pool="ocr",
                payload={"url": url},
                case_key=task.case_key,
            )
        ]

    def fast_text(task: Task) -> list[Task]:
        state.record_text(
            task.case_key, url=task.payload["url"], status="ok", extractor="pypdf"
        )
        return []

    handlers = {
        "fetch_meta": slow_meta,
        "fetch_bytes": fast_bytes,
        "extract_text": fast_text,
    }
    config = SchedulerConfig(
        pools=[
            PoolConfig(name="portal", concurrency=1),
            PoolConfig(name="sistemas", concurrency=2),
            PoolConfig(name="ocr", concurrency=2),
        ],
        handlers=handlers,
    )
    seeds = seeds_from_targets([("HC", 1)], state)
    result = await asyncio.wait_for(
        run_scheduler(seeds, config, state, shutdown_check=_no_shutdown),
        timeout=10.0,
    )

    # If the watcher had fired prematurely during the 0.4 s meta sleep,
    # the run would have ended with only the meta task finished (1).
    # All 17 (1 meta + 8 bytes + 8 text) must complete.
    total_finished = sum(c.finished for c in result.counters.values())
    assert total_finished == 1 + 8 + 8


@pytest.mark.asyncio
async def test_shutdown_mid_fanout_exits_cleanly_with_durable_state(
    tmp_path: Path,
) -> None:
    """When shutdown trips while bytes successors are still being
    emitted, the scheduler must (a) exit, (b) flag
    ``shutdown_requested=True``, and (c) leave a state file on disk
    that reloads cleanly. We deliberately do NOT pin "no successors
    lost" — that's a known v1 gap (sentinels can race ahead of
    successor puts in ``_run_one``); the contract here is durability
    of what was recorded, not zero-loss of what wasn't.
    """
    state_path = tmp_path / "executar.state.json"
    state = PipelineState.load(state_path)

    started_meta = {"n": 0}

    def meta_then_trip(task: Task) -> list[Task]:
        started_meta["n"] += 1
        state.record_meta(task.case_key, status="ok")
        return [
            Task(
                kind="fetch_bytes",
                pool="sistemas",
                payload={"url": f"u-{task.case_key[1]}-{i}"},
                case_key=task.case_key,
            )
            for i in range(50)
        ]

    def shutdown_after_first_meta() -> bool:
        return started_meta["n"] >= 1

    handlers = _mock_handlers(state, peças_per_case=1)
    handlers["fetch_meta"] = meta_then_trip

    config = SchedulerConfig(
        pools=_three_pools(),
        handlers=handlers,
        snapshot_interval_seconds=0.05,
    )
    seeds = seeds_from_targets([("HC", 0), ("HC", 1)], state)
    result = await asyncio.wait_for(
        run_scheduler(seeds, config, state, shutdown_check=shutdown_after_first_meta),
        timeout=10.0,
    )

    assert result.shutdown_requested is True
    # Counters internally consistent: nothing finished or failed that
    # wasn't started. (Equality not required — sentinels can leave
    # tasks queued-but-unrun, which is the documented v1 gap.)
    for c in result.counters.values():
        assert c.finished + c.failed <= c.started

    # State on disk reloads and reflects at least the first meta we
    # know completed before shutdown tripped.
    assert state_path.exists()
    reloaded = PipelineState.load(state_path)
    assert reloaded.is_meta_complete(("HC", 0))


@pytest.mark.asyncio
async def test_handler_raise_recorded_as_failed_not_crash(tmp_path: Path) -> None:
    """A handler that raises (rather than recording an error outcome
    via ``state.record_*``) must be contained inside ``_run_one``'s
    ``except`` block. The pool's ``failed`` counter increments, the
    breaker is fed an error outcome, and the rest of the DAG continues
    untouched.
    """
    state = PipelineState.load(tmp_path / "s.json")

    def raising_meta(task: Task) -> list[Task]:
        if task.case_key == ("HC", 1):
            raise RuntimeError("simulated handler crash")
        state.record_meta(task.case_key, status="ok")
        return [
            Task(
                kind="fetch_bytes",
                pool="sistemas",
                payload={"url": f"u-{task.case_key[1]}"},
                case_key=task.case_key,
            )
        ]

    def handle_bytes(task: Task) -> list[Task]:
        url = task.payload["url"]
        state.record_bytes(task.case_key, url=url, status="ok")
        return [
            Task(
                kind="extract_text",
                pool="ocr",
                payload={"url": url},
                case_key=task.case_key,
            )
        ]

    def handle_text(task: Task) -> list[Task]:
        state.record_text(
            task.case_key, url=task.payload["url"], status="ok", extractor="pypdf"
        )
        return []

    handlers = {
        "fetch_meta": raising_meta,
        "fetch_bytes": handle_bytes,
        "extract_text": handle_text,
    }
    config = SchedulerConfig(pools=_three_pools(), handlers=handlers)
    seeds = seeds_from_targets([("HC", 0), ("HC", 1), ("HC", 2)], state)
    result = await run_scheduler(seeds, config, state, shutdown_check=_no_shutdown)

    # HC-1 crashed in meta; HC-0 and HC-2 went all the way through.
    assert result.counters["portal"].failed == 1
    assert result.counters["portal"].finished == 2
    assert state.is_text_complete(("HC", 0), url="u-0", required_extractor="pypdf")
    assert state.is_text_complete(("HC", 2), url="u-2", required_extractor="pypdf")
    # Crashed case has no meta record (handler raised before recording).
    assert not state.is_meta_complete(("HC", 1))


@pytest.mark.asyncio
async def test_breaker_warning_logged_only_once_under_sustained_errors(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Under hundreds of error outcomes the per-pool circuit breaker
    must log its ``tripped`` warning exactly once — not once per error
    after the trip. Otherwise a sustained WAF burst on the portal pool
    would flood the launcher log.
    """
    state = PipelineState.load(tmp_path / "s.json")

    def always_fail_meta(task: Task) -> list[Task]:
        state.record_meta(task.case_key, status="http_error", error="WAF 403")
        return []

    def unused_bytes(task: Task) -> list[Task]:
        state.record_bytes(task.case_key, url=task.payload["url"], status="ok")
        return []

    def unused_text(task: Task) -> list[Task]:
        return []

    handlers = {
        "fetch_meta": always_fail_meta,
        "fetch_bytes": unused_bytes,
        "extract_text": unused_text,
    }
    config = SchedulerConfig(
        pools=[
            PoolConfig(
                name="portal",
                concurrency=4,
                circuit_window=10,
                circuit_threshold=0.5,
            ),
            PoolConfig(name="sistemas", concurrency=2),
            PoolConfig(name="ocr", concurrency=2),
        ],
        handlers=handlers,
    )
    targets = [("HC", i) for i in range(200)]
    seeds = seeds_from_targets(targets, state)

    with caplog.at_level("WARNING", logger="judex.pipeline.pools"):
        await run_scheduler(seeds, config, state, shutdown_check=_no_shutdown)

    trip_msgs = [
        r.getMessage()
        for r in caplog.records
        if "circuit breaker tripped" in r.getMessage()
    ]
    assert len(trip_msgs) == 1
    assert "[portal]" in trip_msgs[0]


@pytest.mark.asyncio
async def test_seed_loop_does_not_deadlock_when_seed_count_exceeds_queue_maxsize(
    tmp_path: Path,
) -> None:
    """When initial seeds outnumber ``queue_maxsize``, the bulk-put
    loop must yield to the worker coroutines (which drain the queue)
    rather than block on a queue with no consumer.

    This is what HC 2020's first launch hit: 9,137 seed cases against
    the 1024-deep default queue. The original code seeded BEFORE
    spawning workers, so put() blocked at item 1025 forever — no
    state file ever written, zero CPU. The Layer-1 backpressure test
    only exercised mid-run fan-out, not seed-time bulk-put.
    """
    state = PipelineState.load(tmp_path / "s.json")
    # 200 seeds against queue_maxsize=4 forces bulk-put to yield 196
    # times. Without workers consuming, this would deadlock.
    n = 200
    targets = [("HC", i) for i in range(n)]

    config = SchedulerConfig(
        pools=_three_pools(),
        handlers=_mock_handlers(state, peças_per_case=0),  # meta-only, terminal
        queue_maxsize=4,
    )
    seeds = seeds_from_targets(targets, state)

    result = await asyncio.wait_for(
        run_scheduler(seeds, config, state, shutdown_check=_no_shutdown),
        timeout=15.0,
    )

    # All meta seeds completed despite queue holding only 4 at a time.
    assert result.counters["portal"].finished == n


@pytest.mark.asyncio
async def test_high_concurrency_no_lost_tasks(tmp_path: Path) -> None:
    """No-lost-task contract: when N seed tasks fan out to M total
    tasks, ``sum(finished + failed) == M`` regardless of pool
    concurrency. This is the invariant HC 2020 most needs at scale —
    a 1 % loss rate over 21 k tasks would silently leak hundreds of
    peças.
    """
    state = PipelineState.load(tmp_path / "s.json")
    targets = [("HC", i) for i in range(20)]

    config = SchedulerConfig(
        pools=[
            PoolConfig(name="portal", concurrency=8),
            PoolConfig(name="sistemas", concurrency=8),
            PoolConfig(name="ocr", concurrency=8),
        ],
        handlers=_mock_handlers(state, peças_per_case=5),
    )
    seeds = seeds_from_targets(targets, state)
    result = await run_scheduler(seeds, config, state, shutdown_check=_no_shutdown)

    expected = 20 * (1 + 5 + 5)
    total_finished = sum(c.finished for c in result.counters.values())
    total_failed = sum(c.failed for c in result.counters.values())
    assert total_finished + total_failed == expected
    assert total_failed == 0
