"""
Extract andamentos from process data
"""

from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver

from .base import handle_extraction_errors, normalize_spaces, track_extraction_timing


@track_extraction_timing
@handle_extraction_errors(default_value=[], log_errors=True)
def extract_andamentos(driver: WebDriver, soup: BeautifulSoup) -> list:
    """Extract andamentos from the process page"""
    andamentos_list = []

    try:
        # Look for andamentos section
        andamentos_section = driver.find_element(By.ID, "resumo-andamentos")

        # Extract each andamento
        for item in andamentos_section.find_elements(
            By.CSS_SELECTOR, ".andamento-item"
        ):
            try:
                data = normalize_spaces(
                    item.find_element(By.CSS_SELECTOR, ".data").text
                )
                nome = normalize_spaces(
                    item.find_element(By.CSS_SELECTOR, ".nome").text
                )
                complemento = normalize_spaces(
                    item.find_element(By.CSS_SELECTOR, ".complemento").text
                )

                andamento = {
                    "index_num": len(andamentos_list) + 1,
                    "data": data,
                    "nome": nome,
                    "complemento": complemento,
                    "julgador": None,
                    "link_descricao": None,
                    "link": None,
                }
                andamentos_list.append(andamento)
            except Exception:
                continue

    except Exception:
        pass

    return andamentos_list
