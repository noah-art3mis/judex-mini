"""Rotating-session wrapper for proxy-aware HTTP handlers.

The unified pipeline's ``handle_fetch_meta`` / ``handle_fetch_bytes``
need a session that:

* defaults to direct-IP when no proxy pool is provided
* rotates through a :class:`ProxyPool` periodically when one is
* marks a proxy hot on a WAF-classified failure so it cools off

This is the minimum-viable subset of legacy ``run_sweep``'s
session-holder pattern. Things deliberately *not* in v1.5:

* time-based rotation (``proxy_rotate_seconds``) — rotation is
  request-counted only here. Legacy uses both. Wall-time rotation
  matters when the per-IP request rate is low; under the unified
  pipeline's tight WAF schedule, request count tracks WAF reputation
  about as well as wall time.
* breaker-feedback driven rotation — the per-pool circuit breaker in
  ``judex.pipeline.pools.Pool`` already trips on aggregate error rate,
  but right now its only effect is a one-shot warning log. Driving
  rotation off the breaker is a separate (v1.5) deepening.

The intent is: enable Layer-3-style sharded sweeps with a ``--proxy-pool``
file *today*, without yet committing to the full rotation discipline.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from judex.scraping.http_session import new_session
from judex.scraping.proxy_pool import ProxyPool


log = logging.getLogger(__name__)


_DEFAULT_REQUESTS_PER_PROXY = 50
"""How many requests a session is reused for before rotating to a new
proxy. Picked to balance TLS-handshake amortisation (which favours
fewer rotations) against per-IP WAF reputation accumulation (which
favours more rotations). 50 ≈ legacy's 270 s window at 5 s/request."""

_DEFAULT_COOLDOWN_MINUTES = 4.0
"""Cooldown applied to a proxy after a WAF-classified failure. Matches
``download_driver.py``'s default."""


class RotatingSession:
    """A session-holder that picks proxies from a pool and rotates.

    When ``proxies`` is ``None`` the holder is direct-IP: ``session()``
    returns the same single ``requests.Session`` for the run's
    lifetime, no rotation, and ``report_failure`` is a no-op.

    When ``proxies`` is a :class:`ProxyPool`, ``session()`` lazily
    constructs a session bound to a picked proxy; after
    ``requests_per_proxy`` calls the next ``session()`` rotates to a
    fresh proxy. ``report_failure(exc)`` inspects the exception and,
    if it classifies as a WAF block, marks the current proxy hot
    *and* forces the next ``session()`` call to rotate.
    """

    def __init__(
        self,
        proxies: Optional[ProxyPool],
        *,
        requests_per_proxy: int = _DEFAULT_REQUESTS_PER_PROXY,
        cooldown_minutes: float = _DEFAULT_COOLDOWN_MINUTES,
    ) -> None:
        self._proxies = proxies
        self._requests_per_proxy = requests_per_proxy
        self._cooldown_minutes = cooldown_minutes
        self._session: Optional[requests.Session] = None
        self._current_proxy: Optional[str] = None
        self._uses_remaining = 0

    @property
    def current_proxy(self) -> Optional[str]:
        """The proxy URL the current session is bound to. ``None``
        means either direct-IP or 'no session yet'."""
        return self._current_proxy

    def session(self) -> requests.Session:
        """Return a session bound to the currently-active proxy.

        Lazy-constructs on first call; rotates when the per-proxy
        request budget is exhausted.
        """
        if self._session is None or self._uses_remaining <= 0:
            self._rotate()
        # Treat direct-IP as an unlimited budget so we don't churn
        # sessions when there's nothing to rotate to.
        if self._proxies is not None:
            self._uses_remaining -= 1
        return self._session  # type: ignore[return-value]

    def _rotate(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:  # noqa: BLE001
                pass
        # Nudge the just-used proxy to the back of the longest-idle
        # queue — but only if it's currently cold. Without the nudge,
        # two never-used proxies share ``_not_before=0.0`` and
        # ``ProxyPool.pick``'s ``min`` keeps returning the same one,
        # so rotation is a no-op. The cold-only check matters because
        # ``report_failure`` may have already set a longer cooldown,
        # and ``mark_hot(..., minutes=0)`` would overwrite it.
        if self._proxies is not None and self._current_proxy is not None:
            now = self._proxies._now()
            already_hot = (
                self._proxies._not_before.get(self._current_proxy, 0.0) > now
            )
            if not already_hot:
                self._proxies.mark_hot(self._current_proxy, minutes=0.0)
        proxy: Optional[str] = None
        if self._proxies is not None:
            proxy = self._proxies.pick()
            if proxy is None:
                # Pool exhausted (every proxy hot). Fall back to
                # direct-IP for this session — better than blocking.
                # Caller can choose to back off via the breaker.
                wait_s = self._proxies.time_until_next_available()
                log.warning(
                    "rotating-session: proxy pool fully cooled (%.0fs until next); "
                    "falling back to direct-IP", wait_s,
                )
        self._session = new_session(proxy=proxy)
        self._current_proxy = proxy
        self._uses_remaining = self._requests_per_proxy

    def report_failure(self, exc: BaseException) -> None:
        """Hook for handlers: tell the holder a request just failed.

        WAF-classified failures cool the current proxy and force the
        next ``session()`` to rotate. Other failures are no-ops here
        (they're already accounted for by the per-pool circuit
        breaker).
        """
        if self._proxies is None or self._current_proxy is None:
            return
        from judex.sweeps.shared import classify_exception

        kind, _http_status, _ = classify_exception(exc)
        if kind == "waf_403":
            self._proxies.mark_hot(self._current_proxy, minutes=self._cooldown_minutes)
            self._uses_remaining = 0  # force rotation next .session()

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:  # noqa: BLE001
                pass
            self._session = None
