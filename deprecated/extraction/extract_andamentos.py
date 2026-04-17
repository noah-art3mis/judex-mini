"""
Extract andamentos from process data
"""

import logging
import re

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from src.config import ScraperConfig
from src.utils.text_utils import normalize_spaces
from src.utils.timing import track_extraction_timing


# def _clean_nome(nome: str) -> str:
#     """Clean and normalize nome field, removing GUIA artifacts."""
#     nome = normalize_spaces(nome)
#     if nome:
#         nome = re.sub(
#             r",\s*GUIA\s*N[ºOo0]?[^,]*$", "", nome, flags=re.IGNORECASE
#         ).strip()
#     return nome


# def _extract_link_info(
#     andamento, config: ScraperConfig
# ) -> tuple[str | None, str | None]:
#     """Extract link and link description from andamento element."""
#     try:
#         anchors = andamento.find_elements(By.TAG_NAME, "a")
#         if not anchors:
#             return None, None

#         anchor = anchors[0]
#         href = anchor.get_attribute("href")
#         text = anchor.text

#         # Process link
#         link = None
#         if href:
#             if href.startswith("http"):
#                 link = href
#             else:
#                 base_url = config.base_url if config else "https://portal.stf.jus.br"
#                 link = f"{base_url}/processos/{href.replace('amp;', '')}"

#         # Process link description
#         link_descricao = None
#         if text:
#             link_descricao = normalize_spaces(text)
#             if link_descricao:
#                 link_descricao = link_descricao.upper()

#         return link, link_descricao
#     except Exception:
#         return None, None


# def _extract_single_andamento(
#     andamento, index: int, config: ScraperConfig
# ) -> dict | None:
#     """Extract data from a single andamento element."""
#     data = andamento.find_element(By.CLASS_NAME, "andamento-data").text
#     nome_raw = andamento.find_element(By.CLASS_NAME, "andamento-nome").text
#     nome = _clean_nome(nome_raw)

#     # Extract complemento
#     complemento_raw = andamento.find_element(By.CLASS_NAME, "col-md-9").text
#     complemento = normalize_spaces(complemento_raw) or None

#     # Extract julgador (optional)
#     try:
#         julgador = andamento.find_element(By.CLASS_NAME, "andamento-julgador").text
#     except Exception:
#         julgador = None

#     # Extract link info
#     link, link_descricao = _extract_link_info(andamento, config)

#     return {
#         "index_num": index,
#         "data": data,
#         "nome": nome.upper(),
#         "complemento": complemento,
#         "julgador": julgador,
#         "link_descricao": link_descricao,
#         "link": link,
#     }


# @track_extraction_timing
# def extract_andamentos(driver: WebDriver, soup: BeautifulSoup, config) -> list:
#     """Extract andamentos from the process page."""
#     try:
#         # Find the andamentos container
#         andamentos_info = driver.find_element(By.CLASS_NAME, "processo-andamentos")
#         andamentos = andamentos_info.find_elements(By.CLASS_NAME, "andamento-item")

#         andamentos_list = []
#         total_andamentos = len(andamentos)

#         # Process each andamento (in reverse order for correct indexing)
#         for i, andamento in enumerate(andamentos):
#             index = total_andamentos - i
#             andamento_data = _extract_single_andamento(andamento, index, config)

#             if andamento_data:
#                 andamentos_list.append(andamento_data)

#         return andamentos_list

#     except Exception as e:
#         logging.warning(f"Could not extract andamentos: {e}")
#         return []


from bs4 import Tag


def _clean_nome(nome: str) -> str:
    """Clean and normalize nome field, removing GUIA artifacts."""
    nome = normalize_spaces(nome)
    if nome:
        nome = re.sub(
            r",\s*GUIA\s*N[ºOo0]?[^,]*$", "", nome, flags=re.IGNORECASE
        ).strip()
    return nome

# --- This helper is rewritten for BeautifulSoup ---
def _extract_link_info_bs4(
    andamento_tag: Tag, config: ScraperConfig
) -> tuple[str | None, str | None]:
    """Extract link and link description from a BeautifulSoup 'andamento' tag."""
    try:
        # Use bs4's find() - it's much faster
        anchor = andamento_tag.find("a")
        if not anchor:
            return None, None

        href = anchor.get("href")
        text = anchor.get_text()

        # Process link (this logic is unchanged)
        link = None
        if href:
            if href.startswith("http"):
                link = href
            else:
                base_url = config.base_url if config else "https://portal.stf.jus.br"
                link = f"{base_url}/processos/{href.replace('amp;', '')}"

        # Process link description (this logic is unchanged)
        link_descricao = None
        if text:
            link_descricao = normalize_spaces(text)
            if link_descricao:
                link_descricao = link_descricao.upper()

        return link, link_descricao
    except Exception:
        return None, None

# --- This helper is rewritten for BeautifulSoup ---
def _extract_single_andamento_bs4(
    andamento_tag: Tag, index: int, config: ScraperConfig
) -> dict | None:
    """Extract data from a single BeautifulSoup 'andamento' tag."""

    # Use bs4's .find() and .get_text().
    # Add checks for None in case an element is missing.
    data_tag = andamento_tag.find(class_="andamento-data")
    data = data_tag.get_text(strip=True) if data_tag else None

    nome_tag = andamento_tag.find(class_="andamento-nome")
    nome_raw = nome_tag.get_text(strip=True) if nome_tag else ""
    nome = _clean_nome(nome_raw)

    complemento_tag = andamento_tag.find(class_="col-md-9")
    # Use .get_text() without strip=True to preserve internal newlines
    complemento_raw = complemento_tag.get_text() if complemento_tag else ""
    complemento = normalize_spaces(complemento_raw) or None

    julgador_tag = andamento_tag.find(class_="andamento-julgador")
    julgador = julgador_tag.get_text(strip=True) if julgador_tag else None

    # Extract link info
    link, link_descricao = _extract_link_info_bs4(andamento_tag, config)

    return {
        "index_num": index,
        "data": data,
        "nome": nome.upper(),
        "complemento": complemento,
        "julgador": julgador,
        "link_descricao": link_descricao,
        "link": link,
    }

# --- This is the main, optimized function ---
@track_extraction_timing
def extract_andamentos(driver: WebDriver, soup: BeautifulSoup, config) -> list:
    """
    Extract andamentos from the process page using a fast Selenium + BeautifulSoup hybrid.
    """
    try:
        # 1. Find the andamentos container ONCE with Selenium
        andamentos_info = driver.find_element(By.CLASS_NAME, "processo-andamentos")

        # 2. Get the inner HTML of the container ONCE
        container_html = andamentos_info.get_attribute("innerHTML")

        # 3. Pass the HTML to BeautifulSoup for all parsing
        # Using 'lxml' is highly recommended for speed
        bs_soup = BeautifulSoup(container_html, "lxml")

        # 4. Find all items using BeautifulSoup (very fast)
        andamentos = bs_soup.find_all(class_="andamento-item")

        andamentos_list = []
        total_andamentos = len(andamentos)

        # 5. Process each andamento (in reverse order) using the fast bs4 functions
        for i, andamento_tag in enumerate(andamentos):
            index = total_andamentos - i

            # Pass the BeautifulSoup tag, not a Selenium element
            andamento_data = _extract_single_andamento_bs4(andamento_tag, index, config)

            if andamento_data:
                andamentos_list.append(andamento_data)

        return andamentos_list

    except Exception as e:
        # Handle case where 'processo-andamentos' isn't found
        if "no such element" in str(e).lower():
            logging.info("No 'processo-andamentos' container found. Returning empty list.")
        else:
            logging.warning(f"Could not extract andamentos: {e}")
        return []
