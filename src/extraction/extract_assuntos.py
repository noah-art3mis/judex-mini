"""
Extract assuntos from process data
"""

import logging

from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver

from src.utils.get_element import find_element_by_xpath

from .base import normalize_spaces, track_extraction_timing


def _extract_assuntos_from_soup(soup: BeautifulSoup) -> list[str]:
    """Extract assuntos from BeautifulSoup object with error handling."""
    assuntos_list = []

    try:
        for li in soup.find_all("li"):
            assunto_text = li.get_text(strip=True)
            if assunto_text:
                cleaned_text = normalize_spaces(assunto_text)
                if cleaned_text:  # Only add non-empty cleaned text
                    assuntos_list.append(cleaned_text)
    except Exception as e:
        logging.warning(f"Error extracting assuntos from soup: {e}")

    return assuntos_list


@track_extraction_timing
def extract_assuntos(driver: WebDriver, soup: BeautifulSoup) -> list[str]:
    """Extract assuntos with improved error handling and type safety."""
    try:
        assuntos_html = find_element_by_xpath(
            driver, '//*[@id="informacoes-completas"]/div[1]/div[2]'
        )
        soup_assuntos = BeautifulSoup(assuntos_html, "html.parser")
        return _extract_assuntos_from_soup(soup_assuntos)
    except Exception as e:
        logging.warning(f"Could not extract assuntos: {e}")
        return []
