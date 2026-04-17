"""
Extract orgao_origem from process data
"""

from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver

from deprecated.utils.get_element import find_element_by_xpath
from src.utils.text_utils import normalize_spaces
from src.utils.timing import track_extraction_timing


@track_extraction_timing
def extract_orgao_origem(driver: WebDriver, soup: BeautifulSoup) -> str | None:
    """Extract orgao_origem using XPath"""
    element = find_element_by_xpath(
        driver, '//*[@id="informacoes-completas"]/div[2]/div[1]/div[2]/div[4]'
    )
    return normalize_spaces(element) if element else None
