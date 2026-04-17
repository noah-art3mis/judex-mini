"""Shared primitives for sweep drivers.

CircuitBreaker, signal handlers, exception classifier, percentile
helper — used by both the process sweep (scripts/run_sweep.py) and
the PDF sweep (src/pdf_driver.py).
"""

from __future__ import annotations

import signal
from collections import deque
from statistics import median, quantiles
from typing import Any, Optional

import requests

from src.scraper import RetryableHTTPError

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
