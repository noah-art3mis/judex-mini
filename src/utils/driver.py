import logging
import time
from contextlib import contextmanager
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import ScraperConfig


def setup_driver(user_agent: str) -> WebDriver:
    chrome_options = Options()
    chrome_options.add_argument("--incognito")
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=920,600")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument(f"--user-agent={user_agent}")
    return webdriver.Chrome(options=chrome_options)


@contextmanager
def get_driver(user_agent: str):
    """Context manager for WebDriver that ensures proper cleanup."""
    driver = None
    try:
        driver = setup_driver(user_agent)
        yield driver
    finally:
        if driver:
            driver.quit()
            logging.debug("Driver cleanup completed")


def create_retry_decorator(config: ScraperConfig):
    """Create retry decorator with configurable parameters."""
    return retry(
        stop=stop_after_attempt(config.driver_max_retries),
        wait=wait_exponential(
            multiplier=config.driver_backoff_multiplier,
            min=config.driver_backoff_min,
            max=config.driver_backoff_max,
        ),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )


def retry_driver_operation(
    driver, URL, operation_name="operation", config: Optional[ScraperConfig] = None
):
    """Retry driver operations with exponential backoff."""
    if config is None:
        config = ScraperConfig()

    # Create retry decorator with config
    retry_decorator = create_retry_decorator(config)

    @retry_decorator
    def _retry_operation():
        logging.debug(f"Attempting {operation_name}")

        driver.get(URL)
        time.sleep(config.driver_sleep_time)

        # Check for common error conditions
        if "403 Forbidden" in driver.page_source:
            raise Exception("403 Forbidden - Access denied")
        if "CAPTCHA" in driver.page_source:
            raise Exception("CAPTCHA detected")
        if "502 Bad Gateway" in driver.page_source:
            raise Exception("502 Bad Gateway")

        logging.info(f"{operation_name}")
        return True

    return _retry_operation()
