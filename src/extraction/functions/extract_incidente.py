"""
Extract incidente from process data
"""

from bs4 import BeautifulSoup

from .base import handle_extraction_errors, normalize_spaces, track_extraction_timing


@track_extraction_timing
@handle_extraction_errors(default_value=None, log_errors=True)
def extract_incidente(soup: BeautifulSoup) -> str | None:
    """Extract incidente from .processo-dados elements"""
    for div in soup.select(".processo-dados"):
        text = div.get_text(" ", strip=True)
        if text.startswith("Incidente:"):
            return normalize_spaces(text.split(":", 1)[1])
    return None
