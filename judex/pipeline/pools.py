"""Per-pool runtime: semaphore + circuit breaker + optional throttle/proxies.

The scheduler creates one ``Pool`` per ``PoolConfig`` at startup and
holds it for the run's lifetime. Pools encapsulate the per-pool
state that doesn't belong in either the scheduler core (which is
shape-agnostic) or the handlers (which are stateless functions of
their input task).

Per the spec's v1 lock:

* **Breaker is mandatory.** Tracks per-task status. When ``tripped()``
  returns true, the scheduler logs a warning. v1 does NOT halt the
  pool — that's a v1.5 feature waiting on real-world WAF data.
* **Throttle is optional.** Construction-time opt-in via
  ``PoolConfig.throttle_max_delay``. Wired onto the pool but
  consumption is handler-side (handlers call ``pool.throttle.wait``);
  v1 handlers don't yet — left as a v1.5 hook.
* **Proxies are optional.** Loaded from
  ``PoolConfig.proxy_pool_path`` if set; otherwise ``None``. Same
  story as throttle: scaffolded on the pool, consumed by handlers
  in v1.5.

The split between "in v1" and "scaffold for v1.5" is deliberate:
the spec calls for the *shape* of per-pool config to exist; the
*behaviour* of throttle/proxy can land later without re-architecting.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from judex.pipeline.models import PoolConfig, PoolName
from judex.scraping.proxy_pool import ProxyPool
from judex.sweeps.shared import CircuitBreaker
from judex.utils.adaptive_throttle import AdaptiveThrottle


log = logging.getLogger(__name__)


@dataclass
class Pool:
    """Per-pool runtime. Constructed once per run by ``build_pools``."""

    config: PoolConfig
    semaphore: asyncio.Semaphore
    breaker: CircuitBreaker
    throttle: Optional[AdaptiveThrottle] = None
    proxies: Optional[ProxyPool] = None
    _trip_logged: bool = field(default=False, init=False)

    @property
    def name(self) -> PoolName:
        return self.config.name

    @property
    def concurrency(self) -> int:
        return self.config.concurrency

    def record_outcome(self, *, ok: bool) -> None:
        """Update the breaker. The scheduler calls this once per
        completed task, with ``ok`` derived from the state-recorded
        status of the task that just ran.
        """
        self.breaker.record("ok" if ok else "error")
        if self.breaker.tripped() and not self._trip_logged:
            log.warning(
                "[%s] circuit breaker tripped (window=%d threshold=%.2f); "
                "v1 logs only — pool continues dispatching",
                self.name,
                self.config.circuit_window,
                self.config.circuit_threshold,
            )
            self._trip_logged = True

    @property
    def tripped(self) -> bool:
        return self.breaker.tripped()


def build_pools(configs: list[PoolConfig]) -> dict[PoolName, Pool]:
    """Construct one ``Pool`` per config. Loads proxy pool from disk
    if ``proxy_pool_path`` is set; otherwise leaves ``proxies=None``.
    """
    pools: dict[PoolName, Pool] = {}
    for cfg in configs:
        proxies: Optional[ProxyPool] = None
        if cfg.proxy_pool_path:
            path = Path(cfg.proxy_pool_path)
            if path.exists():
                proxies = ProxyPool.from_file(path)
                log.info("[%s] loaded %d proxies from %s", cfg.name, proxies.size(), path)
            else:
                log.warning("[%s] proxy_pool_path=%s does not exist; running direct-IP",
                            cfg.name, path)

        # AdaptiveThrottle is opt-in via the config knob; default of
        # 60.0 max_delay is conservative. v1 handlers don't yet
        # consume it (see module docstring), so we leave it None
        # unless explicitly enabled — avoids quiet pre-sleeps that
        # would surprise direct-IP users.
        throttle: Optional[AdaptiveThrottle] = None
        # No way to "disable" via PoolConfig in v1; future work.

        pool = Pool(
            config=cfg,
            semaphore=asyncio.Semaphore(cfg.concurrency),
            breaker=CircuitBreaker(window=cfg.circuit_window, threshold=cfg.circuit_threshold),
            throttle=throttle,
            proxies=proxies,
        )
        pools[cfg.name] = pool
    return pools
