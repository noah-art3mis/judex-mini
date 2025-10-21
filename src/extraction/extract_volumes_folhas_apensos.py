"""
Extract volumes, folhas, apensos from process data
"""

from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver

from src.utils.get_element import find_element_by_xpath

from .base import track_extraction_timing


def _get_info_boxes(driver: WebDriver) -> list:
    """Helper function to get info boxes from the page."""
    info_html = find_element_by_xpath(driver, '//*[@id="informacoes"]')
    s = BeautifulSoup(info_html, "html.parser")
    return s.select(".processo-quadro")


def _extract_value_from_box(box) -> int | str | None:
    """Helper function to extract and parse value from a box."""
    num_el = box.select_one(".numero")
    if not num_el:
        return None

    value = num_el.get_text(strip=True)
    if value.isdigit():
        return int(value)
    elif not value or value.strip() == "":
        return None
    return value


@track_extraction_timing
def extract_volumes(driver: WebDriver, soup: BeautifulSoup) -> int | str | None:
    """Extract volumes counter from info boxes."""
    boxes = _get_info_boxes(driver)
    for box in boxes:
        rot_el = box.select_one(".rotulo")
        if not rot_el:
            continue
        label = rot_el.get_text(strip=True).upper()
        if "VOLUME" in label:
            return _extract_value_from_box(box)
    return None


@track_extraction_timing
def extract_folhas(driver: WebDriver, soup: BeautifulSoup) -> int | str | None:
    """Extract folhas counter from info boxes."""
    boxes = _get_info_boxes(driver)
    for box in boxes:
        rot_el = box.select_one(".rotulo")
        if not rot_el:
            continue
        label = rot_el.get_text(strip=True).upper()
        if "FOLHA" in label:
            return _extract_value_from_box(box)
    return None


@track_extraction_timing
def extract_apensos(driver: WebDriver, soup: BeautifulSoup) -> int | str | None:
    """Extract apensos counter from info boxes."""
    boxes = _get_info_boxes(driver)
    for box in boxes:
        rot_el = box.select_one(".rotulo")
        if not rot_el:
            continue
        label = rot_el.get_text(strip=True).upper()
        if "APENSO" in label:
            return _extract_value_from_box(box)
    return None
