"""
Extract assuntos from process data
"""

from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver

from src.utils.get_element import find_element_by_xpath

from .base import normalize_spaces, track_extraction_timing


@track_extraction_timing
def extract_assuntos(driver: WebDriver, soup: BeautifulSoup) -> list:
    assuntos_html = find_element_by_xpath(
        driver, '//*[@id="informacoes-completas"]/div[1]/div[2]'
    )
    soup_assuntos = BeautifulSoup(assuntos_html, "html.parser")
    assuntos_list = []
    for li in soup_assuntos.find_all("li"):
        assunto_text = li.get_text(strip=True)
        if assunto_text:
            assuntos_list.append(normalize_spaces(assunto_text))
    return assuntos_list
