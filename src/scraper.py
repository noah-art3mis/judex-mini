"""
Main scraping logic for JUDEX MINI
"""

import logging
import time
from datetime import datetime
from typing import List, Optional

from bs4 import BeautifulSoup

from src.config import ScraperConfig
from src.data.export import export_item
from src.data.output import OutputConfig
from src.data.types import StfItem
from src.extraction import (
    extract_andamentos,
    extract_assuntos,
    extract_badges,
    extract_data_protocolo,
    extract_deslocamentos,
    extract_incidente,
    extract_meio,
    extract_numero_origem,
    extract_numero_unico,
    extract_orgao_origem,
    extract_origem,
    extract_partes,
    extract_primeiro_autor,
    extract_publicidade,
    extract_relator,
    extract_volumes_folhas_apensos,
)
from src.utils.driver import get_driver, retry_driver_operation
from src.utils.get_element import find_element_by_xpath
from src.utils.text_utils import normalize_spaces
from src.utils.timing import ProcessTimer


def run_scraper(
    classe: str,
    processo_inicial: int,
    processo_final: int,
    output_format: str,
    output_dir: str,
    overwrite: bool,
    config: Optional[ScraperConfig] = None,
) -> List[str]:

    if config is None:
        config = ScraperConfig()

    out_file = f"{output_dir}/judex-mini_{classe}_{processo_inicial}-{processo_final}"

    output = OutputConfig.from_format_string(output_format)

    # logging do tempo de processamento
    timer = ProcessTimer()
    all_exported_files = []

    for processo in range(processo_inicial, processo_final + 1):
        processo_name = f"{classe} {processo}"
        process_start_time = timer.start_process(processo_name)
        logging.info(f"Processing {processo_name}")

        # Process the single process
        exported_files = process_single_process(
            processo=processo,
            classe=classe,
            out_file=out_file,
            output_dir=output_dir,
            output=output,
            overwrite=overwrite,
            user_agent=config.user_agent,
            config=config,
        )
        all_exported_files.extend(exported_files)

        # Track success based on whether files were exported
        success = len(exported_files) > 0
        timer.end_process(processo_name, process_start_time, success=success)

    timer.log_summary()

    return all_exported_files


def process_single_process(
    processo: int,
    classe: str,
    out_file: str,
    output_dir: str,
    output: OutputConfig,
    overwrite: bool,
    user_agent: str,
    config: ScraperConfig,
) -> List[str]:
    """Process a single process and return exported files."""
    URL = f"{config.base_url}/processos/listarProcessos.asp?classe={classe}&numeroProcesso={processo}"
    processo_name = f"{classe} {processo}"

    with get_driver(user_agent) as driver:
        # Reset driver with exponential backoff

        try:
            retry_driver_operation(driver, URL, f"loading {processo_name}", config)
        except Exception as e:
            logging.error(f"Error loading {processo_name}: {e}")
            return []

        time.sleep(config.always_wait_time)
        document = find_element_by_xpath(
            driver,
            '//*[@id="conteudo"]',
            initial_delay=config.initial_delay,
            timeout=config.webdriver_timeout,
        )

        # Guard clause: skip if process not found
        if "Processo não encontrado" in document:
            logging.warning(f"Process not found for {processo_name} - skipping")
            return []

        # Guard clause: skip if process not found
        if (
            find_element_by_xpath(
                driver,
                '//*[@id="descricao-procedencia"]',
                initial_delay=config.initial_delay,
                timeout=config.webdriver_timeout,
            )
            == ""
        ):
            logging.warning(f"Process not found for {processo_name} - skipping")
            return []

        logging.info(f"Process found for {processo_name} - starting data extraction")

        soup = BeautifulSoup(document, "html.parser")

        # Extract data using extraction functions
        volumes_folhas_apensos = extract_volumes_folhas_apensos(driver, soup)
        item: StfItem = {
            "incidente": extract_incidente(driver, soup),
            "classe": classe,
            "processo_id": processo,
            "numero_unico": extract_numero_unico(soup),
            "meio": extract_meio(soup),
            "publicidade": extract_publicidade(soup),
            "badges": extract_badges(None, driver, soup),
            "assuntos": extract_assuntos(driver, soup),
            "data_protocolo": extract_data_protocolo(driver, soup),
            "orgao_origem": extract_orgao_origem(driver, soup),
            "origem": extract_origem(driver, soup),
            "numero_origem": extract_numero_origem(driver, soup),
            "volumes": volumes_folhas_apensos.get("volumes", None),
            "folhas": volumes_folhas_apensos.get("folhas", None),
            "apensos": volumes_folhas_apensos.get("apensos", None),
            "relator": extract_relator(soup),
            "primeiro_autor": extract_primeiro_autor(driver, soup),
            "partes": extract_partes(driver, soup),
            "andamentos": extract_andamentos(driver, soup, config),
            "sessao_virtual": [],
            "deslocamentos": extract_deslocamentos(driver, soup),
            "peticoes": [],
            "recursos": [],
            "pautas": [],
            "status": 200,
            "extraido": datetime.now().isoformat(),
            "html": normalize_spaces(document),
        }

        # Export the extracted data
        exported_files = export_item(
            item,
            out_file,
            output_dir,
            output,
            overwrite,
        )

        logging.info(f"Successfully extracted and exported data for {processo_name}")
        return exported_files
