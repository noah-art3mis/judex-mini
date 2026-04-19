"""
Configuration for JUDEX MINI scraper
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from judex.utils.adaptive_throttle import AdaptiveThrottle
    from judex.utils.request_log import RequestLog


@dataclass
class ScraperConfig:
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    )
    base_url: str = "https://portal.stf.jus.br"

    # Configuracao padrao:
    # - nao toma backoff
    # - itens demoram 20s cada
    # - 100 itens demora 40min

    # Timeouts & Delays
    webdriver_timeout: int = 120
    initial_delay: float = 0.2
    driver_sleep_time: float = 0.1
    driver_max_retries_for_missing: int = 5
    button_wait: float = 10

    # Retry Configuration - Driver
    # Budget widened 2026-04-16 after the D-run rate-budget experiments
    # (docs/reports/2026-04-16-D-rate-budget.md): STF's WAF block
    # can last up to ~4.5 min; 20 × 60 s of exponential backoff covers it
    # with ~4× headroom.
    driver_max_retries: int = 20
    driver_backoff_multiplier: int = 1
    driver_backoff_min: int = 0
    driver_backoff_max: int = 60

    # Retry Configuration - Documents
    document_max_retries: int = 3
    document_backoff_multiplier: int = 1
    document_backoff_min: int = 2
    document_backoff_max: int = 5

    # Treat HTTP 403 as a retryable throttle signal. STF's portal issues
    # 403 (not 429) once a sweep trips its WAF rate gate, and the block
    # clears after a few minutes — retrying with exponential backoff rides
    # out the cooldown. Default-on after the D-run experiments
    # (docs/reports/2026-04-16-D-rate-budget.md) showed 199/200
    # completion with retry-403 vs 107/1000 without.
    retry_403: bool = True

    # Optional observability hooks. When set, `_http_get_with_retry`
    # drives them on every GET: `throttle.wait(host)` before the call,
    # `throttle.record(host, latency, was_error=...)` after, and
    # `request_log.log(...)` once the response (or exception) lands.
    # Leaving them None preserves the original pure-retry behavior.
    throttle: Optional["AdaptiveThrottle"] = None
    request_log: Optional["RequestLog"] = None
