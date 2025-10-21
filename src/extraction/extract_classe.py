"""
Extract classe from process data
"""

from bs4 import BeautifulSoup

from .base import track_extraction_timing


@track_extraction_timing
def extract_classe(soup: BeautifulSoup) -> str | None:
    """Extract classe from .processo-dados elements"""
    for div in soup.select(".processo-dados"):
        text = div.get_text(" ", strip=True)
        if text.startswith("Classe:"):
            return text.split(":", 1)[1].strip()
    return None