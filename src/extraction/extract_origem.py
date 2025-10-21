"""
Extract origem from process data
"""

import logging

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from src.utils.text_utils import normalize_spaces

from .base import track_extraction_timing


@track_extraction_timing
def extract_origem(driver: WebDriver, soup: BeautifulSoup) -> str | None:
    """Extract origem from descricao-procedencia span"""
    try:
        element = driver.find_element(By.ID, "descricao-procedencia")
        return normalize_spaces(element.text)
    except Exception as e:
        logging.warning(f"Could not extract origem: {e}")
        return None
