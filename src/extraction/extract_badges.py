"""
Extract badges from process data
"""

from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver

from .base import track_extraction_timing


@track_extraction_timing
def extract_badges(spider, driver: WebDriver, soup: BeautifulSoup) -> list | None:
    """Extract badges from badge elements"""
    try:
        labels: list[str] = []
        for badge in soup.select(".badge"):
            text = badge.get_text(" ", strip=True)
            if not text:
                continue
            upper = text.upper()
            if (
                "MAIOR DE 60 ANOS" in upper
                or "DOENÇA GRAVE" in upper
                or "DOENCA GRAVE" in upper
            ):
                labels.append(text)
        return labels
    except Exception:
        return []
