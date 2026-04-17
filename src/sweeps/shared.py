"""Shared primitives for sweep drivers.

CircuitBreaker, signal handlers, exception classifier, percentile
helper, and a generic guarded-iteration driver — used by both the
process sweep (scripts/run_sweep.py) and the PDF sweep
(src/sweeps/pdf_driver.py).
"""

from __future__ import annotations

import signal
import time
from collections import deque
from datetime import datetime, timezone
from statistics import median, quantiles
from typing import Any, Callable, Optional, Sequence, TypeVar

import requests

from src.scraping.http_session import RetryableHTTPError

T = TypeVar("T")

_SHUTDOWN = False


def install_signal_handlers() -> None:
    """Install SIGINT/SIGTERM handlers that set the shutdown flag.

    Drivers must poll `shutdown_requested()` in their inner loop and
    stop after the in-flight item finishes. Re-calling is idempotent
    (replaces the handlers, which is fine).
    """
    def handler(signum: int, _frame: Any) -> None:
        global _SHUTDOWN
        _SHUTDOWN = True
        print(
            f"\n!! received signal {signum}; finishing current item and stopping",
            flush=True,
        )

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def shutdown_requested() -> bool:
    return _SHUTDOWN


def _reset_shutdown_for_tests() -> None:
    """Test hook — clear the shutdown flag so tests can stay isolated."""
    global _SHUTDOWN
    _SHUTDOWN = False


class CircuitBreaker:
    """Abort after recent error rate exceeds threshold fraction of the window.

    Parameterised on which status strings count as errors, so the same
    breaker serves both the process sweep (status in {"error"}) and the
    PDF sweep (status in {"http_error", "extract_error"}).
    """

    def __init__(self, window: int, threshold: float) -> None:
        self.window = window
        self.threshold = threshold
        self._recent: deque[str] = deque(maxlen=window)

    def record(self, status: str) -> None:
        self._recent.append(status)

    def tripped(self, error_statuses: tuple[str, ...] = ("error",)) -> bool:
        if len(self._recent) < self.window:
            return False
        errors = sum(1 for s in self._recent if s in error_statuses)
        return errors / self.window > self.threshold


def classify_exception(e: BaseException) -> tuple[str, Optional[int], Optional[str]]:
    """Return (error_type, http_status, url) extracted from a fetch exception.

    Handles RetryableHTTPError (has .status_code + .url directly),
    requests.HTTPError (pull from .response), and fall-through to just
    the class name.
    """
    etype = type(e).__name__
    http_status: Optional[int] = None
    url: Optional[str] = None
    if isinstance(e, RetryableHTTPError):
        http_status = e.status_code
        url = e.url or None
    elif isinstance(e, requests.HTTPError):
        resp = getattr(e, "response", None)
        if resp is not None:
            http_status = getattr(resp, "status_code", None)
            url = getattr(resp, "url", None)
    return etype, http_status, url


def iterate_with_guards(
    items: Sequence[T],
    *,
    on_item: Callable[[int, int, T], Optional[str]],
    should_resume_skip: Callable[[T], bool] = lambda _item: False,
    on_skip: Callable[[T], None] = lambda _item: None,
    breaker: Optional["CircuitBreaker"] = None,
    error_statuses: tuple[str, ...] = ("error",),
    trip_noun: str = "items",
    progress_every: int = 25,
    on_progress: Callable[[int, int], None] = lambda _i, _n: None,
    throttle_sleep: float = 0.0,
) -> bool:
    """Walk `items` with the usual sweep guardrails.

    For each item the loop:
      1. Checks the shutdown flag (from `install_signal_handlers()`) — if
         set, prints `"  stopping before item {i}/{n}"` and breaks.
      2. Calls `should_resume_skip(item)`; if truthy, invokes `on_skip`
         and continues (no breaker accounting, no throttle).
      3. Invokes `on_item(i, n, item)`. The callback does the real work
         (fetch, store, counter updates) and returns either a status
         string for the circuit breaker or None (skip breaker accounting).
      4. Records the status on `breaker` (if provided); if the breaker
         trips, prints a message and breaks out.
      5. Invokes `on_progress(i, n)` every `progress_every` items.
      6. `time.sleep(throttle_sleep)` before the next item (skipped on
         the final item).

    Returns True iff the circuit breaker tripped. Callers that care can
    translate that to an exit code; callers that don't can ignore it.
    """
    n = len(items)
    for i, item in enumerate(items, 1):
        if shutdown_requested():
            print(f"  stopping before item {i}/{n}", flush=True)
            return False

        if should_resume_skip(item):
            on_skip(item)
            continue

        status = on_item(i, n, item)

        if breaker is not None and status is not None:
            breaker.record(status)
            if breaker.tripped(error_statuses):
                print(
                    f"\n!! circuit breaker tripped: >{breaker.threshold:.0%} "
                    f"error-like statuses in the last {breaker.window} "
                    f"{trip_noun}. Stopping at {i}/{n}.",
                    flush=True,
                )
                return True

        if progress_every and i % progress_every == 0:
            on_progress(i, n)

        if throttle_sleep > 0 and i < n:
            time.sleep(throttle_sleep)
    return False


def elapsed_rate_eta(
    started: datetime, i: int, n: int
) -> tuple[float, float, float]:
    """(elapsed_s, rate_per_s, eta_s) based on items done so far.

    rate and eta are 0.0 when the run hasn't accumulated any wall time
    yet — callers display them uniformly.
    """
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    rate = i / elapsed if elapsed > 0 else 0.0
    eta_s = (n - i) / rate if rate > 0 else 0.0
    return elapsed, rate, eta_s


def percentiles(values: list[float]) -> tuple[float, float, float]:
    """Return (p50, p90, max). Zeros when empty, scalar expansion at n=1."""
    if not values:
        return (0.0, 0.0, 0.0)
    if len(values) == 1:
        v = values[0]
        return (v, v, v)
    qs = quantiles(values, n=10)
    p50 = median(values)
    p90 = qs[8]
    return (p50, p90, max(values))
