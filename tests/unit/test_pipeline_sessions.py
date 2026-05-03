"""Tests for the rotating-session abstraction.

Pins the behaviour the proxy-aware handlers depend on:

* direct-IP fallback when no pool is given
* per-call proxy reuse up to ``requests_per_proxy`` budget
* rotation when the budget is spent
* on-failure cool-down for WAF-classified errors
* graceful fall-through when the pool is fully cooled
"""

from __future__ import annotations

from typing import Optional

import pytest

from judex.pipeline.sessions import RotatingSession
from judex.scraping.proxy_pool import ProxyPool


def test_direct_ip_when_no_pool() -> None:
    """No pool → single session reused forever, no rotation, no proxy."""
    holder = RotatingSession(proxies=None)
    s1 = holder.session()
    s2 = holder.session()
    s3 = holder.session()

    # Same session object across calls — no rotation.
    assert s1 is s2 is s3
    # Direct-IP: requests.Session has empty proxies dict.
    assert holder.current_proxy is None
    assert s1.proxies == {}


def test_picks_proxy_when_pool_provided() -> None:
    pool = ProxyPool(["http://p1:8080", "http://p2:8080"])
    holder = RotatingSession(proxies=pool, requests_per_proxy=3)

    s = holder.session()
    assert holder.current_proxy in {"http://p1:8080", "http://p2:8080"}
    # Session is bound to the picked proxy on both http and https.
    assert s.proxies["http"] == holder.current_proxy
    assert s.proxies["https"] == holder.current_proxy


def test_reuses_session_within_budget() -> None:
    """Within the per-proxy budget, ``session()`` returns the same
    object — connection reuse matters at scale."""
    pool = ProxyPool(["http://p1:8080", "http://p2:8080"])
    holder = RotatingSession(proxies=pool, requests_per_proxy=3)

    s1 = holder.session()
    s2 = holder.session()
    s3 = holder.session()
    assert s1 is s2 is s3


def test_rotates_after_budget_exhausted() -> None:
    """After ``requests_per_proxy`` calls, the next call rotates to a
    different proxy (different session object, same pool)."""
    pool = ProxyPool(["http://p1:8080", "http://p2:8080"])
    holder = RotatingSession(proxies=pool, requests_per_proxy=2)

    s1 = holder.session()
    first_proxy = holder.current_proxy
    holder.session()  # 2nd use within budget
    s_after = holder.session()  # 3rd → rotation
    assert s_after is not s1
    # Pool has 2 proxies, no cooldowns yet, so rotation picks the
    # not-recently-used one (longest idle).
    assert holder.current_proxy != first_proxy


def test_report_failure_marks_proxy_hot_and_forces_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A WAF-classified failure must cool the current proxy and force
    the next ``session()`` call to rotate, regardless of remaining
    budget."""
    pool = ProxyPool(["http://p1:8080", "http://p2:8080"])
    holder = RotatingSession(proxies=pool, requests_per_proxy=100, cooldown_minutes=1.0)

    # Stub classify_exception so the test doesn't depend on the exact
    # exception type plumbing in judex.sweeps.shared.
    def fake_classify(exc: BaseException) -> tuple[str, Optional[int], None]:
        return ("waf_403", 403, None)

    monkeypatch.setattr("judex.sweeps.shared.classify_exception", fake_classify)

    holder.session()
    proxy_at_failure = holder.current_proxy
    holder.report_failure(RuntimeError("simulated WAF block"))

    next_session = holder.session()
    # Forced rotation.
    assert holder.current_proxy != proxy_at_failure
    # And the failed proxy is hot (won't be picked until cooldown
    # expires); pool.pick should not return it now.
    picked = pool.pick()
    while picked == proxy_at_failure:
        # Should never happen, but guard against it: pick should
        # never return a hot proxy.
        pytest.fail(f"hot proxy {proxy_at_failure!r} was returned by pool.pick")
    assert next_session is not None


def test_report_failure_non_waf_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-WAF failure (timeout / DNS / 500) must NOT cool the
    current proxy — those errors are infrastructure, not reputation."""
    pool = ProxyPool(["http://p1:8080"])
    holder = RotatingSession(proxies=pool, requests_per_proxy=100)

    def fake_classify(exc: BaseException) -> tuple[str, Optional[int], None]:
        return ("timeout", None, None)

    monkeypatch.setattr("judex.sweeps.shared.classify_exception", fake_classify)

    holder.session()
    proxy_before = holder.current_proxy
    holder.report_failure(TimeoutError("simulated timeout"))

    # Single proxy in the pool, never cooled, so .pick() still returns it.
    assert pool.pick() == proxy_before
    # Budget unchanged — no forced rotation.
    next_session = holder.session()
    assert next_session is not None
    assert holder.current_proxy == proxy_before


def test_falls_back_to_direct_ip_when_pool_fully_cooled() -> None:
    """When every proxy is hot, ``pick`` returns None; the holder
    builds a direct-IP session rather than blocking."""
    pool = ProxyPool(["http://p1:8080"])
    holder = RotatingSession(proxies=pool, requests_per_proxy=1, cooldown_minutes=10.0)

    holder.session()
    pool.mark_hot("http://p1:8080", minutes=10.0)

    # Budget exhausted by the first call → next session() rotates,
    # but pool is fully cooled, so the new session is direct-IP.
    fallback = holder.session()
    assert holder.current_proxy is None
    assert fallback.proxies == {}
