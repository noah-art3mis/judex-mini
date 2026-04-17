"""Per-host latency-aware throttle.

Mirrors Scrapy's AutoThrottle: the delay between successive GETs to a
host converges on `observed_latency / target_concurrency`, clamped to
a configured [min, max] range, and never *decreases* when the last
response was an error.
"""

from __future__ import annotations

import threading
import time

import pytest

from src.utils.adaptive_throttle import AdaptiveThrottle


def test_current_delay_starts_at_start_delay() -> None:
    t = AdaptiveThrottle(start_delay=0.5)
    assert t.current_delay("a.test") == 0.5


def test_record_moves_delay_toward_latency_over_target_concurrency() -> None:
    # target_concurrency=1, latency=2.0 → target_delay=2.0
    # new = (current + target) / 2 = (0 + 2.0) / 2 = 1.0
    t = AdaptiveThrottle(target_concurrency=1.0, start_delay=0.0, max_delay=10.0)
    t.record("a.test", latency=2.0)
    assert t.current_delay("a.test") == pytest.approx(1.0)


def test_record_with_concurrency_scales_target() -> None:
    # target_concurrency=4, latency=2.0 → target_delay=0.5
    # new = (0 + 0.5) / 2 = 0.25
    t = AdaptiveThrottle(target_concurrency=4.0, start_delay=0.0, max_delay=10.0)
    t.record("a.test", latency=2.0)
    assert t.current_delay("a.test") == pytest.approx(0.25)


def test_record_clamps_to_max_delay() -> None:
    t = AdaptiveThrottle(target_concurrency=1.0, start_delay=0.0, max_delay=0.5)
    t.record("a.test", latency=10.0)
    assert t.current_delay("a.test") == 0.5


def test_record_clamps_to_min_delay() -> None:
    t = AdaptiveThrottle(target_concurrency=1.0, start_delay=1.0, min_delay=0.8)
    # latency=0 → target=0 → new=0.5 → clamped up to 0.8
    t.record("a.test", latency=0.0)
    assert t.current_delay("a.test") == 0.8


def test_record_error_does_not_decrease_delay() -> None:
    t = AdaptiveThrottle(target_concurrency=1.0, start_delay=2.0, max_delay=10.0)
    # Without the error guard: new_delay would drop to 1.0.
    # With the error guard: delay stays at 2.0 because the server returned 4xx/5xx.
    t.record("a.test", latency=2.0, was_error=True)
    assert t.current_delay("a.test") == 2.0


def test_record_error_still_allows_increase() -> None:
    t = AdaptiveThrottle(target_concurrency=1.0, start_delay=0.5, max_delay=10.0)
    # Latency is high *and* error → delay should climb, not stay pinned.
    t.record("a.test", latency=4.0, was_error=True)
    assert t.current_delay("a.test") > 0.5


def test_hosts_are_isolated() -> None:
    t = AdaptiveThrottle(target_concurrency=1.0, start_delay=0.0, max_delay=10.0)
    t.record("a.test", latency=4.0)
    assert t.current_delay("a.test") == pytest.approx(2.0)
    assert t.current_delay("b.test") == 0.0


def test_wait_blocks_for_current_delay(monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    t = AdaptiveThrottle(start_delay=0.42)
    t.wait("a.test")
    assert slept == [0.42]


def test_wait_does_not_sleep_when_delay_is_zero(monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    t = AdaptiveThrottle(start_delay=0.0)
    t.wait("a.test")
    assert slept == []


def test_concurrent_record_is_safe() -> None:
    t = AdaptiveThrottle(target_concurrency=1.0, start_delay=0.0, max_delay=10.0)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(200):
                t.record("a.test", latency=1.0)
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert errors == []
    # Some value between min and max — the important thing is no crash / no KeyError.
    d = t.current_delay("a.test")
    assert 0.0 <= d <= 10.0
