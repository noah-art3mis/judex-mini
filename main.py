import logging
import os

import pandas as pd
import typer
from selenium.webdriver.common.by import By

import utils.dsl as dsl
from utils.documents import retry_document_download
from utils.driver import get_driver, retry_driver_operation
from utils.get_element import (
    find_element_by_id,
    find_element_by_xpath,
    find_elements_by_class,
)
from utils.validation import check_is_valid_page

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


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
    classe: str = "RE", processo_inicial: int = 1234567, processo_final: int = 1234567
) -> None:

    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    out_file = f"output/judex-mini_{classe}_{processo_inicial}-{processo_final}"
    os.makedirs("output", exist_ok=True)
    save_to_csv = True
    save_to_jsonl = False
    
    processonaoencontrado = 0
    request_count = 0

    for i in range(processo_inicial, processo_final + 1):
        if processonaoencontrado > 20:
            logging.warning("Stopping: 20 consecutive processes not found")
            break

        processo_num = processo_inicial + i
        logging.info(f"Processing {classe} {processo_num}")

        URL = f"https://portal.stf.jus.br/processos/listarProcessos.asp?classe={classe}&numeroProcesso={processo_num}"
        request_count += 1

        # Use context manager for driver with tenacity retries
        try:
            with get_driver(USER_AGENT) as driver:
                # Use tenacity for retry logic
                retry_driver_operation(driver, URL, f"loading {classe}{processo_num}")

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
                        f"Process found for {classe}{processo_num} - starting data extraction"
                    )
                    processonaoencontrado = 0

                    incidente = find_element_by_id(driver, "incidente")

                    nome_processo = find_element_by_id(driver, "classe-numero-processo")

                    classe_extenso = find_element_by_xpath(
                        driver,
                        '//*[@id="texto-pagina-interna"]/div/div/div/div[2]/div[1]/div/div[1]',
                    )

                    titulo_processo = find_element_by_xpath(
                        driver, '//*[@id="texto-pagina-interna"]/div/div/div/div[1]'
                    )

                    if "Processo Físico" in document:
                        tipo_processo = "Físico"
                    elif "Processo Eletrônico" in document:
                        tipo_processo = "Eletrônico"
                    else:
                        tipo_processo = "NA"

                    liminar = []
                    if "bg-danger" in titulo_processo:
                        liminar0 = find_elements_by_class(driver, "bg-danger")
                        for item in liminar0:
                            liminar.append(item.text)
                    else:
                        liminar = []

                    try:
                        origem = find_element_by_xpath(
                            driver, '//*[@id="descricao-procedencia"]'
                        )
                        origem = dsl.clext(origem, ">", "<") if origem else "NA"
                    except Exception:
                        origem = "NA"

                    try:
                        relator = dsl.clext(document, "Relator(a): ", "<")
                    except Exception:
                        relator = "NA"

                    partes_tipo = find_elements_by_class(driver, "detalhe-parte")
                    partes_nome = find_elements_by_class(driver, "nome-parte")

                    partes_total = []
                    index = 0
                    primeiro_autor = "NA"
                    for n in range(len(partes_tipo)):
                        index = index + 1
                        tipo = partes_tipo[n].get_attribute("innerHTML")
                        nome_parte = partes_nome[n].get_attribute("innerHTML")
                        if index == 1:
                            primeiro_autor = nome_parte

                        parte_info = {"_index": index, "tipo": tipo, "nome": nome_parte}

                        partes_total.append(parte_info)

                    data_protocolo = dsl.clean(
                        find_element_by_xpath(
                            driver,
                            '//*[@id="informacoes-completas"]/div[2]/div[1]/div[2]/div[2]',
                        )
                    )

                    origem_orgao = dsl.clean(
                        find_element_by_xpath(
                            driver,
                            '//*[@id="informacoes-completas"]/div[2]/div[1]/div[2]/div[4]',
                        )
                    )

                    assuntos = find_element_by_xpath(
                        driver, '//*[@id="informacoes-completas"]/div[1]/div[2]'
                    ).split("<li>")[1:]
                    lista_assuntos = []

                    for assunto in assuntos:
                        lista_assuntos.append(dsl.clext(assunto, "", "</"))

                    # resumo = find_element_by_xpath(
                    #     driver,
                    #     "/html/body/div[1]/div[2]/section/div/div/div/div/div/div/div[2]/div[1]",
                    # )

                    andamentos = find_elements_by_class(driver, "andamento-item")
                    andamentos_lista = []
                    andamentos_decisórios = []
                    html_andamentos = []
                    for n in range(len(andamentos)):
                        index = len(andamentos) - n
                        andamento = andamentos[n]
                        html = andamento.get_attribute("innerHTML")

                        html_andamentos.append(html)

                        # if "andamento-invalido" in html:
                        #     and_tipo = "invalid"
                        # else:
                        #     and_tipo = "valid"

                        and_data = andamento.find_element(
                            By.CLASS_NAME, "andamento-data"
                        ).text
                        and_nome = andamento.find_element(
                            By.CLASS_NAME, "andamento-nome"
                        ).text
                        and_complemento = andamento.find_element(
                            By.CLASS_NAME, "col-md-9"
                        ).text

                        if html and "andamento-julgador badge bg-info" in html:
                            and_julgador = andamento.find_element(
                                By.CLASS_NAME, "andamento-julgador"
                            ).text
                        else:
                            and_julgador = "NA"

                        if html and "href" in html:
                            and_link = dsl.ext(html, 'href="', '"')
                            and_link = (
                                "https://portal.stf.jus.br/processos/"
                                + and_link.replace("amp;", "")
                            )
                        else:
                            and_link = "NA"

                        if html and "fa-file-alt" in html:
                            and_link_tipo = andamento.find_element(
                                By.CLASS_NAME, "fa-file-alt"
                            ).text
                        else:
                            and_link_tipo = "NA"

                        if html and "fa-download" in html:
                            and_link_tipo = andamento.find_element(
                                By.CLASS_NAME, "fa-download"
                            ).text
                        else:
                            and_link_tipo = "NA"

                        # Use tenacity retry for document downloads
                        try:
                            and_link_conteudo = retry_document_download(
                                and_link, and_link_tipo
                            )
                        except Exception as e:
                            logging.warning(
                                f"Failed to download document after retries: {e}"
                            )
                            and_link_conteudo = "Exception"

                        andamento_dados = {
                            "index": index,
                            "data": and_data,
                            "nome": and_nome,
                            "complemento": and_complemento,
                            "julgador": and_julgador,
                            "link": and_link,
                            "link_tipo": and_link_tipo,
                            "link_conteúdo": and_link_conteudo,
                        }

                        andamentos_lista.append(andamento_dados)
                        if and_julgador != "NA":
                            andamentos_decisórios.append(andamento_dados)

                    deslocamentos_info = driver.find_element(
                        By.XPATH, '//*[@id="deslocamentos"]'
                    )
                    deslocamentos = deslocamentos_info.find_elements(
                        By.CLASS_NAME, "lista-dados"
                    )
                    deslocamentos_lista = []
                    htmld = "NA"
                    for n in range(len(deslocamentos)):
                        index = len(deslocamentos) - n
                        deslocamento = deslocamentos[n]
                        htmld = deslocamento.get_attribute("innerHTML")

                        enviado = dsl.clext(htmld, '"processo-detalhes-bold">', "<")
                        recebido = dsl.clext(htmld, '"processo-detalhes">', "<")

                        if htmld and 'processo-detalhes bg-font-success">' in htmld:
                            data_recebido = dsl.ext(
                                htmld, 'processo-detalhes bg-font-success">', "<"
                            )
                        else:
                            data_recebido = "NA"

                        guia = dsl.clext(
                            htmld,
                            'text-right">\n                <span class="processo-detalhes">',
                            "<",
                        )

                        deslocamento_dados = {
                            "index": index,
                            "data_recebido": data_recebido,
                            "enviado por": enviado,
                            "recebido por": recebido,
                            "gruia": guia,
                        }

                        deslocamentos_lista.append(deslocamento_dados)

                    # Define os dados a gravar, criando uma lista com as variáveis
                    dados_a_gravar = [
                        incidente,
                        classe,
                        nome_processo,
                        classe_extenso,
                        tipo_processo,
                        liminar,
                        origem,
                        relator,
                        primeiro_autor,
                        len(partes_total),
                        dsl.js(partes_total),
                        data_protocolo,
                        origem_orgao,
                        lista_assuntos,
                        # resumo,
                        len(andamentos_lista),
                        dsl.js(andamentos_lista),
                        len(andamentos_decisórios),
                        dsl.js(andamentos_decisórios),
                        len(deslocamentos_lista),
                        dsl.js(deslocamentos_lista),
                    ]

                export_data(dados_a_gravar, out_file, save_to_csv, save_to_jsonl)


        except Exception as e:
            logging.error(f"Error processing {classe} {processo_num}: {e}")
            processonaoencontrado += 1


if __name__ == "__main__":
    typer.run(main)
