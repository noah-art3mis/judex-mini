"""
Extract relator from process data
"""

from bs4 import BeautifulSoup

from .base import normalize_spaces, track_extraction_timing


@track_extraction_timing
def extract_relator(soup: BeautifulSoup) -> str | None:
    """Extract relator from .processo-dados elements"""
    for div in soup.select(".processo-dados"):
        text = div.get_text(" ", strip=True)
        if text.startswith("Relator(a):"):
            relator = normalize_spaces(text.split(":", 1)[1])
            # Remove "MIN." prefix if present
            if relator.startswith("MIN. "):
                relator = relator[5:]  # Remove "MIN. " (5 characters)
            # Normalize empty strings to None
            if not relator:
                return None
            return relator
    return None
