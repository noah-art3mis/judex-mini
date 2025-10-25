import logging
import time
from typing import Dict, List

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from src.utils.pdf_utils import extract_pdf_text
from src.utils.text_utils import normalize_spaces
from src.utils.timing import track_extraction_timing


def _parse_sessao_virtual_item(sessao_element: WebElement) -> Dict:
    """
    Parses a single virtual session date block (the content inside a nested collapse).
    """
    sessao_soup = BeautifulSoup(sessao_element.get_attribute("innerHTML") or "", "lxml")
    data = {}
    try:
        # Extract metadata from 'lista_cabecalho'
        metadata = {}
        table = sessao_soup.find("table", id="lista_cabecalho")
        if table:
            for row in table.find_all("tr"):
                cols = row.find_all("td")
                if len(cols) == 2:
                    # Clean key: "Relator(a):" -> "relator"
                    key = normalize_spaces(cols[0].text.replace(":", "")).lower()
                    key = key.replace("(", "").replace(")", "").replace(" ", "_")
                    value = normalize_spaces(cols[1].text)
                    metadata[key] = value
        data["metadata"] = metadata

        # Extract 'Voto do Relator'
        voto_relator = sessao_soup.find("div", class_="titulo-lista")
        data["voto_relator"] = (
            normalize_spaces(voto_relator.text) if voto_relator else None
        )

        # Extract votes
        votes = {
            "relator": [],
            "acompanha_relator": [],
            "diverge_relator": [],
            "acompanha_divergencia": [],
            "pedido_vista": [],
        }

        relator_div = sessao_soup.find("div", id="relator")
        if relator_div:
            votes["relator"] = [
                normalize_spaces(m.text)
                for m in relator_div.find_all("div", class_="manifestacao-julgador")
            ]

        acompanha_div = sessao_soup.find("div", id="acompanha")
        if acompanha_div:
            votes["acompanha_relator"] = [
                normalize_spaces(m.text)
                for m in acompanha_div.find_all("div", class_="manifestacao-julgador")
            ]

        diverge_div = sessao_soup.find("div", id="diverge")
        if diverge_div:
            votes["diverge_relator"] = [
                normalize_spaces(m.text)
                for m in diverge_div.find_all("div", class_="manifestacao-julgador")
            ]

        acompanha_div_div = sessao_soup.find("div", id="acompanha-divergencia")
        if acompanha_div_div:
            votes["acompanha_divergencia"] = [
                normalize_spaces(m.text)
                for m in acompanha_div_div.find_all(
                    class_=["manifestacao-julgador-linha1", "manifestacao-julgador"]
                )
            ]

        vista_div = sessao_soup.find("div", id="vista")
        if vista_div:
            votes["pedido_vista"] = [
                normalize_spaces(m.text)
                for m in vista_div.find_all("div", class_="manifestacao-julgador")
            ]

        data["votes"] = votes

        # Extract PDF links and text
        pdf_texts = {}
        # Find all <a> tags within the current element that contain 'votacao?texto='
        pdf_links = sessao_element.find_elements(
            By.CSS_SELECTOR, "a[href*='votacao?texto=']"
        )
        for link in pdf_links:
            try:
                url = link.get_attribute("href")
                text_type = normalize_spaces(link.text)  # e.g., "Relatório", "Voto"
                # Use the imported function to get PDF text
                pdf_texts[text_type] = extract_pdf_text(url)
            except Exception as e:
                logging.warning(f"Could not extract PDF from {url}: {e}")
        data["documentos"] = pdf_texts

    except Exception as e:
        logging.warning(f"Error parsing session item: {e}")
    return data


def _parse_tema_item(tema_element: WebElement) -> Dict:
    """Parses the 'Tema' block."""
    tema_soup = BeautifulSoup(tema_element.get_attribute("innerHTML") or "", "lxml")
    data = {"tipo": "tema"}
    try:
        # Extract info
        info_div = tema_soup.find(
            "div", style=lambda s: "background-color: #f2f2f2" in s if s else False
        )
        if info_div:
            # Get clean text from all lines, skipping empty ones
            info_lines = [normalize_spaces(line) for line in info_div.stripped_strings]
            data["info"] = "\n".join(info_lines)

        # Extract table data
        table = tema_soup.find("table")
        votes = []
        if table:
            headers = [
                normalize_spaces(th.text) for th in table.find("thead").find_all("th")
            ]
            for row in table.find("tbody").find_all("tr"):
                vote = {}
                cells = row.find_all("td")
                if len(cells) == len(headers):
                    for i, header in enumerate(headers):
                        vote[header] = normalize_spaces(cells[i].text)
                    # Check for link in the last cell
                    link = cells[-1].find("a")
                    if link:
                        vote["Link"] = link.get_attribute("href")
                if vote:
                    votes.append(vote)
        data["votes"] = votes
    except Exception as e:
        logging.warning(f"Error parsing tema item: {e}")
    return data


@track_extraction_timing
def extract_sessao_virtual(driver: WebDriver, soup: BeautifulSoup) -> List[Dict]:
    """Extract sessao_virtual from AJAX-loaded content"""
    try:
        sessao_tab = driver.find_element(By.CSS_SELECTOR, "a[href='#sessao-virtual']")
        driver.execute_script("arguments[0].click();", sessao_tab)
        logging.debug("Clicked Sessão virtual tab")

        julgamento_items = driver.find_elements(
            By.CSS_SELECTOR, "#sessao-virtual .julgamento-item"
        )
        logging.debug(f"Found {len(julgamento_items)} top-level julgamento items")

        if not julgamento_items:
            logging.debug("No julgamento items found in Sessão virtual - exiting early")
            return []

        wait = WebDriverWait(driver, 10)

        sessao_list = []

        for i, julgamento_item in enumerate(julgamento_items):
            logging.debug(f"Processing julgamento item {i+1}/{len(julgamento_items)}")

            try:
                # 1. Find and click the main button for this item
                main_button = julgamento_item.find_element(
                    By.CSS_SELECTOR, "button[data-bs-toggle='collapse']"
                )
                main_target_id = main_button.get_attribute("data-bs-target").lstrip("#")

                if main_button.get_attribute("aria-expanded") == "false":
                    driver.execute_script("arguments[0].click();", main_button)
                    logging.debug(f"Clicked main button for {main_target_id}")

                # Wait for the main collapse div to be visible
                main_collapse_div = wait.until(
                    EC.visibility_of_element_located((By.ID, main_target_id))
                )
                time.sleep(0.5)  # Allow animations/JS to settle

                # 2. Check what's inside this main_collapse_div

                # CASE A: "Sessão" item with nested date links (e.g., #listasJulgamento2083816)
                date_links = main_collapse_div.find_elements(
                    By.CSS_SELECTOR, "a[data-bs-toggle='collapse'][href*='#listas']"
                )

                if date_links:
                    logging.debug(
                        f"Found {len(date_links)} nested date links in {main_target_id}"
                    )
                    for j, date_link in enumerate(date_links):
                        try:
                            nested_target_id = date_link.get_attribute("href").split(
                                "#"
                            )[-1]
                            logging.debug(
                                f"Processing nested link {j+1}/{len(date_links)} for {nested_target_id}"
                            )

                            if date_link.get_attribute("aria-expanded") == "false":
                                driver.execute_script(
                                    "arguments[0].click();", date_link
                                )

                            nested_collapse_div = wait.until(
                                EC.visibility_of_element_located(
                                    (By.ID, nested_target_id)
                                )
                            )
                            time.sleep(0.5)  # Settle

                            # --- SCRAPE NESTED DATA ---
                            sessao_data = _parse_sessao_virtual_item(
                                nested_collapse_div
                            )
                            sessao_data["julgamento_item_titulo"] = normalize_spaces(
                                main_button.text
                            )
                            sessao_list.append(sessao_data)
                            logging.debug(
                                f"Successfully scraped data from {nested_target_id}"
                            )

                            # Collapse the nested div
                            driver.execute_script("arguments[0].click();", date_link)
                            wait.until(
                                EC.invisibility_of_element_located(
                                    (By.ID, nested_target_id)
                                )
                            )

                        except Exception as e:
                            logging.warning(
                                f"Error processing nested link {j+1} ({nested_target_id}): {e}"
                            )
                            continue

                # CASE B: "Tema" item with a direct table (e.g., #listasJulgamentoTema)
                else:
                    tema_table = main_collapse_div.find_elements(By.TAG_NAME, "table")
                    if tema_table:
                        logging.debug(
                            f"Found 'Tema' table in {main_target_id}. Parsing..."
                        )

                        # --- SCRAPE TEMA DATA ---
                        tema_data = _parse_tema_item(main_collapse_div)
                        tema_data["julgamento_item_titulo"] = normalize_spaces(
                            main_button.text
                        )
                        sessao_list.append(tema_data)
                        logging.debug(
                            f"Successfully scraped data from 'Tema' {main_target_id}"
                        )

                # Collapse the main item
                driver.execute_script("arguments[0].click();", main_button)
                wait.until(EC.invisibility_of_element_located((By.ID, main_target_id)))

            except Exception as e:
                logging.warning(f"Error processing julgamento item {i+1}: {e}")
                continue

        logging.debug(
            f"Successfully extracted {len(sessao_list)} data blocks from Sessão virtual"
        )
        return sessao_list

    except Exception as e:
        logging.error(f"Failed to extract sessao_virtual: {e}", exc_info=True)
        return []
