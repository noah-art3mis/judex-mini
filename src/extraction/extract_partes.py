"""
Extract partes from process data
"""

import logging

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from src.utils.text_utils import normalize_spaces

from .base import track_extraction_timing


def _extract_partes_from_soup(soup: BeautifulSoup) -> list[dict]:
    """Extract partes using BeautifulSoup CSS selectors."""
    partes = []

    # Find all divs with processo-partes class
    elementos = soup.select("div[class*='processo-partes']")

    # Process elements in pairs (tipo, nome)
    for i in range(0, len(elementos), 2):
        if i + 1 >= len(elementos):
            break

        tipo_elem = elementos[i]
        nome_elem = elementos[i + 1]

        tipo_text = normalize_spaces(tipo_elem.get_text(strip=True))
        nome_text = normalize_spaces(nome_elem.get_text(strip=True))

        if not tipo_text or not nome_text:
            continue

        partes.append(
            {
                "index": len(partes) + 1,
                "tipo": tipo_text,
                "nome": nome_text,
            }
        )

    return partes


def _extract_single_parte_element(element, index: int) -> dict | None:
    """Extract data from a single parte element."""
    try:
        # Get HTML and parse with BeautifulSoup
        html = element.get_attribute("outerHTML")
        soup = BeautifulSoup(html, "html.parser")

        # Extract tipo and nome
        tipo_elem = soup.select_one("div[class*='processo-partes']")
        if not tipo_elem:
            return None

        tipo_text = normalize_spaces(tipo_elem.get_text(strip=True))

        # Look for the next sibling element for nome
        nome_elem = tipo_elem.find_next_sibling("div")
        if not nome_elem:
            return None

        nome_text = normalize_spaces(nome_elem.get_text(strip=True))

        if not tipo_text or not nome_text:
            return None

        return {
            "index": index,
            "tipo": tipo_text,
            "nome": nome_text,
        }
    except Exception as e:
        logging.warning(f"Could not extract parte: {e}")
        return None


@track_extraction_timing
def extract_partes(driver: WebDriver, soup: BeautifulSoup) -> list:
    """Extract partes using BeautifulSoup approach for better reliability."""
    try:
        # Find the partes section
        partes_section = driver.find_element(By.ID, "resumo-partes")

        # Get HTML and parse with BeautifulSoup
        html = partes_section.get_attribute("innerHTML")
        soup = BeautifulSoup(html, "html.parser")

        # Extract partes using BeautifulSoup
        partes_list = _extract_partes_from_soup(soup)

        return partes_list

    except Exception as e:
        logging.warning(f"Could not extract partes: {e}")
        return []
