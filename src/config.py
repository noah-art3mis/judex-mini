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
    webdriver_timeout: int = 10
    initial_delay: float = 1
    driver_sleep_time: float = 1
    always_wait_time: float = 2
    driver_max_retries_for_missing: int = 5

    # Retry Configuration - Driver
    driver_max_retries: int = 5
    driver_backoff_multiplier: int = 1
    driver_backoff_min: int = 0
    driver_backoff_max: int = 10

    # Retry Configuration - Documents
    document_max_retries: int = 3
    document_backoff_multiplier: int = 1
    document_backoff_min: int = 2
    document_backoff_max: int = 5
