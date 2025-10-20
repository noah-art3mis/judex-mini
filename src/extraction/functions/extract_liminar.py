"""
Extract liminar from process data
"""

from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver

from .base import handle_extraction_errors, track_extraction_timing


@track_extraction_timing
@handle_extraction_errors(default_value=[], log_errors=True)
def extract_liminar(driver: WebDriver, titulo_processo: str) -> list:
    """Extract liminar information from process title"""
    liminar_list = []

    # Check if title contains liminar indicators
    if titulo_processo and any(
        keyword in titulo_processo.upper() for keyword in ["LIMINAR", "TUTELA"]
    ):
        liminar_list.append({"tipo": "liminar", "descricao": titulo_processo})

    return liminar_list
