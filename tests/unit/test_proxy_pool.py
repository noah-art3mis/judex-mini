"""Tests for src.scraping.proxy_pool.ProxyPool.

The pool tracks per-proxy cool-down windows (in monotonic time) and
returns the longest-idle proxy that is currently cold. Used by the
sweep driver's proactive-rotation loop to cycle IPs before any one of
them trips STF's WAF layer-1 threshold.
"""

from __future__ import annotations

import pytest

from src.scraping.proxy_pool import ProxyPool, _normalize_proxy_url


def test_empty_pool_returns_none():
    pool = ProxyPool([])
    assert pool.pick() is None


def test_single_proxy_always_returned():
    pool = ProxyPool(["socks5://a:1080"])
    assert pool.pick() == "socks5://a:1080"
    assert pool.pick() == "socks5://a:1080"


def test_pick_cycles_through_proxies_fifo():
    pool = ProxyPool(["p1", "p2", "p3"])
    # first pick — any proxy (impl detail: first in list)
    a = pool.pick()
    pool.mark_hot(a, minutes=5)
    b = pool.pick()
    assert b != a
    pool.mark_hot(b, minutes=5)
    c = pool.pick()
    assert c not in (a, b)


def test_mark_hot_takes_proxy_out_of_rotation():
    clock = [0.0]
    pool = ProxyPool(["p1", "p2"], _now=lambda: clock[0])
    pool.mark_hot("p1", minutes=5)
    # p1 is hot until t=300; picking should return p2
    assert pool.pick() == "p2"


def test_mark_hot_cooldown_elapses():
    clock = [0.0]
    pool = ProxyPool(["p1", "p2"], _now=lambda: clock[0])
    pool.mark_hot("p1", minutes=5)
    # 6 minutes later — p1 should be cool again
    clock[0] = 6 * 60.0
    assert pool.pick() in ("p1", "p2")
    # both are cool — prefer the longest-idle (p1, never picked since cooldown)
    # or whichever the impl chooses; both are valid — just shouldn't fail


def test_all_hot_returns_none():
    clock = [0.0]
    pool = ProxyPool(["p1", "p2"], _now=lambda: clock[0])
    pool.mark_hot("p1", minutes=5)
    pool.mark_hot("p2", minutes=5)
    assert pool.pick() is None


def test_pick_prefers_longest_idle_when_multiple_cool():
    clock = [0.0]
    pool = ProxyPool(["p1", "p2", "p3"], _now=lambda: clock[0])
    # Use all three, varying hot-until times
    pool.mark_hot("p1", minutes=1)  # cool at t=60
    clock[0] = 10.0
    pool.mark_hot("p2", minutes=1)  # cool at t=70
    clock[0] = 20.0
    pool.mark_hot("p3", minutes=1)  # cool at t=80
    # at t=100, all are cool; p1 cooled first → longest idle
    clock[0] = 100.0
    assert pool.pick() == "p1"


def test_time_until_next_available_when_all_hot():
    clock = [0.0]
    pool = ProxyPool(["p1", "p2"], _now=lambda: clock[0])
    pool.mark_hot("p1", minutes=2)   # cool at t=120
    pool.mark_hot("p2", minutes=5)   # cool at t=300
    # at t=0, soonest cool is p1 at t=120
    assert pool.time_until_next_available() == pytest.approx(120.0)


def test_time_until_next_available_when_some_cool():
    clock = [0.0]
    pool = ProxyPool(["p1", "p2"], _now=lambda: clock[0])
    pool.mark_hot("p1", minutes=5)
    # p2 is currently cool → 0 wait
    assert pool.time_until_next_available() == 0.0


def test_from_file_parses_one_url_per_line(tmp_path):
    p = tmp_path / "proxies.txt"
    p.write_text(
        "socks5://a:1080\n"
        "http://user:pass@b:3128\n"
        "\n"                              # blank line ignored
        "# commented line ignored\n"
        "socks5://c:1080\n"
    )
    pool = ProxyPool.from_file(p)
    assert pool.size() == 3


def test_from_file_missing_returns_empty_pool(tmp_path):
    p = tmp_path / "does-not-exist.txt"
    pool = ProxyPool.from_file(p)
    assert pool.size() == 0


def test_mark_hot_unknown_proxy_is_noop():
    # Rotating through a proxy not in the pool shouldn't crash —
    # happens if the pool is reconfigured mid-sweep.
    pool = ProxyPool(["p1"])
    pool.mark_hot("never-added", minutes=5)
    assert pool.pick() == "p1"


# ----- _normalize_proxy_url --------------------------------------------------


def test_normalize_passes_http_url_unchanged():
    assert _normalize_proxy_url("http://user:pass@host:3128") == \
        "http://user:pass@host:3128"


def test_normalize_passes_socks5_url_unchanged():
    assert _normalize_proxy_url("socks5://user:pass@host:1080") == \
        "socks5://user:pass@host:1080"


def test_normalize_converts_host_port_user_pass_dump():
    # ScrapeGW / many residential providers dump in this format.
    assert _normalize_proxy_url("rp.example.com:6060:user-country-br:secret") == \
        "http://user-country-br:secret@rp.example.com:6060"


def test_normalize_prepends_scheme_for_userinfo_host_port():
    assert _normalize_proxy_url("user:pass@host:3128") == \
        "http://user:pass@host:3128"


def test_normalize_handles_bare_host_port():
    assert _normalize_proxy_url("host:3128") == "http://host:3128"


def test_from_file_parses_dump_format(tmp_path):
    p = tmp_path / "proxies.txt"
    p.write_text(
        "rp.example.com:6060:user-country-br:secret\n"
        "http://already-a-url:port\n"
    )
    pool = ProxyPool.from_file(p)
    assert pool.size() == 2
    assert "http://user-country-br:secret@rp.example.com:6060" in pool._not_before
    assert "http://already-a-url:port" in pool._not_before
