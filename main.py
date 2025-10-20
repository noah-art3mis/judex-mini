import logging
import os

import typer
from bs4 import BeautifulSoup

from src.driver import get_driver, retry_driver_operation
from src.export import export_data
from src.extraction import (
    extract_andamentos,
    extract_assuntos,
    extract_data_protocolo,
    extract_deslocamentos,
    extract_incidente,
    extract_liminar,
    extract_orgao_origem,
    extract_origem,
    extract_partes,
    extract_primeiro_autor,
    extract_relator,
    extract_tipo_processo,
    normalize_spaces,
)
from src.get_element import find_element_by_id, find_element_by_xpath
from src.output_config import OutputConfig
from src.timing import ProcessTimer
from src.validation import check_is_valid_page

# Define column names for CSV output
colunas = [
    "incidente",
    "classe",
    "nome_processo",
    "classe_extenso",
    "tipo_processo",
    "liminar",
    "origem",
    "relator",
    "autor1",
    "len(partes_total)",
    "partes_total",
    "data_protocolo",
    "origem_orgao",
    "lista_assuntos",
    "len(andamentos_lista)",
    "andamentos_lista",
    "len(decisões)",
    "decisões",
    "len(deslocamentos)",
    "deslocamentos_lista",
]


def arquivo_existe(arquivo):
    return os.path.exists(arquivo) and os.path.getsize(arquivo) > 0


def main(
    classe: str = "RE",
    processo_inicial: int = 1234567,
    processo_final: int = 1234567,
    output_format: str = "csv",
    output_dir: str = "output",
    log_level: str = "INFO",
) -> None:

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    os.makedirs(output_dir, exist_ok=True)

    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    out_file = f"{output_dir}/judex-mini_{classe}_{processo_inicial}-{processo_final}"

    # Parse output format
    output_config = OutputConfig.from_format_string(output_format)
    logging.info(f"📋 Output formats enabled: {output_config}")

    request_count = 0
    timer = ProcessTimer()
    all_exported_files = []

    for i in range(processo_inicial, processo_final + 1):
        processo_num = i
        processo_name = f"{classe} {processo_num}"
        process_start_time = timer.start_process(processo_name)
        logging.info(f"Processing {processo_name}")

        URL = f"https://portal.stf.jus.br/processos/listarProcessos.asp?classe={classe}&numeroProcesso={processo_num}"
        request_count += 1

        # Use context manager for driver with tenacity retries
        try:
            with get_driver(USER_AGENT) as driver:
                # Use tenacity for retry logic
                retry_driver_operation(driver, URL, f"loading {classe} {processo_num}")

                # Check if page is valid
                check_is_valid_page(driver)

                document = find_element_by_xpath(driver, '//*[@id="conteudo"]')

                if (
                    "Processo não encontrado" not in document
                    and find_element_by_xpath(
                        driver, '//*[@id="descricao-procedencia"]'
                    )
                    != ""
                ):
                    logging.info(
                        f"Process found for {classe} {processo_num} - starting data extraction"
                    )

                    # Parse document with BeautifulSoup for extraction functions
                    soup = BeautifulSoup(document, "html.parser")

                    # Get basic process information
                    nome_processo = find_element_by_id(driver, "classe-numero-processo")
                    titulo_processo = find_element_by_xpath(
                        driver, '//*[@id="texto-pagina-interna"]/div/div/div/div[1]'
                    )

                    # Extract data using extraction functions
                    item = {
                        "incidente": extract_incidente(soup),
                        "nome_processo": normalize_spaces(nome_processo),
                        "classe_extenso": normalize_spaces(
                            find_element_by_xpath(
                                driver,
                                '//*[@id="texto-pagina-interna"]/div/div/div/div[2]/div[1]/div/div[1]',
                            )
                        ),
                        "titulo_processo": normalize_spaces(titulo_processo),
                        "tipo_processo": extract_tipo_processo(soup),
                        "liminar": extract_liminar(driver, titulo_processo),
                        "origem": extract_origem(driver, soup),
                        "relator": extract_relator(soup),
                        "partes_total": extract_partes(driver, soup),
                        "primeiro_autor": extract_primeiro_autor(driver, soup),
                        "data_protocolo": extract_data_protocolo(driver, soup),
                        "origem_orgao": extract_orgao_origem(driver, soup),
                        "lista_assuntos": extract_assuntos(driver, soup),
                        "andamentos": extract_andamentos(driver, soup),
                        "deslocamentos": extract_deslocamentos(driver, soup),
                    }

                    # Export the extracted data
                    exported_files = export_data(item, out_file, output_config)
                    all_exported_files.extend(exported_files)

        except Exception as e:
            logging.error(f"Error processing {processo_name}: {e}")
            timer.end_process(processo_name, process_start_time, success=False)
            continue

        # Mark as successful
        timer.end_process(processo_name, process_start_time, success=True)

    # Log completion of all processes
    logging.info("🎉 Finished processing all processes!")

    # Log comprehensive timing summary
    timer.log_summary()

    # Log exported files summary
    if all_exported_files:
        logging.info("📁 EXPORTED FILES:")
        for file_info in all_exported_files:
            logging.info(f"  {file_info}")
    else:
        logging.info("📁 No files were exported (no successful processes)")


if __name__ == "__main__":
    typer.run(main)
