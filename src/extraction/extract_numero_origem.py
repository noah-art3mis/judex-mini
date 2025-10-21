"""
Extract numero_origem from process data
"""

import re

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from .base import track_extraction_timing


@track_extraction_timing
def extract_numero_origem(driver: WebDriver, soup: BeautifulSoup) -> list | None:
    """Extract numero_origem as a list to match ground-truth schema."""
    try:
        info_html = driver.find_element(
            By.XPATH, '//*[@id="informacoes-completas"]/div[2]/div[1]/div[2]'
        )
        text = info_html.text

        m = re.search(r"Número de Origem:\s*([0-9\./-]+)", text, re.IGNORECASE)
        if not m:
            return None
        raw = m.group(1).strip()
        if raw.isdigit():
            return [int(raw)]
        return [raw]
    except Exception:
        return None
