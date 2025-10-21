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
) -> None:

    if config is None:
        config = ScraperConfig()

    out_file = f"{output_dir}/judex-mini_{classe}_{processo_inicial}-{processo_final}"

    output_config = OutputConfig.from_format_string(output_format)

    # logging do tempo de processamento
    timer = ProcessTimer()
    all_exported_files = []

    def handle_processos(processos: list):
        for processo in processos:
            processo_name = f"{classe} {processo}"
            process_start_time = timer.start_process(processo_name)
            logging.info(f"{processo_name}: START")

            item = process_single_process(processo, classe, config)

            # Only export if we have valid data
            if item:
                exported_files = export_item(
                    item,
                    out_file,
                    output_dir,
                    output_config,
                    overwrite,
                )
            else:
                exported_files = []

            # Track success based on whether files were exported
            all_exported_files.extend(exported_files)
            success = len(exported_files) > 0
            timer.end_process(processo_name, process_start_time, success=success)


    def handle_missing_processes(
        classe: str,
        processo_inicial: int,
        processo_final: int,
        output_dir: str,
        config: ScraperConfig,
    ) -> list[str]:
        for _ in range(config.driver_max_retries_for_missing):
            missing_processes = check_missing_processes(
                classe, processo_inicial, processo_final, output_dir
            )
            if not missing_processes:
                break
            handle_processos(missing_processes)

    processos = list(range(processo_inicial, processo_final + 1))

    handle_processos(processos)
    handle_missing_processes(
        classe, processo_inicial, processo_final, output_dir, config
    )
    
    timer.log_summary()

    if all_exported_files:
        logging.info(f"{processo_inicial}-{processo_final}: EXPORTED FILES:")
        for file_info in set(all_exported_files):
            logging.info(f"  {file_info}")
    else:
        logging.info(f"{classe} {processo_inicial}-{processo_final}: No files were exported (no successful processes)")


def process_single_process(
    processo: int,
    classe: str,
    config: ScraperConfig,
) -> Optional[StfItem]:
    """Process a single process and return exported files."""
    URL = f"{config.base_url}/processos/listarProcessos.asp?classe={classe}&numeroProcesso={processo}"
    processo_name = f"{classe} {processo}"

    with get_driver(config.user_agent) as driver:
        try:
            retry_driver_operation(driver, URL, f"{processo_name}: loading", config)
        except Exception as e:
            logging.error(f"Error loading {processo_name}: {e}")
            return None

        time.sleep(config.always_wait_time)
        document = find_element_by_xpath(
            driver,
            '//*[@id="conteudo"]',
            initial_delay=config.initial_delay,
            timeout=config.webdriver_timeout,
        )

        # Guard clause: skip if process not found
        if "Processo não encontrado" in document:
            logging.warning(f"{processo_name}: Processo não encontrado -- skipping")
            return None

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
            logging.warning(f"{processo_name}: descricao-procedencia não encontrado -- skipping")
            return None

        logging.info(f"{processo_name}: start extraction")

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

        logging.info(f"{processo_name}: exported")
        return item


def check_missing_processes(
    classe: str,
    processo_inicial: int,
    processo_final: int,
    output_dir: str,
) -> list[int]:
    """Check for missing process numbers in the CSV output and log them."""
    import os

    import pandas as pd

    # Construct the expected CSV file path
    csv_file = (
        f"{output_dir}/judex-mini_{classe}_{processo_inicial}-{processo_final}.csv"
    )

    if not os.path.exists(csv_file):
        logging.warning(f"CSV file not found: {csv_file}")
        return []

    try:
        # Read the CSV file
        df = pd.read_csv(csv_file)

        # Extract process numbers from the 'numero' column
        if "processo_id" not in df.columns:
            logging.warning("No 'processo_id' column found in CSV file")
            return

        # Get the process numbers that were successfully processed
        processed_numbers = set(df["processo_id"].astype(str))

        # Generate the expected range of process numbers
        expected_numbers = set(
            str(i) for i in range(processo_inicial, processo_final + 1)
        )

        return list(expected_numbers - processed_numbers)

    except Exception as e:
        logging.error(f"Error checking missing processes: {e}")
        return []
