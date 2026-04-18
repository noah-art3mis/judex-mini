"""HTTP session + retry primitives shared by every component that
hits STF over HTTP — the scraper, PDF driver, sweep drivers, OCR
pipeline, and density probes.

STF's portal uses cookie-based ASP sessions and a behavioral WAF
that returns **403** (not 429) when an IP exceeds a sliding threshold.
This module centralises:

- ``new_session()``   — a `requests.Session` preconfigured with a
  browser-shaped ``User-Agent`` (non-browser UAs like ``curl/*`` get
  permanent 403s) and ``verify=False`` for WSL sandboxes that lack a
  full CA bundle. The site is public so no secrets travel here.

- ``_http_get_with_retry()`` — every outbound GET goes through this.
  Tenacity retries 429 + 5xx + connection errors; 403 retry is opt-in
  via ``cfg.retry_403`` (the WAF block lifts within minutes). Wires
  ``cfg.throttle.wait/record`` for adaptive per-host pacing and
  ``cfg.request_log.log`` for the SQLite request archive.

- ``RetryableHTTPError`` — sentinel exception that tenacity matches on.

- ``_decode()`` — STF serves UTF-8 without declaring a charset, so
  ``requests`` defaults to Latin-1 → mojibake. Always decode through
  here.

Carved out of ``src/scraping/scraper.py`` on 2026-04-17 once the file crossed
the 600-line ceiling (CLAUDE.md § Conventions).
"""

from __future__ import annotations

import logging
import time
from typing import Optional
from urllib.parse import urlparse

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.config import ScraperConfig

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)


def new_session(proxy: Optional[str] = None) -> requests.Session:
    """Build a `requests.Session` preconfigured for STF.

    ``proxy`` is any URL requests accepts (``socks5://host:port``,
    ``http://user:pass@host:port``). When set, both http and https
    traffic routes through it — used by the sweep driver's
    proxy-rotation loop to cycle IPs before L1 fires. See
    ``src/scraping/proxy_pool.py`` and docs/rate-limits.md §
    Wall taxonomy.
    """
    s = requests.Session()
    s.headers.update({"User-Agent": DEFAULT_UA})
    s.verify = False  # WSL sandbox lacks full CA bundle; site is public anyway
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    return s


class RetryableHTTPError(Exception):
    """Raised for HTTP status codes that warrant a retry (429, 5xx, opt-in 403)."""

    def __init__(self, status_code: int, url: str = "") -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(f"HTTP {status_code} {url}".rstrip())


_RETRYABLE_NETWORK_EXCS = (
    requests.ConnectionError,
    requests.Timeout,
)


def _should_retry(exc: BaseException) -> bool:
    return isinstance(exc, (RetryableHTTPError,) + _RETRYABLE_NETWORK_EXCS)


def _http_get_with_retry(
    session: requests.Session,
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: int = 30,
    allow_redirects: bool = True,
    config: Optional[ScraperConfig] = None,
) -> requests.Response:
    """GET with tenacity retries on 429, 5xx, and network errors.

    4xx responses other than 429 raise immediately (no retry) — they signal
    a client-side problem that won't resolve on its own.
    """
    cfg = config or ScraperConfig()

    @retry(
        stop=stop_after_attempt(cfg.driver_max_retries),
        wait=wait_exponential(
            multiplier=cfg.driver_backoff_multiplier,
            min=cfg.driver_backoff_min,
            max=cfg.driver_backoff_max,
        ),
        retry=retry_if_exception(_should_retry),
        reraise=True,
        before_sleep=lambda st: logging.debug(
            f"Retry {st.attempt_number}/{cfg.driver_max_retries} for GET {url}: "
            f"{st.outcome.exception()}"
        ),
    )
    def _go() -> requests.Response:
        host = urlparse(url).hostname or ""
        if cfg.throttle is not None:
            cfg.throttle.wait(host)

        started = time.perf_counter()
        try:
            r = session.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout,
                allow_redirects=allow_redirects,
            )
        except Exception:
            elapsed = time.perf_counter() - started
            if cfg.throttle is not None:
                cfg.throttle.record(host, elapsed, was_error=True)
            if cfg.request_log is not None:
                cfg.request_log.log(
                    url=url, status=None,
                    elapsed_ms=int(elapsed * 1000),
                )
            raise

        elapsed = time.perf_counter() - started
        is_error = r.status_code >= 400
        if cfg.throttle is not None:
            cfg.throttle.record(host, elapsed, was_error=is_error)
        if cfg.request_log is not None:
            cfg.request_log.log(
                url=url,
                status=r.status_code,
                elapsed_ms=int(elapsed * 1000),
                bytes=len(r.content) if r.content is not None else None,
            )

        if (
            r.status_code == 429
            or 500 <= r.status_code < 600
            or (cfg.retry_403 and r.status_code == 403)
        ):
            raise RetryableHTTPError(r.status_code, url)
        r.raise_for_status()  # non-429 4xx: don't retry
        return r

    return _go()


def _decode(r: requests.Response) -> str:
    """STF serves UTF-8 without a charset; requests defaults to Latin-1 → mojibake."""
    r.encoding = "utf-8"
    return r.text
