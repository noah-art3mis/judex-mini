import logging
import time
from datetime import datetime

import typer
from bs4 import BeautifulSoup

from src.driver import get_driver, retry_driver_operation
from src.export import export_item
from src.extraction import (
    extract_andamentos,
    extract_assuntos,
    extract_badges,
    extract_classe,
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
from src.extraction.functions.base import normalize_spaces
from src.get_element import find_element_by_xpath
from src.output_config import OutputConfig
from src.timing import ProcessTimer
from src.types import StfItem

# from src.validation import check_is_valid_page


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

    logging.info("=== JUDEX MINI START ===")

    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    out_file = f"{output_dir}/judex-mini_{classe}_{processo_inicial}-{processo_final}"
    ALWAYS_WAIT_TIME = 2

    output_config = OutputConfig.from_format_string(output_format)
    logging.info(f"Output formats enabled: {output_config}")

    timer = ProcessTimer()
    all_exported_files = []

    for processo in range(processo_inicial, processo_final + 1):
        processo_name = f"{classe} {processo}"
        process_start_time = timer.start_process(processo_name)
        logging.info(f"Processing {processo_name}")

        URL = f"https://portal.stf.jus.br/processos/listarProcessos.asp?classe={classe}&numeroProcesso={processo}"

        with get_driver(USER_AGENT) as driver:
            # Use tenacity for retry logic
            retry_driver_operation(driver, URL, f"loading {classe} {processo}")

            document = find_element_by_xpath(driver, '//*[@id="conteudo"]')

            if (
                "Processo não encontrado" not in document
                and find_element_by_xpath(driver, '//*[@id="descricao-procedencia"]')
                != ""
            ):
                logging.info(
                    f"Process found for {classe} {processo} - starting data extraction"
                )

                # Wait for page to fully load
                time.sleep(ALWAYS_WAIT_TIME)

                # Parse document with BeautifulSoup for extraction functions
                soup = BeautifulSoup(document, "html.parser")

                # Extract data using extraction functions
                volumes_folhas_apensos = extract_volumes_folhas_apensos(driver, soup)

                item = StfItem(
                    # Basic process identification
                    incidente=extract_incidente(driver, soup),
                    classe=extract_classe(soup),
                    processo_id=processo,
                    numero_unico=extract_numero_unico(soup),
                    # Process classification
                    meio=extract_meio(soup),
                    publicidade=extract_publicidade(soup),
                    badges=extract_badges(None, driver, soup),
                    # Process content
                    assuntos=extract_assuntos(driver, soup),
                    data_protocolo=extract_data_protocolo(driver, soup),
                    orgao_origem=extract_orgao_origem(driver, soup),
                    origem=extract_origem(driver, soup),
                    numero_origem=extract_numero_origem(driver, soup),
                    # Document counts
                    volumes=volumes_folhas_apensos.get("volumes", None),
                    folhas=volumes_folhas_apensos.get("folhas", None),
                    apensos=volumes_folhas_apensos.get("apensos", None),
                    # People and parties
                    relator=extract_relator(soup),
                    primeiro_autor=extract_primeiro_autor(driver, soup),
                    partes=extract_partes(driver, soup),
                    # Process steps and activities
                    andamentos=extract_andamentos(driver, soup),
                    sessao_virtual=[],
                    deslocamentos=extract_deslocamentos(driver, soup),
                    peticoes=[],
                    recursos=[],
                    pautas=[],
                    # Metadata
                    status=200,
                    extraido=datetime.now().isoformat(),
                    html=normalize_spaces(document),
                )

                # Export the extracted data
                exported_files = export_item(item, out_file, output_dir, output_config)
                all_exported_files.extend(exported_files)

        timer.end_process(processo_name, process_start_time, success=True)

    logging.info("🎉 Finished processing all processes!")

    timer.log_summary()

    if all_exported_files:
        logging.info("📁 EXPORTED FILES:")
        for file_info in all_exported_files:
            logging.info(f"  {file_info}")
    else:
        logging.info("📁 No files were exported (no successful processes)")


if __name__ == "__main__":
    typer.run(main)
