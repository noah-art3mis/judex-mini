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

from src.config import ScraperConfig
from src.utils.get_element import find_element_by_xpath


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


def _check_for_errors(driver, document: str):
    """Check for common error conditions in page source."""
    page_source = driver.page_source
    if "403 Forbidden" in page_source:
        raise Exception("403 Forbidden - Access denied")
    if "CAPTCHA" in page_source:
        raise Exception("CAPTCHA detected")
    if "502 Bad Gateway" in page_source:
        raise Exception("502 Bad Gateway")
    if "Processo não encontrado" in document:
        raise Exception("Processo não encontrado")
    _xpath_descricao = '//*[@id="descricao-procedencia"]'
    if find_element_by_xpath(driver, _xpath_descricao) == "":
        raise Exception("descricao-procedencia não encontrado")


def load_page_with_retry(driver, URL, process_name: str, config: ScraperConfig) -> str:

    @retry(
        stop=stop_after_attempt(config.driver_max_retries),
        wait=wait_exponential(
            multiplier=config.driver_backoff_multiplier,
            min=config.driver_backoff_min,
            max=config.driver_backoff_max,
        ),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    def _retry_operation() -> str:
        logging.debug(f"Attempting {process_name}")

        driver.get(URL)
        time.sleep(config.driver_sleep_time)

        document = find_element_by_xpath(
            driver,
            '//*[@id="conteudo"]',
            initial_delay=config.initial_delay,
            timeout=config.webdriver_timeout,
        )

        _check_for_errors(driver, document)

        logging.info(f"{process_name}: loaded")
        return document

    return _retry_operation()
