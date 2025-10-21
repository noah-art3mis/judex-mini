"""
Extract andamentos from process data
"""

import logging
import re

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from src.utils.get_element import find_elements_by_class

from .base import normalize_spaces, track_extraction_timing


@track_extraction_timing
def extract_andamentos(driver: WebDriver, soup: BeautifulSoup) -> list:
    try:
        andamentos_info = driver.find_element(By.CLASS_NAME, "processo-andamentos")
        andamentos = andamentos_info.find_elements(By.CLASS_NAME, "andamento-item")

        andamentos_list = []
        for i, andamento in enumerate(andamentos):
            try:
                index = len(andamentos) - i

                # Extract data, nome, complemento, julgador
                data = andamento.find_element(By.CLASS_NAME, "andamento-data").text
                nome_raw = andamento.find_element(By.CLASS_NAME, "andamento-nome").text
                # Normalize nome and remove trailing ", GUIA N..." artifacts when present
                nome = normalize_spaces(nome_raw)
                try:
                    if nome:
                        nome = re.sub(
                            r",\s*GUIA\s*N[ºOo0]?[^,]*$", "", nome, flags=re.IGNORECASE
                        ).strip()
                except Exception:
                    pass
                complemento_raw = andamento.find_element(By.CLASS_NAME, "col-md-9").text
                complemento = normalize_spaces(complemento_raw)
                if not complemento:
                    complemento = None

                # Check for julgador
                try:
                    julgador = andamento.find_element(
                        By.CLASS_NAME, "andamento-julgador"
                    ).text
                except Exception:
                    julgador = None

                # Extract optional link and description from the andamento DOM
                link = None
                link_descricao = None
                try:
                    anchors = andamento.find_elements(By.TAG_NAME, "a")
                    if anchors:
                        a = anchors[0]
                        href = a.get_attribute("href")
                        if href:
                            if href.startswith("http"):
                                link = href
                            else:
                                link = (
                                    "https://portal.stf.jus.br/processos/"
                                    + href.replace("amp;", "")
                                )
                        text = a.text
                        if text:
                            link_descricao = normalize_spaces(text)
                            if link_descricao:
                                link_descricao = link_descricao.upper()
                except Exception:
                    pass

                andamento_data = {
                    "index_num": index,
                    "data": data,
                    "nome": nome.upper(),
                    "complemento": complemento,
                    "julgador": julgador,
                    "link_descricao": link_descricao,
                    "link": link,
                }
                andamentos_list.append(andamento_data)
            except Exception as e:
                logging.warning(f"Could not extract andamento {i}: {e}")
                continue

        return andamentos_list
    except Exception as e:
        logging.warning(f"Could not extract andamentos: {e}")
        return []
