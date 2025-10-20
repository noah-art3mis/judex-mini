"""
Extract incidente from process data
"""

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from .base import handle_extraction_errors, track_extraction_timing


@track_extraction_timing
@handle_extraction_errors(default_value=None, log_errors=True)
def extract_incidente(driver: WebDriver, soup: BeautifulSoup) -> int | None:
    """Extract incidente from hidden input field"""
    try:
        element = driver.find_element(By.ID, "incidente")
        value = element.get_attribute("value")
        if value and value.isdigit():
            return int(value)
        return None
    except Exception:
        return None
