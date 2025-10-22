"""
Extract peticoes from process data
"""

import re

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from src.utils.text_utils import normalize_spaces

from .base import track_extraction_timing


@track_extraction_timing
def extract_peticoes(driver: WebDriver, soup: BeautifulSoup) -> list:
    """Extract peticoes from AJAX-loaded content"""
    peticoes_info = driver.find_element(By.XPATH, '//*[@id="peticoes"]')
    peticoes = peticoes_info.find_elements(By.CLASS_NAME, "lista-dados")

    peticoes_list = []
    for i, peticao in enumerate(peticoes):
        index = len(peticoes) - i
        html = peticao.get_attribute("innerHTML") or ""

        # Extract data from HTML using text parsing
        # Look for different patterns to extract all fields
        data_match = re.search(r'processo-detalhes bg-font-info">([^<]+)', html)
        id_match = re.search(r'processo-detalhes-bold">([^<]+)', html)
        data_match = re.search(r'processo-detalhes">([^<]+)', html)

        # Also look for "Recebido em" pattern
        recebido_match = re.search(r"Recebido em ([^<]+)", html)

        data = data_match.group(1) if data_match else None
        id = id_match.group(1) if id_match else None
        data = data_match.group(1) if data_match else None
        recebido = recebido_match.group(1) if recebido_match else None

        # Clean the extracted data
        if data is not None:
            data = normalize_spaces(data)
            # Remove "Peticionado em" prefix
            data = re.sub(r"^Peticionado em\s+", "", data)
        if id is not None:
            id = normalize_spaces(id)
        if data is not None:
            data = normalize_spaces(data)
        if recebido is not None:
            recebido = normalize_spaces(recebido)

        # Parse recebido into recebido_data and recebido_por
        recebido_data = None
        recebido_por = None
        if recebido is not None:
            # Extract date and organization from "04/05/1994 00:00:00 por DIVISAO DE PROCESSOS ORIGINARIOS"
            recebido_parts = recebido.split(" por ")
            if len(recebido_parts) == 2:
                recebido_data = recebido_parts[0].strip()  # "04/05/1994 00:00:00"
                recebido_por = recebido_parts[
                    1
                ].strip()  # "DIVISAO DE PROCESSOS ORIGINARIOS"
            else:
                recebido_data = recebido  # Fallback to full string

        peticao_data = {
            "index": index,
            "id": id,
            "data": data,
            "recebido_data": recebido_data,
            "recebido_por": recebido_por,
        }
        peticoes_list.append(peticao_data)
    return peticoes_list
