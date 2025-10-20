import logging
import time
from contextlib import contextmanager

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


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
            logging.info("Driver cleanup completed")


# Retry decorator for driver operations
@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((Exception,)),
    reraise=True,
)
def retry_driver_operation(driver, URL, operation_name="operation"):
    """Retry driver operations with exponential backoff."""
    logging.info(f"Attempting {operation_name} for URL: {URL}")

    driver.get(URL)
    time.sleep(3)

    # Check for common error conditions
    if "403 Forbidden" in driver.page_source:
        raise Exception("403 Forbidden - Access denied")
    if "CAPTCHA" in driver.page_source:
        raise Exception("CAPTCHA detected")
    if "502 Bad Gateway" in driver.page_source:
        raise Exception("502 Bad Gateway")

    logging.info(f"Successfully completed {operation_name}")
    return True
