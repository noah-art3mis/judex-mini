"""
Configuration for JUDEX MINI scraper
"""

from dataclasses import dataclass


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
    driver_max_retries: int = 10
    driver_backoff_multiplier: int = 1
    driver_backoff_min: int = 0
    driver_backoff_max: int = 30

    # Retry Configuration - Documents
    document_max_retries: int = 3
    document_backoff_multiplier: int = 1
    document_backoff_min: int = 2
    document_backoff_max: int = 5

    # When True, treat HTTP 403 as a retryable throttle signal. STF's portal
    # issues 403 (not 429) once a sweep trips its WAF rate gate, and the
    # block clears after a few minutes — retrying with exponential backoff
    # rides out the cooldown. Disabled by default because 403 is normally
    # a permanent access denial.
    retry_403: bool = False
