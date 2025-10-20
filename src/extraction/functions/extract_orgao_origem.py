"""
Extract orgao_origem from process data
"""

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from .base import handle_extraction_errors, normalize_spaces, track_extraction_timing


@track_extraction_timing
@handle_extraction_errors(default_value=None, log_errors=True)
def extract_orgao_origem(driver: WebDriver, soup: BeautifulSoup) -> str | None:
    """Extract orgao_origem using XPath"""
    try:
        element = driver.find_element(
            By.XPATH, '//*[@id="informacoes-completas"]/div[2]/div[1]/div[2]/div[4]'
        )
        return normalize_spaces(element.text)
    except Exception:
        return None
