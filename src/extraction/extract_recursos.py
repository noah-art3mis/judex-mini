"""
Extract recursos from process data
"""

import logging
import re

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from src.utils.text_utils import normalize_spaces

from .base import track_extraction_timing


@track_extraction_timing
def extract_recursos(driver: WebDriver, soup: BeautifulSoup) -> list:
    """Extract recursos from AJAX-loaded content"""
    try:
        recursos_info = driver.find_element(By.XPATH, '//*[@id="recursos"]')
        recursos = recursos_info.find_elements(By.CLASS_NAME, "lista-dados")

        recursos_list = []
        for i, recurso in enumerate(recursos):
            index = len(recursos) - i
            html = recurso.get_attribute("innerHTML")

            # Extract data from HTML using text parsing
            # Look for different patterns to extract all fields
            data_match = re.search(r'processo-detalhes-bold">([^<]+)', html)

            data = data_match.group(1) if data_match else None

            # Clean the extracted data
            if data is not None:
                data = normalize_spaces(data)

            recurso_data = {
                "index": index,
                "data": data,
            }
            recursos_list.append(recurso_data)
        return recursos_list
    except Exception as e:
        logging.warning(f"Could not extract recursos: {e}")
        return []
