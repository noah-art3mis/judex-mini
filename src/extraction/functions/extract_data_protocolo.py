"""
Extract data_protocolo from process data
"""

from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver

from .base import handle_extraction_errors, normalize_spaces, track_extraction_timing


@track_extraction_timing
@handle_extraction_errors(default_value=None, log_errors=True)
def extract_data_protocolo(driver: WebDriver, soup: BeautifulSoup) -> str | None:
    """Extract data_protocolo from .processo-dados elements"""
    for div in soup.select(".processo-dados"):
        text = div.get_text(" ", strip=True)
        if text.startswith("Data do Protocolo:"):
            return normalize_spaces(text.split(":", 1)[1])
    return None
