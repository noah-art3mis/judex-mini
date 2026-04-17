"""Per-host latency-aware throttle.

Stand-in for Scrapy's AutoThrottle. Tracks observed response latency
per host and converges the inter-request delay on
`latency / target_concurrency`, clamped to `[min_delay, max_delay]`.
Never *decreases* the delay after an error response — the server is
already complaining; backing off further is not warranted, but neither
is speeding up.

Thread-safe: `_TAB_WORKERS=4` workers call `record()` / `wait()`
concurrently during `fetch_process`, so per-host state is guarded by
a single lock. Lock contention is trivial at our request rate.
"""

from __future__ import annotations

import threading
import time


class AdaptiveThrottle:
    def __init__(
        self,
        *,
        target_concurrency: float = 1.0,
        min_delay: float = 0.0,
        max_delay: float = 60.0,
        start_delay: float = 0.0,
    ) -> None:
        if target_concurrency <= 0:
            raise ValueError("target_concurrency must be > 0")
        if min_delay < 0 or max_delay < min_delay:
            raise ValueError("require 0 <= min_delay <= max_delay")
        self._target_concurrency = target_concurrency
        self._min = min_delay
        self._max = max_delay
        self._start = max(min_delay, min(start_delay, max_delay))
        self._lock = threading.Lock()
        self._delays: dict[str, float] = {}

    def current_delay(self, host: str) -> float:
        with self._lock:
            return self._delays.get(host, self._start)

    def record(self, host: str, latency: float, *, was_error: bool = False) -> None:
        """Update the per-host delay estimator with one observed latency."""
        target = latency / self._target_concurrency
        with self._lock:
            current = self._delays.get(host, self._start)
            new = (current + target) / 2.0
            if was_error and new < current:
                new = current
            new = max(self._min, min(self._max, new))
            self._delays[host] = new

    def wait(self, host: str) -> None:
        """Block for the current per-host delay before the next request."""
        d = self.current_delay(host)
        if d > 0:
            time.sleep(d)
