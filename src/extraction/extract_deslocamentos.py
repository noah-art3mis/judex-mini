"""
Extract deslocamentos from process data
"""

import logging
import re

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from src.utils.text_utils import normalize_spaces

from .base import track_extraction_timing


def _extract_data_from_html(html: str) -> dict:
    """Extract data from HTML using regex patterns (like the original working code)."""
    import re

    # Define regex patterns for different data fields (from original working code)
    patterns = {
        "enviado_match": r'"processo-detalhes-bold">([^<]+)',
        "data_recebido_match": r'processo-detalhes bg-font-success">([^<]+)',
        "recebido_match": r'"processo-detalhes">([^<]+)',
        "data_enviado_match": r'processo-detalhes bg-font-info">([^<]+)',
        "guia_match": r'text-right">\s*<span class="processo-detalhes">([^<]+)',
    }

    # Extract matches
    matches = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, html)
        matches[key] = match.group(1) if match else None

    return matches


def _clean_data_fields(matches: dict) -> dict:
    """Clean and normalize extracted data fields."""
    # Extract raw data
    data_recebido = matches["data_recebido_match"]
    data_enviado = matches["data_enviado_match"]
    guia = matches["guia_match"]
    enviado_raw = matches["recebido_match"]
    recebido_raw = matches["enviado_match"]

    # Clean data_recebido
    if data_recebido is not None:
        data_recebido = normalize_spaces(data_recebido)
        data_recebido = (
            data_recebido.replace("Recebido em ", "").replace(" em ", "").strip()
        )

    # Clean data_enviado
    if data_enviado is not None:
        data_enviado = normalize_spaces(data_enviado)
        data_enviado = (
            data_enviado.replace("Enviado em ", "").replace(" em ", "").strip()
        )

    # Clean guia
    if guia is not None:
        guia = normalize_spaces(guia)
        guia = (
            guia.replace("Guia: ", "").replace("Guia ", "").replace("Nº ", "").strip()
        )

    return {
        "data_recebido": data_recebido,
        "data_enviado": data_enviado,
        "guia": guia,
        "enviado_raw": enviado_raw,
        "recebido_raw": recebido_raw,
    }


def _extract_person_data(
    enviado_raw: str, recebido_raw: str, data_enviado: str, data_recebido: str
) -> dict:
    """Extract and clean person data from raw text."""
    # Process enviado_por
    enviado_por_clean = enviado_raw
    if enviado_raw is not None:
        enviado_por_clean = normalize_spaces(enviado_raw)
        # Extract date from "Enviado por X em DD/MM/YYYY" format
        date_match = re.search(r"em (\d{2}/\d{2}/\d{4})", enviado_por_clean)
        if date_match and data_enviado is None:
            data_enviado = date_match.group(1)
        # Remove boilerplate text
        enviado_por_clean = re.sub(r"^Enviado por ", "", enviado_por_clean)
        enviado_por_clean = re.sub(r" em \d{2}/\d{2}/\d{4}$", "", enviado_por_clean)

    # Process recebido_por
    recebido_por_clean = recebido_raw
    if recebido_raw is not None:
        recebido_por_clean = normalize_spaces(recebido_raw)
        # Extract date from "Recebido por X em DD/MM/YYYY" format
        date_match = re.search(r"em (\d{2}/\d{2}/\d{4})", recebido_por_clean)
        if date_match and data_recebido is None:
            data_recebido = date_match.group(1)
        # Remove boilerplate text
        recebido_por_clean = re.sub(r"^Recebido por ", "", recebido_por_clean)
        recebido_por_clean = re.sub(r" em \d{2}/\d{2}/\d{4}$", "", recebido_por_clean)

    return {
        "enviado_por": enviado_por_clean,
        "recebido_por": recebido_por_clean,
        "data_enviado": data_enviado,
        "data_recebido": data_recebido,
    }


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
        cleaned["guia"] = ""

    # Clean data_recebido
    if data.get("data_recebido"):
        data_recebido = normalize_spaces(data["data_recebido"])
        cleaned["data_recebido"] = (
            data_recebido.replace("Recebido em ", "").replace(" em ", "").strip()
        )
    else:
        cleaned["data_recebido"] = ""

    # Clean data_enviado
    if data.get("data_enviado"):
        data_enviado = normalize_spaces(data["data_enviado"])
        cleaned["data_enviado"] = (
            data_enviado.replace("Enviado em ", "").replace(" em ", "").strip()
        )
    else:
        cleaned["data_enviado"] = ""

    # Clean person data and extract dates
    cleaned["recebido_por"] = (
        _clean_person_data(data.get("recebido_por"), "recebido") or ""
    )
    cleaned["enviado_por"] = (
        _clean_person_data(data.get("enviado_por"), "enviado") or ""
    )

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
        # Get HTML and use regex patterns (like original working code)
        html = deslocamento.get_attribute("innerHTML")

        # Extract data using regex patterns
        matches = _extract_data_from_html(html)

        # Clean basic data fields
        cleaned_data = _clean_data_fields(matches)

        # Extract person data with date extraction
        person_data = _extract_person_data(
            cleaned_data["enviado_raw"],
            cleaned_data["recebido_raw"],
            cleaned_data["data_enviado"],
            cleaned_data["data_recebido"],
        )

        return {
            "index_num": index,
            "guia": cleaned_data["guia"],
            "recebido_por": person_data["recebido_por"],
            "data_recebido": person_data["data_recebido"],
            "enviado_por": person_data["enviado_por"],
            "data_enviado": person_data["data_enviado"],
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
