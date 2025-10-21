"""
Extract orgao_origem from process data
"""

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from src.utils.get_element import find_element_by_xpath

from .base import normalize_spaces, track_extraction_timing


@track_extraction_timing
def extract_orgao_origem(driver: WebDriver, soup: BeautifulSoup) -> str | None:
    """Extract orgao_origem using XPath"""
    element = find_element_by_xpath(
        driver, '//*[@id="informacoes-completas"]/div[2]/div[1]/div[2]/div[4]'
    )
    return normalize_spaces(element) if element else None
