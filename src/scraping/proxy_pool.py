"""Per-IP rotation pool with cool-down tracking.

Used by the sweep driver's proactive-rotation loop: rotate IPs every
~4.5 min (safely under STF's WAF layer-1 window) so no single proxy
ever accumulates enough request history to trip the 403 threshold.

Design matches docs/rate-limits.md § Wall taxonomy and severity
timeline — the pool is how we stay in the "under_utilising" or
"healthy" regime on every individual IP indefinitely.

Pool semantics:
- ``pick()`` returns the longest-idle cold proxy, or ``None`` if all
  proxies are currently in cool-down. Callers decide what to do when
  all hot (stop + wait, or fall back to direct).
- ``mark_hot(proxy, minutes)`` called after rotating AWAY from a
  proxy — sets ``not_before = now + minutes*60``.
- ``time_until_next_available()`` returns seconds until the soonest
  proxy becomes cold, used by the driver to sleep instead of busy-wait.

Proxies are opaque URL strings (``socks5://host:port``,
``http://user:pass@host:port``, …) — anything ``requests`` accepts.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional


def _normalize_proxy_url(raw: str) -> str:
    """Accept the handful of proxy-dump formats provider dashboards emit.

    Residential providers vary: Bright Data hands out
    ``http://user:pass@host:port`` URLs directly, ScrapeGW / Webshare
    dump ``host:port:user:pass`` (one per line), some copy-paste flows
    end up as ``user:pass@host:port`` without scheme. Rather than fail
    on any of them, coerce to a full ``http://`` URL that requests can
    pass into ``session.proxies``.

    Unschemed input is assumed to be HTTP (not SOCKS5) — the most
    common residential case. Pass a full ``socks5://`` URL to override.
    """
    s = raw.strip()
    if s.startswith("http://") or s.startswith("https://") or s.startswith("socks5://") or s.startswith("socks4://"):
        return s
    if "@" in s:
        # e.g. "user:pass@host:port" — just needs a scheme
        return f"http://{s}"
    parts = s.split(":")
    if len(parts) == 4:
        # "host:port:user:pass" dump format
        host, port, user, password = parts
        return f"http://{user}:{password}@{host}:{port}"
    if len(parts) == 2:
        # bare "host:port" — no auth
        return f"http://{s}"
    # Leave as-is; downstream will surface the bad URL.
    return s


class ProxyPool:
    def __init__(
        self,
        proxies: list[str],
        *,
        _now: Optional[Callable[[], float]] = None,
    ) -> None:
        self._proxies: list[str] = list(proxies)
        # Monotonic timestamp after which a proxy is cold again.
        # 0.0 means "never used, cold since forever".
        self._not_before: dict[str, float] = {p: 0.0 for p in self._proxies}
        self._now = _now or time.monotonic

    def size(self) -> int:
        return len(self._proxies)

    def pick(self) -> Optional[str]:
        if not self._proxies:
            return None
        now = self._now()
        cold = [p for p in self._proxies if self._not_before[p] <= now]
        if not cold:
            return None
        # Longest-idle: smallest not_before (cooled earliest / never used).
        return min(cold, key=lambda p: self._not_before[p])

    def mark_hot(self, proxy: str, minutes: float) -> None:
        if proxy not in self._not_before:
            return
        self._not_before[proxy] = self._now() + minutes * 60.0

    def time_until_next_available(self) -> float:
        if not self._proxies:
            return 0.0
        now = self._now()
        soonest = min(self._not_before.values())
        return max(0.0, soonest - now)

    @classmethod
    def from_file(cls, path: Path) -> "ProxyPool":
        if not path.exists():
            return cls([])
        lines = path.read_text(encoding="utf-8").splitlines()
        proxies = [
            _normalize_proxy_url(s) for s in lines
            if s.strip() and not s.strip().startswith("#")
        ]
        # Deduplicate while preserving order — providers sometimes
        # emit the same line repeatedly; dict/string keys in the pool
        # collapse duplicates anyway, but warn visibly so the user
        # knows they don't have the IP diversity they think they do.
        seen: dict[str, None] = {}
        for p in proxies:
            seen.setdefault(p, None)
        return cls(list(seen.keys()))
