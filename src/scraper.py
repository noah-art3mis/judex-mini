"""
Main scraping logic for JUDEX MINI
"""

import logging
from datetime import datetime
from typing import List, Optional

from bs4 import BeautifulSoup
from selenium.webdriver.remote.webdriver import WebDriver

from src.config import ScraperConfig
from src.data.export import export_item
from src.data.output import OutputConfig
from src.data.types import StfItem
from src.extraction import (
    extract_andamentos,
    extract_apensos,
    extract_assuntos,
    extract_badges,
    extract_data_protocolo,
    extract_deslocamentos,
    extract_folhas,
    extract_incidente,
    extract_meio,
    extract_numero_origem,
    extract_numero_unico,
    extract_orgao_origem,
    extract_origem,
    extract_partes,
    extract_peticoes,
    extract_primeiro_autor,
    extract_publicidade,
    extract_recursos,
    extract_relator,
    extract_volumes,
)
from src.utils.driver import get_driver, load_page_with_retry
from src.utils.text_utils import normalize_spaces
from src.utils.timing import ProcessTimer


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

    timer.log_summary()

    if all_exported_files:
        logging.info(f"{classe} {processo_inicial}-{processo_final}: EXPORTED FILES:")
        for file_info in all_exported_files:
            logging.info(f"  {file_info}")
    else:
        logging.warning(
            f"{classe} {processo_inicial}-{processo_final}: NO FILES EXPORTED"
        )


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

    for processo in processos:
        processo_name = f"{classe} {processo}"
        process_start_time = timer.start_process(processo_name)
        logging.info(f"{processo_name}: START")

        item = process_single_process(processo, classe, config)

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


def process_single_process(
    processo: int, classe: str, config: ScraperConfig
) -> Optional[StfItem]:
    """Process a single process and return the extracted item."""
    URL = f"{config.base_url}/processos/listarProcessos.asp?classe={classe}&numeroProcesso={processo}"
    processo_name = f"{classe} {processo}"

    # context manager -- handles closing the driver
    with get_driver(config.user_agent) as driver:
        try:
            document = load_page_with_retry(driver, URL, processo_name, config)
        except Exception as e:
            logging.error(f"Error loading {processo_name}: {e}")
            return None

        soup = BeautifulSoup(document, "html.parser")
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
        "sessao_virtual": [],
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


def check_missing_processes(
    classe: str,
    processo_inicial: int,
    processo_final: int,
    output_dir: str,
    output_config: OutputConfig,
) -> list[int]:
    """Check for missing process numbers in the output files and log them."""
    import json
    import os

    import pandas as pd

    # Check which output files exist
    base_file = f"{output_dir}/judex-mini_{classe}_{processo_inicial}-{processo_final}"

    # Try to find an existing output file
    existing_file = None
    file_type = None

    if output_config.csv and os.path.exists(base_file + ".csv"):
        existing_file = base_file + ".csv"
        file_type = "csv"
    elif output_config.jsonl and os.path.exists(base_file + ".jsonl"):
        existing_file = base_file + ".jsonl"
        file_type = "jsonl"
    elif output_config.json and os.path.exists(base_file + ".json"):
        existing_file = base_file + ".json"
        file_type = "json"

    if not existing_file:
        logging.warning(
            f"No output file found for {classe} {processo_inicial}-{processo_final}"
        )
        return []

    try:
        if file_type == "csv":
            # Read CSV file
            df = pd.read_csv(existing_file)
            if "processo_id" not in df.columns:
                logging.warning("No 'processo_id' column found in CSV file")
                return []
            processed_numbers = set(df["processo_id"].astype(str))

        elif file_type == "jsonl":
            # Read JSONL file
            processed_numbers = set()
            with open(existing_file, "r") as f:
                for line in f:
                    data = json.loads(line.strip())
                    if "processo_id" in data:
                        processed_numbers.add(str(data["processo_id"]))

        elif file_type == "json":
            # Read JSON file
            with open(existing_file, "r") as f:
                data = json.load(f)
                processed_numbers = set(
                    str(item["processo_id"]) for item in data if "processo_id" in item
                )

        # Generate the expected range of process numbers
        expected_numbers = set(
            str(i) for i in range(processo_inicial, processo_final + 1)
        )

        return list(expected_numbers - processed_numbers)

    except Exception as e:
        logging.error(f"Error checking missing processes: {e}")
        return []
