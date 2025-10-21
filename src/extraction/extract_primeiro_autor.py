"""
Extract primeiro_autor from process data
"""

from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver

from .base import track_extraction_timing


@track_extraction_timing
def extract_primeiro_autor(driver: WebDriver, soup: BeautifulSoup) -> str | None:
    """Extract primeiro_autor from partes data"""
    from .extract_partes import extract_partes

    partes = extract_partes(driver, soup)
    if not partes:
        return None

    # Find first author (RECTE, REQTE, etc.)
    for parte in partes:
        if parte.get("tipo", "").startswith(("RECTE", "REQTE", "AUTOR")):
            return parte.get("nome")

    return None
