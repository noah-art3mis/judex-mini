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

from judex.scraping.http_session import RetryableHTTPError

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


def request_shutdown() -> None:
    """Programmatically set the shutdown flag — used by CliffDetector's
    collapse handler to stop the sweep the same way SIGTERM does.
    """
    global _SHUTDOWN
    _SHUTDOWN = True


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


# Regime labels mirror the operating-regime table in
# docs/rate-limits.md § Wall taxonomy and severity timeline.
REGIMES = (
    "warming",
    "under_utilising",
    "healthy",
    "l2_engaged",
    "approaching_collapse",
    "collapse",
)


class CliffDetector:
    """Rolling-window detector for WAF layer-2 engagement.

    Classifies the sweep's current operating regime via two composite
    axes: **WAF-shaped** fail-rate and p95 wall_s. Either axis alone
    can promote the regime — the adaptive-block signature (long stalls
    with still-ok statuses) is caught by the p95 axis, while V-style
    collapse (many retry-403 fails) is caught by the fail-rate axis.

    A fail is **WAF-shaped** if any of:

    - ``wall_s > 15`` — retry-403 exhausted after tenacity backoff
    - ``http_status in {403, 429}`` or 5xx — explicit WAF / server signal
    - ``retries`` non-empty — tenacity fired, even if the call succeeded

    Fast fails with no HTTP error and no retries (``NoIncidente`` —
    HC doesn't exist in STF) do **not** count toward the fail-rate
    axis. This is the 2026-04-17 calibration fix: the first proxy
    canary tripped false collapse because corpus sparsity was read as
    WAF pressure. Thresholds still match
    docs/rate-limits.md § Wall taxonomy.
    """

    MIN_OBS = 20

    def __init__(self, window: int = 50) -> None:
        self._waf_bad: deque[bool] = deque(maxlen=window)
        self._walls: deque[float] = deque(maxlen=window)
        # Kept for backwards compatibility with any caller that reads
        # ``_statuses`` directly; the regime logic does not use it.
        self._statuses: deque[str] = deque(maxlen=window)

    def observe(
        self,
        status: str,
        wall_s: float,
        *,
        http_status: Optional[int] = None,
        retries: Optional[dict[str, int]] = None,
    ) -> bool:
        is_bad = status != "ok" and _is_waf_shape(wall_s, http_status, retries)
        self._waf_bad.append(is_bad)
        self._walls.append(wall_s)
        self._statuses.append(status)
        return is_bad

    def regime(self) -> str:
        n = len(self._waf_bad)
        if n < self.MIN_OBS:
            return "warming"
        fails = sum(self._waf_bad)
        fail_rate = fails / n
        # Axis B (p95 wall_s) is unreliable on a partially-filled window:
        # at n == MIN_OBS == 20 with the default window=50, the p95 index
        # lands on the maximum element, so a single slow record
        # (e.g. one 70s HTTP stall with no retries, no fails) trips
        # collapse without any WAF signal. Gate axis B on window fullness
        # so only genuinely-multi-record-spread latency signals
        # (≥ 3 records at p95-threshold+ in a full 50-record window)
        # contribute. Axis A (WAF-shaped fail rate) is not gated — it
        # still fires early when fail rate is catastrophic.
        window_full = len(self._walls) == self._walls.maxlen
        if window_full:
            walls_sorted = sorted(self._walls)
            p95 = walls_sorted[int(0.95 * n)]
        else:
            p95 = 0.0
        if fail_rate > 0.30 or p95 > 60:
            return "collapse"
        if fail_rate > 0.20 or p95 > 30:
            return "approaching_collapse"
        if fail_rate > 0.10 or p95 > 15:
            return "l2_engaged"
        if fail_rate > 0.05:
            return "healthy"
        return "under_utilising"


def _is_waf_shape(
    wall_s: float,
    http_status: Optional[int],
    retries: Optional[dict[str, int]],
) -> bool:
    if wall_s > 15.0:
        return True
    if http_status is not None:
        if http_status in (403, 429):
            return True
        if 500 <= http_status < 600:
            return True
    if retries:
        return True
    return False


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
