"""
Extract data_protocolo from process data
"""

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from .base import normalize_spaces, track_extraction_timing


@track_extraction_timing
def extract_data_protocolo(driver: WebDriver, soup: BeautifulSoup) -> str | None:
    """Extract data_protocolo using XPath"""
    try:
        element = driver.find_element(
            By.XPATH, '//*[@id="informacoes-completas"]/div[2]/div[1]/div[2]/div[2]'
        )
        return normalize_spaces(element.text)
    except Exception:
        return None
