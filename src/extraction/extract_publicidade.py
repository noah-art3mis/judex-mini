"""
Extract publicidade from process data
"""

from bs4 import BeautifulSoup

from .base import track_extraction_timing


@track_extraction_timing
def extract_publicidade(soup: BeautifulSoup) -> str | None:
    """Return 'PUBLICO' or 'SIGILOSO' inferred from badges."""
    badges = [b.get_text(strip=True).upper() for b in soup.select(".badge")]
    if any("SIGILOSO" in b for b in badges):
        return "SIGILOSO"
    if any("PÚBLICO" in b or "PUBLICO" in b for b in badges):
        return "PUBLICO"
    return None
