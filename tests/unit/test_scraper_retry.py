"""Retry behavior for the HTTP scraper path.

These tests pin down the tenacity wrapper around network GETs:
429 and 5xx are retried, 4xx (non-429) is not, and the wrapper
eventually gives up after max_attempts.
"""

from unittest.mock import Mock

import pytest
import requests

from src import scraper as scraper_http
from src.config import ScraperConfig


def _fake_response(status_code: int, text: str = "") -> Mock:
    r = Mock()
    r.status_code = status_code
    r.text = text
    r.headers = {}
    if status_code >= 400:
        err = requests.HTTPError(f"{status_code} error")
        r.raise_for_status = Mock(side_effect=err)
    else:
        r.raise_for_status = Mock()
    return r


@pytest.fixture
def fast_config() -> ScraperConfig:
    """Zero-backoff config so retry tests run instantly."""
    return ScraperConfig(
        driver_max_retries=3,
        driver_backoff_min=0,
        driver_backoff_max=0,
        driver_backoff_multiplier=0,
    )


def test_http_get_retries_on_429(fast_config: ScraperConfig) -> None:
    session = Mock()
    session.get = Mock(side_effect=[_fake_response(429), _fake_response(200, "ok")])

    r = scraper_http._http_get_with_retry(
        session,
        "http://x.test/page",
        params={"a": 1},
        headers={"X-H": "v"},
        config=fast_config,
    )

    assert r.status_code == 200
    assert session.get.call_count == 2


def test_http_get_retries_on_5xx(fast_config: ScraperConfig) -> None:
    session = Mock()
    session.get = Mock(
        side_effect=[_fake_response(500), _fake_response(502), _fake_response(200)]
    )

    r = scraper_http._http_get_with_retry(
        session,
        "http://x.test/page",
        params={},
        headers={},
        config=fast_config,
    )

    assert r.status_code == 200
    assert session.get.call_count == 3


def test_http_get_gives_up_after_max_attempts(fast_config: ScraperConfig) -> None:
    session = Mock()
    session.get = Mock(return_value=_fake_response(503))

    with pytest.raises(scraper_http.RetryableHTTPError):
        scraper_http._http_get_with_retry(
            session,
            "http://x.test/page",
            params={},
            headers={},
            config=fast_config,
        )

    assert session.get.call_count == fast_config.driver_max_retries


def test_http_get_does_not_retry_404(fast_config: ScraperConfig) -> None:
    session = Mock()
    session.get = Mock(return_value=_fake_response(404))

    with pytest.raises(requests.HTTPError):
        scraper_http._http_get_with_retry(
            session,
            "http://x.test/page",
            params={},
            headers={},
            config=fast_config,
        )

    assert session.get.call_count == 1


def test_http_get_retries_on_connection_error(fast_config: ScraperConfig) -> None:
    session = Mock()
    session.get = Mock(
        side_effect=[requests.ConnectionError("boom"), _fake_response(200)]
    )

    r = scraper_http._http_get_with_retry(
        session,
        "http://x.test/page",
        params={},
        headers={},
        config=fast_config,
    )

    assert r.status_code == 200
    assert session.get.call_count == 2


def test_http_get_does_not_retry_403_when_disabled(fast_config: ScraperConfig) -> None:
    # Opt-out: with retry_403 off, 403 is treated as a permanent access denial.
    fast_config.retry_403 = False
    session = Mock()
    session.get = Mock(return_value=_fake_response(403))

    with pytest.raises(requests.HTTPError):
        scraper_http._http_get_with_retry(
            session,
            "http://x.test/page",
            params={},
            headers={},
            config=fast_config,
        )

    assert session.get.call_count == 1


def test_http_get_retries_on_403_by_default(fast_config: ScraperConfig) -> None:
    # STF returns 403 as its WAF throttle signal; retry with backoff.
    session = Mock()
    session.get = Mock(side_effect=[_fake_response(403), _fake_response(403), _fake_response(200)])

    r = scraper_http._http_get_with_retry(
        session,
        "http://x.test/page",
        params={},
        headers={},
        config=fast_config,
    )

    assert r.status_code == 200
    assert session.get.call_count == 3
