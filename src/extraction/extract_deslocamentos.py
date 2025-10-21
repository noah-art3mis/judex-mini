"""
Extract deslocamentos from process data
"""

import logging
import re

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from .base import normalize_spaces, track_extraction_timing


def _extract_data_from_soup(soup: BeautifulSoup) -> dict:
    """Extract data from BeautifulSoup object using CSS selectors."""
    data = {}

    # Extract guia (usually in a span with specific classes)
    guia_elem = soup.select_one(".text-right span.processo-detalhes")
    data["guia"] = guia_elem.get_text(strip=True) if guia_elem else None

    # Extract data_recebido (green background)
    data_recebido_elem = soup.select_one(".processo-detalhes.bg-font-success")
    data["data_recebido"] = (
        data_recebido_elem.get_text(strip=True) if data_recebido_elem else None
    )

    # Extract data_enviado (blue background)
    data_enviado_elem = soup.select_one(".processo-detalhes.bg-font-info")
    data["data_enviado"] = (
        data_enviado_elem.get_text(strip=True) if data_enviado_elem else None
    )

    # Extract recebido_por (regular processo-detalhes)
    recebido_elem = soup.select_one(
        ".processo-detalhes:not(.bg-font-success):not(.bg-font-info)"
    )
    data["recebido_por"] = recebido_elem.get_text(strip=True) if recebido_elem else None

    # Extract enviado_por (bold processo-detalhes)
    enviado_elem = soup.select_one(".processo-detalhes-bold")
    data["enviado_por"] = enviado_elem.get_text(strip=True) if enviado_elem else None

    return data


def _clean_extracted_data(data: dict) -> dict:
    """Clean and normalize extracted data."""
    cleaned = {}

    # Clean guia
    if data.get("guia"):
        guia = normalize_spaces(data["guia"])
        cleaned["guia"] = (
            guia.replace("Guia: ", "").replace("Guia ", "").replace("Nº ", "").strip()
        )
    else:
        cleaned["guia"] = None

    # Clean data_recebido
    if data.get("data_recebido"):
        data_recebido = normalize_spaces(data["data_recebido"])
        cleaned["data_recebido"] = (
            data_recebido.replace("Recebido em ", "").replace(" em ", "").strip()
        )
    else:
        cleaned["data_recebido"] = None

    # Clean data_enviado
    if data.get("data_enviado"):
        data_enviado = normalize_spaces(data["data_enviado"])
        cleaned["data_enviado"] = (
            data_enviado.replace("Enviado em ", "").replace(" em ", "").strip()
        )
    else:
        cleaned["data_enviado"] = None

    # Clean person data and extract dates
    cleaned["recebido_por"] = _clean_person_data(data.get("recebido_por"), "recebido")
    cleaned["enviado_por"] = _clean_person_data(data.get("enviado_por"), "enviado")

    return cleaned


def _clean_person_data(text: str | None, person_type: str) -> str | None:
    """Clean person data and extract dates if needed."""
    if not text:
        return None

    cleaned = normalize_spaces(text)

    # Remove boilerplate text
    if person_type == "recebido":
        cleaned = re.sub(r"^Recebido por ", "", cleaned)
    else:  # enviado
        cleaned = re.sub(r"^Enviado por ", "", cleaned)

    # Remove date suffix
    cleaned = re.sub(r" em \d{2}/\d{2}/\d{4}$", "", cleaned)

    return cleaned.strip() or None


def _extract_single_deslocamento(deslocamento, index: int) -> dict | None:
    """Extract data from a single deslocamento element."""
    try:
        # Get HTML and parse with BeautifulSoup
        html = deslocamento.get_attribute("innerHTML")
        soup = BeautifulSoup(html, "html.parser")

        # Extract data using BeautifulSoup
        raw_data = _extract_data_from_soup(soup)

        # Clean the extracted data
        cleaned_data = _clean_extracted_data(raw_data)

        return {
            "index_num": index,
            "guia": cleaned_data["guia"],
            "recebido_por": cleaned_data["recebido_por"],
            "data_recebido": cleaned_data["data_recebido"],
            "enviado_por": cleaned_data["enviado_por"],
            "data_enviado": cleaned_data["data_enviado"],
        }
    except Exception as e:
        logging.warning(f"Could not extract deslocamento: {e}")
        return None


@track_extraction_timing
def extract_deslocamentos(driver: WebDriver, soup: BeautifulSoup) -> list:
    """Extract deslocamentos from the process page."""
    try:
        # Find the deslocamentos container
        deslocamentos_info = driver.find_element(By.XPATH, '//*[@id="deslocamentos"]')
        deslocamentos = deslocamentos_info.find_elements(By.CLASS_NAME, "lista-dados")

        deslocamentos_list = []
        total_deslocamentos = len(deslocamentos)

        # Process each deslocamento (in reverse order for correct indexing)
        for i, deslocamento in enumerate(deslocamentos):
            index = total_deslocamentos - i
            deslocamento_data = _extract_single_deslocamento(deslocamento, index)

            if deslocamento_data:
                deslocamentos_list.append(deslocamento_data)

        return deslocamentos_list

    except Exception as e:
        logging.warning(f"Could not extract deslocamentos: {e}")
        return []
