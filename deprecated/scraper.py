"""
Main scraping logic for JUDEX MINI
"""

import logging
from datetime import datetime
from typing import List, Optional

import tenacity
from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver

from judex.config import ScraperConfig
from judex.data.export import export_item
from judex.data.missing import check_missing_processes
from judex.data.output import OutputConfig
from judex.data.types import StfItem
from deprecated.extraction.extract_andamentos import extract_andamentos
from deprecated.extraction.extract_assuntos import extract_assuntos
from deprecated.extraction.extract_badges import extract_badges
from deprecated.extraction.extract_data_protocolo import extract_data_protocolo
from deprecated.extraction.extract_deslocamentos import extract_deslocamentos
from deprecated.extraction.extract_incidente import extract_incidente
from judex.scraping.extraction.meio import extract_meio
from deprecated.extraction.extract_numero_origem import extract_numero_origem
from judex.scraping.extraction.numero_unico import extract_numero_unico
from deprecated.extraction.extract_orgao_origem import extract_orgao_origem
from deprecated.extraction.extract_origem import extract_origem
from deprecated.extraction.extract_partes import extract_partes
from deprecated.extraction.extract_peticoes import extract_peticoes
from deprecated.extraction.extract_primeiro_autor import extract_primeiro_autor
from judex.scraping.extraction.publicidade import extract_publicidade
from deprecated.extraction.extract_recursos import extract_recursos
from judex.scraping.extraction.relator import extract_relator
from deprecated.extraction.extract_sessao_virtual import extract_sessao_virtual
from deprecated.extraction.extract_volumes_folhas_apensos import (
    extract_apensos,
    extract_folhas,
    extract_volumes,
)
from deprecated.utils.driver import get_driver, load_page_with_retry
from judex.utils.text_utils import normalize_spaces
from judex.utils.timing import ProcessTimer, track_extraction_timing

__all__ = ["run_scraper", "check_missing_processes"]


def run_scraper(
    classe: str,
    processo_inicial: int,
    processo_final: int,
    output_format: str,
    output_dir: str,
    overwrite: bool,
    config: ScraperConfig,
) -> None:
    """Main scraping orchestration."""

    out_file = f"{output_dir}/judex-mini_{classe}_{processo_inicial}-{processo_final}"
    output_config = OutputConfig.from_format_string(output_format)
    timer = ProcessTimer()
    all_exported_files = []

    try:
        # Process initial batch
        processos = list(range(processo_inicial, processo_final + 1))
        exported_files = process_batch(
            processos,
            classe,
            config,
            out_file,
            output_dir,
            output_config,
            overwrite,
            timer,
        )
        all_exported_files.extend(exported_files)

        # Retry missing processes
        missing_files = retry_missing_processes(
            classe,
            processo_inicial,
            processo_final,
            output_dir,
            config,
            out_file,
            output_config,
            overwrite,
            timer,
        )
        all_exported_files.extend(missing_files)

        if all_exported_files:
            for file_info in all_exported_files:
                logging.info(f"Exported file: {file_info}")
        else:
            logging.warning(
                f"{classe} {processo_inicial}-{processo_final}: NO FILES EXPORTED"
            )
    finally:
        if timer.process_times:
            logging.info("=== SCRAPER ENDED - SHOWING REPORT ===")
            timer.log_summary()


def process_batch(
    processos: list,
    classe: str,
    config: ScraperConfig,
    out_file: str,
    output_dir: str,
    output_config: OutputConfig,
    overwrite: bool,
    timer: ProcessTimer,
) -> List[str]:
    """Process a batch of processes and return exported files."""
    all_exported_files = []

    with get_driver(config.user_agent) as driver:
        for processo in processos:
            processo_name = f"{classe} {processo}"
            process_start_time = timer.start_process(processo_name)


            logging.info(f"{processo_name}: iniciado")

            item = process_single_process_with_driver(processo, classe, config, driver)

            if item:
                exported_files = export_item(
                    item, out_file, output_dir, output_config, overwrite
                )
            else:
                exported_files = []

            all_exported_files.extend(exported_files)
            success = len(exported_files) > 0
            timer.end_process(processo_name, process_start_time, success=success)

    return all_exported_files


# def process_single_process(
#     processo: int, classe: str, config: ScraperConfig
# ) -> Optional[StfItem]:
#     """Process a single process and return the extracted item."""
#     URL = f"{config.base_url}/processos/listarProcessos.asp?classe={classe}&numeroProcesso={processo}"
#     processo_name = f"{classe} {processo}"

#     # context manager -- handles closing the driver
#     with get_driver(config.user_agent) as driver:
#         try:
#             document = load_page_with_retry(driver, URL, processo_name, config)
#         except Exception as e:
#             error_msg = str(e) if str(e) else type(e).__name__
#             logging.error(f"Error loading {processo_name}: {error_msg}")
#             return None

#         soup = BeautifulSoup(document, "lxml")
#         data = extract_processo(driver, soup, classe, processo, config)
#         return data

def process_single_process_with_driver(
    processo: int, classe: str, config: ScraperConfig, driver: WebDriver
) -> Optional[StfItem]:
    """Process a single process with an existing driver and return the extracted item."""
    URL = f"{config.base_url}/processos/listarProcessos.asp?classe={classe}&numeroProcesso={processo}"
    processo_name = f"{classe} {processo}"

    try:
        document = load_page_with_retry(driver, URL, processo_name, config)
    except tenacity.RetryError as retry_error:
        logging.error(f"Exhausted retry attempts for {processo_name}: {retry_error}")
        return None
    except Exception as e:
        error_msg = str(e) if str(e) else type(e).__name__
        logging.error(f"Error loading {processo_name}: {error_msg}")
        return None

    soup = BeautifulSoup(document, "lxml")
    data = extract_processo(driver, soup, classe, processo, config)
    return data


def extract_processo(
    driver: WebDriver,
    soup: BeautifulSoup,
    classe: str,
    processo: int,
    config: ScraperConfig,
) -> StfItem:
    """Extract all data from a process page."""
    return {
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
        "volumes": extract_volumes(driver, soup),
        "folhas": extract_folhas(driver, soup),
        "apensos": extract_apensos(driver, soup),
        "relator": extract_relator(soup),
        "primeiro_autor": extract_primeiro_autor(driver, soup),
        "partes": extract_partes(driver, soup),
        "andamentos": extract_andamentos(driver, soup, config),
        "sessao_virtual": extract_sessao_virtual(driver, soup),
        "deslocamentos": extract_deslocamentos(driver, soup),
        "peticoes": extract_peticoes(driver, soup),
        "recursos": extract_recursos(driver, soup),
        "pautas": [],
        "status": 200,
        "extraido": datetime.now().isoformat(),
        "html": normalize_spaces(driver.page_source),
    }


def retry_missing_processes(
    classe: str,
    processo_inicial: int,
    processo_final: int,
    output_dir: str,
    config: ScraperConfig,
    out_file: str,
    output_config: OutputConfig,
    overwrite: bool,
    timer: ProcessTimer,
) -> List[str]:
    """Checks if extraction failed for a process and retries."""
    all_exported_files = []

    for attempt in range(config.driver_max_retries_for_missing):
        missing_processes = check_missing_processes(
            classe, processo_inicial, processo_final, output_dir, output_config
        )
        if not missing_processes:
            break

        logging.info(
            f"Retrying {len(missing_processes)} missing processes (attempt {attempt + 1}/{config.driver_max_retries_for_missing})"
        )
        exported_files = process_batch(
            missing_processes,
            classe,
            config,
            out_file,
            output_dir,
            output_config,
            overwrite,
            timer,
        )
        all_exported_files.extend(exported_files)

    return all_exported_files
