"""Tests for the proxy URL redaction helper.

Proxy URLs in `config/proxies.txt` typically embed credentials
(user:pass@host:port). The redaction helper strips those before the
URL is printed to driver.log / stdout, so rotation events can be
inspected without leaking the provider auth.
"""

from __future__ import annotations

from scripts.run_sweep import _redact_proxy


def test_redact_none_returns_direct_sentinel():
    assert _redact_proxy(None) == "direct"


def test_redact_empty_returns_direct_sentinel():
    assert _redact_proxy("") == "direct"


def test_redact_strips_userinfo_from_http_proxy():
    assert _redact_proxy("http://user:pass@proxy.example:3128") == \
        "http://proxy.example:3128"


def test_redact_strips_userinfo_from_socks5():
    assert _redact_proxy("socks5://user:pass@residential.example:1080") == \
        "socks5://residential.example:1080"


def test_redact_preserves_host_port_without_userinfo():
    # No creds to strip — just passes through
    assert _redact_proxy("socks5://proxy:1080") == "socks5://proxy:1080"


def test_redact_handles_bare_host_without_scheme():
    # Malformed entry — shouldn't crash, should not leak anything
    out = _redact_proxy("user:pass@host:1234")
    assert "user" not in out
    assert "pass" not in out


def test_redact_does_not_leak_password_in_any_output():
    """Regression guard — even if the URL is weird, the secret must not survive."""
    secret = "s3cret-p@ssword!"
    url = f"http://user:{secret}@proxy.example:3128"
    assert secret not in _redact_proxy(url)


def test_redact_does_not_leak_username_in_any_output():
    secret_user = "customer-abc123"
    url = f"http://{secret_user}:pass@proxy.example:3128"
    assert secret_user not in _redact_proxy(url)
