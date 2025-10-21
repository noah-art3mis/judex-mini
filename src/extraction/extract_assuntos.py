"""
Extract assuntos from process data
"""

from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver

from .base import normalize_spaces, track_extraction_timing


@track_extraction_timing
def extract_assuntos(driver: WebDriver, soup: BeautifulSoup) -> list:
    """Extract assuntos from the process page"""
    assuntos_list = []

    try:
        # Look for assuntos in the process data
        for div in soup.select(".processo-dados"):
            text = div.get_text(" ", strip=True)
            if text.startswith("Assunto:"):
                assunto_text = normalize_spaces(text.split(":", 1)[1])
                if assunto_text:
                    assuntos_list.append(assunto_text)
    except Exception:
        pass

    return assuntos_list
