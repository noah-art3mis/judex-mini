"""
Extract meio from process data
"""

from bs4 import BeautifulSoup

from .base import track_extraction_timing


@track_extraction_timing
def extract_meio(soup: BeautifulSoup) -> str | None:
    """Extract meio from badge elements"""
    badges = [b.get_text(strip=True) for b in soup.select(".badge")]
    for badge in badges:
        if "Físico" in badge:
            return "FISICO"
        elif "Eletrônico" in badge:
            return "ELETRONICO"
    return None
