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

# configuracoes da cli
def main(
    classe: str = typer.Option(
        "RE", "-c", "--classe", help="Process class (RE, AI, ADI, etc.)"
    ),
    processo_inicial: int = typer.Option(
        1234567, "-i", "--processo-inicial", help="Initial process number"
    ),
    processo_final: int = typer.Option(
        1234567, "-f", "--processo-final", help="Final process number"
    ),
    output_format: str = typer.Option(
        "csv", "-o", "--output-format", help="Output format (csv, json)"
    ),
    output_dir: str = typer.Option(
        "output", "-d", "--output-dir", help="Output directory"
    ),
    log_level: str = typer.Option(
        "INFO", "-l", "--log-level", help="Log level (DEBUG, INFO, WARNING, ERROR)"
    ),
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

    # logging do tempo de processamento
    timer = ProcessTimer()
    all_exported_files = []

    for processo in range(processo_inicial, processo_final + 1):
        URL = f"https://portal.stf.jus.br/processos/listarProcessos.asp?classe={classe}&numeroProcesso={processo}"

        processo_name = f"{classe} {processo}"
        process_start_time = timer.start_process(processo_name)
        logging.info(f"Processing {processo_name}")

        with get_driver(USER_AGENT) as driver:
            
            # reset driver com exponential backoff
            retry_driver_operation(driver, URL, f"loading {processo_name}")

            document = find_element_by_xpath(driver, '//*[@id="conteudo"]')

            if (
                "Processo não encontrado" not in document
                and find_element_by_xpath(driver, '//*[@id="descricao-procedencia"]')
                != ""
            ):
                logging.info(
                    f"Process found for {processo_name} - starting data extraction"
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

                # Convert StfItem to dictionary for JSON serialization
                item_dict = {
                    "incidente": item.incidente,
                    "classe": item.classe,
                    "processo_id": item.processo_id,
                    "numero_unico": item.numero_unico,
                    "meio": item.meio,
                    "publicidade": item.publicidade,
                    "badges": item.badges,
                    "assuntos": item.assuntos,
                    "data_protocolo": item.data_protocolo,
                    "orgao_origem": item.orgao_origem,
                    "origem": item.origem,
                    "numero_origem": item.numero_origem,
                    "volumes": item.volumes,
                    "folhas": item.folhas,
                    "apensos": item.apensos,
                    "relator": item.relator,
                    "primeiro_autor": item.primeiro_autor,
                    "partes": item.partes,
                    "andamentos": item.andamentos,
                    "sessao_virtual": item.sessao_virtual,
                    "deslocamentos": item.deslocamentos,
                    "peticoes": item.peticoes,
                    "recursos": item.recursos,
                    "pautas": item.pautas,
                    "status": item.status,
                    "extraido": item.extraido,
                    "html": item.html,
                }

                # Export the extracted data
                exported_files = export_item(
                    item_dict, out_file, output_dir, output_config
                )
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
