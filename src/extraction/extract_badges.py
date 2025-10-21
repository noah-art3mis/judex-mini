"""
Extract badges from process data
"""

import logging

from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver

from .base import track_extraction_timing


def _is_valid_badge_text(text: str) -> bool:
    """Check if badge text matches valid patterns."""
    if not text:
        return False

    upper = text.upper()
    return (
        "MAIOR DE 60 ANOS" in upper
        or "DOENÇA GRAVE" in upper
        or "DOENCA GRAVE" in upper
    )


def _extract_badges_from_soup(soup: BeautifulSoup) -> list[str]:
    """Extract badges using BeautifulSoup with proper error handling."""
    labels: list[str] = []

    try:
        badges = soup.select(".badge")
        for badge in badges:
            text = badge.get_text(" ", strip=True)
            if _is_valid_badge_text(text):
                labels.append(text)
    except Exception as e:
        logging.warning(f"Error extracting badges: {e}")

    return labels


@track_extraction_timing
def extract_badges(spider, driver: WebDriver, soup: BeautifulSoup) -> list[str]:
    """Extract badges from badge elements with improved error handling."""
    try:
        return _extract_badges_from_soup(soup)
    except Exception as e:
        logging.warning(f"Could not extract badges: {e}")
        return []
