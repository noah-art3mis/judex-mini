"""
Extract partes from process data
"""

import logging

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from .base import handle_extraction_errors, normalize_spaces, track_extraction_timing


@track_extraction_timing
@handle_extraction_errors(default_value=[], log_errors=True)
def extract_partes(driver: WebDriver, soup: BeautifulSoup) -> list:
    """Extract partes using updated CSS selectors for current STF website"""
    try:
        # Find the partes section
        partes_section = driver.find_element(By.ID, "resumo-partes")

        # Look for all divs with processo-partes class; they appear as tipo then nome
        elementos = partes_section.find_elements(
            By.CSS_SELECTOR, "div[class*='processo-partes']"
        )

        partes_list: list[dict] = []
        i = 0
        while i + 1 < len(elementos):
            tipo_text = normalize_spaces(elementos[i].text)
            nome_text = normalize_spaces(elementos[i + 1].text)

            # Advance by 2 for next pair
            i += 2

            if not tipo_text or not nome_text:
                continue

            parte_data = {
                "index": len(partes_list) + 1,
                "tipo": tipo_text,
                "nome": nome_text,
            }
            partes_list.append(parte_data)

        return partes_list
    except Exception as e:
        logging.warning(f"Could not extract partes: {e}")
        return []
