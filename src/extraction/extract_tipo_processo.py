"""
Extract tipo_processo from process data
"""

from bs4 import BeautifulSoup

from .base import normalize_spaces, track_extraction_timing


@track_extraction_timing
def extract_tipo_processo(soup: BeautifulSoup) -> str | None:
    """Extract tipo_processo from .processo-dados elements"""
    for div in soup.select(".processo-dados"):
        text = div.get_text(" ", strip=True)
        if text.startswith("Tipo:"):
            return normalize_spaces(text.split(":", 1)[1])
    return None
