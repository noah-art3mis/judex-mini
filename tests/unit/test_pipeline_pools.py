"""Pool-runtime contracts: breaker behaviour + per-pool isolation.

These tests pin the spec's per-pool fail-isolation property: a
sistemas WAF storm that trips the sistemas breaker must not crash
the pipeline or affect portal/ocr breaker state. They also confirm
the trip event is logged (observability) but does NOT halt
dispatch in v1.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from judex.pipeline.models import PoolConfig, Task
from judex.pipeline.pools import Pool, build_pools
from judex.pipeline.runner import run_pipeline
from judex.pipeline.state import PipelineState


def _config(name: str = "portal", *, window: int = 10, threshold: float = 0.5) -> PoolConfig:
    return PoolConfig(
        name=name,  # type: ignore[arg-type]
        concurrency=2,
        circuit_window=window,
        circuit_threshold=threshold,
    )


def test_pool_breaker_starts_untripped() -> None:
    pools = build_pools([_config()])
    assert pools["portal"].tripped is False


def test_pool_breaker_trips_above_threshold() -> None:
    """50% threshold over a 10-task window: 6 errors trip it."""
    pools = build_pools([_config(window=10, threshold=0.5)])
    pool = pools["portal"]
    for _ in range(4):
        pool.record_outcome(ok=True)
    assert pool.tripped is False
    for _ in range(6):
        pool.record_outcome(ok=False)
    assert pool.tripped is True


def test_pool_breaker_does_not_trip_below_threshold() -> None:
    pools = build_pools([_config(window=10, threshold=0.5)])
    pool = pools["portal"]
    for _ in range(7):
        pool.record_outcome(ok=True)
    for _ in range(3):
        pool.record_outcome(ok=False)
    assert pool.tripped is False


def test_pool_breaker_window_isolates_old_errors() -> None:
    """Breaker window=10: old errors fall out as new oks come in."""
    pools = build_pools([_config(window=10, threshold=0.5)])
    pool = pools["portal"]
    for _ in range(10):
        pool.record_outcome(ok=False)
    assert pool.tripped is True
    for _ in range(10):
        pool.record_outcome(ok=True)
    assert pool.tripped is False


def test_pools_are_independent() -> None:
    """Tripping portal must not trip sistemas or ocr."""
    pools = build_pools([
        _config("portal", window=5, threshold=0.5),
        _config("sistemas", window=5, threshold=0.5),
        _config("ocr", window=5, threshold=0.5),
    ])
    for _ in range(5):
        pools["portal"].record_outcome(ok=False)
    assert pools["portal"].tripped is True
    assert pools["sistemas"].tripped is False
    assert pools["ocr"].tripped is False


def test_pool_trip_logs_warning_once(caplog: pytest.LogCaptureFixture) -> None:
    """The 'circuit breaker tripped' warning fires on the FIRST trip
    transition, not every subsequent record. (Otherwise a tripped
    pool would spam the log.)"""
    pools = build_pools([_config(window=5, threshold=0.5)])
    pool = pools["portal"]

    with caplog.at_level(logging.WARNING, logger="judex.pipeline.pools"):
        for _ in range(5):
            pool.record_outcome(ok=False)
        # Continue recording — warning must NOT fire again.
        for _ in range(5):
            pool.record_outcome(ok=False)

    trip_warnings = [
        r for r in caplog.records
        if "circuit breaker tripped" in r.getMessage()
    ]
    assert len(trip_warnings) == 1


def test_pool_proxy_path_missing_logs_warning(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """A configured-but-nonexistent proxy file warns and falls back
    to direct-IP, rather than crashing the run."""
    cfg = PoolConfig(
        name="sistemas",
        concurrency=2,
        proxy_pool_path=str(tmp_path / "missing.txt"),
    )
    with caplog.at_level(logging.WARNING, logger="judex.pipeline.pools"):
        pools = build_pools([cfg])
    assert pools["sistemas"].proxies is None
    assert any("does not exist" in r.getMessage() for r in caplog.records)


def test_pool_proxy_path_loads(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("http://10.0.0.1:8080\nhttp://10.0.0.2:8080\n# comment\n\n")
    cfg = PoolConfig(
        name="sistemas",
        concurrency=2,
        proxy_pool_path=str(proxy_file),
    )
    pools = build_pools([cfg])
    assert pools["sistemas"].proxies is not None
    assert pools["sistemas"].proxies.size() == 2


# ---------------------------------------------------------------------------
# Integration: breaker observation across a full pipeline run
# ---------------------------------------------------------------------------


def _failing_handlers_factory(state: PipelineState, **_: object) -> dict[str, object]:
    """All bytes tasks fail with http_error. Meta succeeds; the
    failure pattern should trip the sistemas breaker without
    crashing the run.
    """

    def handle_meta(task: Task) -> list[Task]:
        state.record_meta(task.case_key, status="ok")
        return [
            Task(kind="fetch_bytes", pool="sistemas",
                 payload={"url": f"u-{task.case_key[1]}-{i}"},
                 case_key=task.case_key)
            for i in range(3)
        ]

    def handle_bytes(task: Task) -> list[Task]:
        state.record_bytes(task.case_key, url=task.payload["url"],
                           status="http_error", error="WAF 403")
        return []

    def handle_text(task: Task) -> list[Task]:
        state.record_text(task.case_key, url=task.payload["url"], status="ok", extractor="pypdf")
        return []

    return {
        "fetch_meta": handle_meta,
        "fetch_bytes": handle_bytes,
        "extract_text": handle_text,
    }


def test_breaker_does_not_halt_pipeline(tmp_path: Path) -> None:
    """Even when sistemas breaker trips, the run completes (in v1
    the breaker is observability-only). State reflects every
    bytes-task failure; meta succeeds for every case."""
    saida = tmp_path / "run"
    targets = [("HC", i) for i in range(20)]  # 20×3 = 60 bytes failures

    rc = run_pipeline(
        targets=targets, saida=saida, provedor="pypdf",
        handlers_factory=_failing_handlers_factory,
    )
    assert rc == 0  # clean exit despite breaker trip

    state = PipelineState.load(saida / "executar.state.json")
    for c in targets:
        assert state.is_meta_complete(c)
        for i in range(3):
            assert not state.is_bytes_complete(c, url=f"u-{c[1]}-{i}")
