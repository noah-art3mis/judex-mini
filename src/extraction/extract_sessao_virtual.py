"""
Extract sessao_virtual from process data
"""

import logging
from typing import Any

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from src.utils.pdf_utils import extract_pdf_texts_from_session
from src.utils.text_utils import normalize_spaces

from .base import track_extraction_timing


@track_extraction_timing
def extract_sessao_virtual(driver: WebDriver, soup: BeautifulSoup) -> list:
    """Extract sessao_virtual from AJAX-loaded content"""
    try:
        # First, click the "Sessão virtual" tab to make content visible
        try:
            sessao_tab = driver.find_element(
                By.CSS_SELECTOR, "a[href='#sessao-virtual']"
            )
            driver.execute_script("arguments[0].click();", sessao_tab)
            logging.info("Clicked Sessão virtual tab")
        except Exception as e:
            logging.warning(f"Could not click Sessão virtual tab: {e}")
            return []

        # Wait for the tab content to load
        wait = WebDriverWait(driver, 10)
        try:
            wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#sessao-virtual"))
            )
            logging.info("Sessão virtual tab content loaded")
        except Exception as e:
            logging.warning(f"Sessão virtual tab content did not load: {e}")
            return []

        # Now find the julgamento items in the sessao-virtual container
        julgamento_items = driver.find_elements(
            By.CSS_SELECTOR, "#sessao-virtual .julgamento-item"
        )

        logging.info(f"Found {len(julgamento_items)} julgamento items")

        sessao_list = []
        for julgamento_item in julgamento_items:
            try:
                button = julgamento_item.find_element(By.TAG_NAME, "button")

                # Now the button should be clickable
                try:
                    driver.execute_script("arguments[0].click();", button)
                except Exception as e:
                    logging.warning(f"Could not click button: {e}")
                    continue

                # Wait for content and extract
                wait = WebDriverWait(driver, 10)
                try:
                    # Find the collapse div within this specific julgamento item
                    collapse_div = julgamento_item.find_element(
                        By.CSS_SELECTOR, "[id^='listasJulgamento']"
                    )
                    logging.debug(
                        f"Found collapse div: {collapse_div.get_attribute('id')}"
                    )

                    # Wait for the collapse animation to complete (no more "collapsing" class)
                    wait.until(
                        lambda driver: "collapsing"
                        not in (collapse_div.get_attribute("class") or "")
                    )
                    logging.debug("Collapse animation completed")

                    # Debug: Check what's actually in the collapse div
                    html_content = collapse_div.get_attribute("outerHTML") or ""
                    logging.debug(f"Collapse div HTML: {html_content[:500]}...")

                    # Check if there's a nested collapse that needs to be clicked
                    try:
                        # Use the specific selector you identified
                        nested_collapse_link = collapse_div.find_element(
                            By.CSS_SELECTOR, "div:nth-child(1) > a:nth-child(1)"
                        )
                        logging.debug("Found nested collapse link, clicking it...")
                        driver.execute_script(
                            "arguments[0].click();", nested_collapse_link
                        )

                        # Wait for the nested collapse to expand
                        wait.until(
                            lambda driver: "collapse"
                            not in (
                                nested_collapse_link.get_attribute("aria-expanded")
                                or ""
                            )
                            or nested_collapse_link.get_attribute("aria-expanded")
                            == "true"
                        )
                        logging.debug("Nested collapse expanded")
                    except Exception as e:
                        logging.debug(
                            f"No nested collapse found or already expanded: {e}"
                        )

                    # Try to find titulo-lista with different selectors
                    titulo = None
                    try:
                        titulo = collapse_div.find_element(
                            By.CSS_SELECTOR, ".titulo-lista"
                        ).text
                        logging.debug(
                            f"Found titulo with .titulo-lista: {titulo[:100]}..."
                        )
                    except Exception:
                        try:
                            # Try without the m-16 class
                            titulo = collapse_div.find_element(
                                By.CSS_SELECTOR, ".titulo-lista"
                            ).text
                            logging.debug(
                                f"Found titulo without m-16: {titulo[:100]}..."
                            )
                        except Exception:
                            # Try finding any div with the vote text
                            vote_divs = collapse_div.find_elements(
                                By.CSS_SELECTOR, "div"
                            )
                            for div in vote_divs:
                                text = div.text.strip()
                                if len(text) > 50 and (
                                    "julgo" in text.lower()
                                    or "procedente" in text.lower()
                                    or "improcedente" in text.lower()
                                ):
                                    titulo = text
                                    logging.debug(
                                        f"Found titulo by text search: {titulo[:100]}..."
                                    )
                                    break

                    if titulo:
                        # Extract the full session data using the _extract_sessao_details function
                        sessao_data = _extract_sessao_details(collapse_div)
                        if sessao_data:
                            # Extract PDF content from URLs
                            sessao_data = extract_pdf_texts_from_session(sessao_data)
                            sessao_list.append(sessao_data)
                        else:
                            # Fallback: just add the titulo text
                            sessao_list.append({"voto_texto": titulo})
                    else:
                        logging.warning("Could not find titulo text in any form")

                except Exception as e:
                    logging.warning(f"Could not extract content: {e}")
                    continue

            except Exception as e:
                logging.warning(f"Could not process julgamento item: {e}")
                continue

        return sessao_list

    except Exception as e:
        logging.warning(f"Could not extract sessao_virtual: {e}")
        return []


def _extract_sessao_details(content_div: WebElement) -> dict[str, Any] | None:
    """Extract detailed session information from collapse div"""
    try:
        # Initialize with default values
        sessao_data: dict[str, Any] = {
            "lista": "",
            "relator": "",
            "orgao_julgador": "",
            "voto_texto": "",
            "data_inicio": "",
            "data_fim_prevista": "",
            "acompanham_relator": [],
            "url_relatorio": "",
            "conteudo_relatorio": "",
            "url_voto": "",
            "conteudo_voto": "",
        }

        # Try to extract data from the table if it exists
        try:
            # Look for table with more flexible selector
            table = content_div.find_element(By.CSS_SELECTOR, "table")
            rows = table.find_elements(By.TAG_NAME, "tr")

            for row in rows:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) == 2:
                    try:
                        label_elem = cells[0].find_element(
                            By.CSS_SELECTOR, ".processo-detalhes-bold"
                        )
                        label = label_elem.text
                    except Exception:
                        label = cells[0].text

                    try:
                        value_elem = cells[1].find_element(
                            By.CSS_SELECTOR, ".desc-lista"
                        )
                        value = value_elem.text
                    except Exception:
                        value = cells[1].text

                    # Map labels to our data structure
                    if "Lista:" in label:
                        sessao_data["lista"] = value
                    elif "Relator(a):" in label:
                        sessao_data["relator"] = value
                    elif "Órgão Julgador:" in label:
                        sessao_data["orgao_julgador"] = value
                    elif "Data início:" in label:
                        sessao_data["data_inicio"] = value
                    elif "Data prevista fim:" in label:
                        sessao_data["data_fim_prevista"] = value
        except Exception:
            pass

        voto_texto = content_div.find_element(By.CSS_SELECTOR, ".titulo-lista").text
        sessao_data["voto_texto"] = normalize_spaces(voto_texto)
        sessao_data["relator"] = content_div.find_element(
            By.CSS_SELECTOR, ".manifestacao-julgador"
        ).text
        # Extract URLs for relatorio and voto
        try:
            relatorio_link = content_div.find_element(
                By.CSS_SELECTOR, "a[href*='texto=']"
            )
            sessao_data["url_relatorio"] = relatorio_link.get_attribute("href")
            sessao_data["conteudo_relatorio"] = None
        except Exception:
            sessao_data["url_relatorio"] = None
            sessao_data["conteudo_relatorio"] = None

        try:
            voto_links = content_div.find_elements(By.CSS_SELECTOR, "a[href*='texto=']")
            if len(voto_links) > 1:
                sessao_data["url_voto"] = voto_links[1].get_attribute("href")
            else:
                sessao_data["url_voto"] = None
            sessao_data["conteudo_voto"] = None
        except Exception:
            sessao_data["url_voto"] = None
            sessao_data["conteudo_voto"] = None

        # Extract acompanham_relator list
        try:
            acompanham_list = []
            try:
                # Try the specific selector first
                acompanham_section = content_div.find_element(
                    By.CSS_SELECTOR, "#acompanha"
                )
                acompanham_items = acompanham_section.find_elements(
                    By.CSS_SELECTOR, ".manifestacao-julgador"
                )
                acompanham_list = [
                    item.text.strip() for item in acompanham_items if item.text.strip()
                ]
            except Exception:
                acompanham_list = []
            sessao_data["acompanham_relator"] = acompanham_list
        except Exception:
            sessao_data["acompanham_relator"] = []

        return sessao_data
    except Exception as e:
        logging.warning(f"Could not extract sessao details: {e}")
        return None
