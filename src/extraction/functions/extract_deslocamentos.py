"""
Extract deslocamentos from process data
"""

from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver

from .base import handle_extraction_errors, normalize_spaces, track_extraction_timing


@track_extraction_timing
@handle_extraction_errors(default_value=[], log_errors=True)
def extract_deslocamentos(driver: WebDriver, soup: BeautifulSoup) -> list:
    """Extract deslocamentos from the process page"""
    deslocamentos_list = []

    try:
        # Look for deslocamentos section
        deslocamentos_section = driver.find_element(By.ID, "resumo-deslocamentos")

        # Extract each deslocamento
        for item in deslocamentos_section.find_elements(
            By.CSS_SELECTOR, ".deslocamento-item"
        ):
            try:
                guia = normalize_spaces(
                    item.find_element(By.CSS_SELECTOR, ".guia").text
                )
                recebido_por = normalize_spaces(
                    item.find_element(By.CSS_SELECTOR, ".recebido-por").text
                )
                data_recebido = normalize_spaces(
                    item.find_element(By.CSS_SELECTOR, ".data-recebido").text
                )
                enviado_por = normalize_spaces(
                    item.find_element(By.CSS_SELECTOR, ".enviado-por").text
                )
                data_enviado = normalize_spaces(
                    item.find_element(By.CSS_SELECTOR, ".data-enviado").text
                )

                deslocamento = {
                    "index_num": len(deslocamentos_list) + 1,
                    "guia": guia,
                    "recebido_por": recebido_por,
                    "data_recebido": data_recebido,
                    "enviado_por": enviado_por,
                    "data_enviado": data_enviado,
                }
                deslocamentos_list.append(deslocamento)
            except Exception:
                continue

    except Exception:
        pass

    return deslocamentos_list
