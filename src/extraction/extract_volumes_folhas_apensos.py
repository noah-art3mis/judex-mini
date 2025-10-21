"""
Extract volumes, folhas, apensos from process data
"""

from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver

from src.utils.get_element import find_element_by_xpath

from .base import track_extraction_timing


@track_extraction_timing
def extract_volumes_folhas_apensos(
    driver: WebDriver, soup: BeautifulSoup
) -> dict | None:
    """Extract volumes, folhas, apensos counters from info boxes."""
    info_html = find_element_by_xpath(driver, '//*[@id="informacoes"]')
    s = BeautifulSoup(info_html, "html.parser")
    boxes = s.select(".processo-quadro")
    result: dict[str, int | str] = {}
    for box in boxes:
        num_el = box.select_one(".numero")
        rot_el = box.select_one(".rotulo")
        if not num_el or not rot_el:
            continue
        label = rot_el.get_text(strip=True).upper()
        value = num_el.get_text(strip=True)
        if value.isdigit():
            value = int(value)
        elif not value or value.strip() == "":
            value = None
        if "VOLUME" in label:
            result["volumes"] = value
        elif "FOLHA" in label:
            result["folhas"] = value
        elif "APENSO" in label:
            result["apensos"] = value
    return result if result else None
