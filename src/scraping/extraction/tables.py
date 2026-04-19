"""Row-by-row table extractors.

Four sister parsers that all iterate the same `.lista-dados` rows from
their respective tab fragments: andamentos, deslocamentos, peticoes,
recursos. `iter_lista_dados` and the regex helpers live in `_shared`.
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from src.scraping.extraction._shared import (
    P_DETAIL_BASIC,
    P_DETAIL_BOLD,
    P_DETAIL_INFO,
    P_DETAIL_SUCCESS,
    P_EM_DATE,
    P_GUIA_CELL,
    P_RECEBIDO_EM,
    clean_nome,
    iter_lista_dados,
    strip_actor_boiler,
    to_iso,
)
from src.utils.text_utils import normalize_spaces


def extract_andamentos(
    andamentos_html: str, base_url: str = "https://portal.stf.jus.br"
) -> list[dict]:
    soup = BeautifulSoup(andamentos_html, "lxml")
    items = soup.find_all(class_="andamento-item")
    total = len(items)
    out: list[dict] = []
    for i, item in enumerate(items):
        index = total - i

        data_tag = item.find(class_="andamento-data")
        data = data_tag.get_text(strip=True) if data_tag else None

        nome_tag = item.find(class_="andamento-nome")
        nome = clean_nome(nome_tag.get_text(strip=True) if nome_tag else "")

        complemento_tag = item.find(class_="col-md-9")
        complemento = (
            normalize_spaces(complemento_tag.get_text()) if complemento_tag else None
        ) or None

        julgador_tag = item.find(class_="andamento-julgador")
        julgador = julgador_tag.get_text(strip=True) if julgador_tag else None

        anchor = item.find("a")
        link = None
        link_descricao = None
        if anchor:
            href = anchor.get("href")
            if href:
                url = href if href.startswith("http") else f"{base_url}/processos/{href.replace('amp;', '')}"
                # text is populated later by an OCR/pypdf enrichment pass;
                # keeping it None here means the scrape output is structurally
                # complete without blocking on PDF downloads.
                link = {"url": url, "text": None}
            text = anchor.get_text()
            if text:
                link_descricao = normalize_spaces(text).upper() or None

        out.append(
            {
                "index_num": index,
                "data": data,
                "data_iso": to_iso(data),
                "nome": nome.upper(),
                "complemento": complemento,
                "julgador": julgador,
                "link_descricao": link_descricao,
                "link": link,
            }
        )
    return out


def extract_deslocamentos(deslocamentos_html: str) -> list[dict]:
    out: list[dict] = []
    for index, row in iter_lista_dados(deslocamentos_html):
        html = str(row)

        bold = P_DETAIL_BOLD.search(html)
        data_recebido_m = P_DETAIL_SUCCESS.search(html)
        data_enviado_m = P_DETAIL_INFO.search(html)
        basic_m = P_DETAIL_BASIC.search(html)
        guia_m = P_GUIA_CELL.search(html)

        data_recebido = None
        if data_recebido_m:
            data_recebido = (
                normalize_spaces(data_recebido_m.group(1))
                .replace("Recebido em ", "")
                .replace(" em ", "")
                .strip()
            )

        data_enviado = None
        if data_enviado_m:
            data_enviado = (
                normalize_spaces(data_enviado_m.group(1))
                .replace("Enviado em ", "")
                .replace(" em ", "")
                .strip()
            )

        guia = ""
        if guia_m:
            guia = (
                normalize_spaces(guia_m.group(1))
                .replace("Guia: ", "")
                .replace("Guia ", "")
                .replace("Nº ", "")
                .strip()
            )

        enviado_por = None
        if basic_m:
            raw = normalize_spaces(basic_m.group(1))
            m = P_EM_DATE.search(raw)
            if m and data_enviado is None:
                data_enviado = m.group(1)
            enviado_por = strip_actor_boiler(raw, "Enviado por") or None

        recebido_por = None
        if bold:
            raw = normalize_spaces(bold.group(1))
            m = P_EM_DATE.search(raw)
            if m and data_recebido is None:
                data_recebido = m.group(1)
            recebido_por = strip_actor_boiler(raw, "Recebido por") or None

        out.append(
            {
                "index_num": index,
                "guia": guia,
                "recebido_por": recebido_por,
                "data_recebido": data_recebido,
                "data_recebido_iso": to_iso(data_recebido),
                "enviado_por": enviado_por,
                "data_enviado": data_enviado,
                "data_enviado_iso": to_iso(data_enviado),
            }
        )
    return out


def extract_peticoes(peticoes_html: str) -> list[dict]:
    out: list[dict] = []
    for index, row in iter_lista_dados(peticoes_html):
        html = str(row)

        data_m = P_DETAIL_BASIC.search(html)
        id_m = P_DETAIL_BOLD.search(html)
        recebido_m = P_RECEBIDO_EM.search(html)

        data = normalize_spaces(data_m.group(1)) if data_m else None
        if data:
            data = re.sub(r"^Peticionado em\s+", "", data)
        petic_id = normalize_spaces(id_m.group(1)) if id_m else None
        recebido = normalize_spaces(recebido_m.group(1)) if recebido_m else None

        recebido_data: Optional[str] = None
        recebido_por: Optional[str] = None
        if recebido:
            parts = recebido.split(" por ", 1)
            if len(parts) == 2:
                recebido_data, recebido_por = parts[0].strip(), parts[1].strip()
            else:
                recebido_data = recebido

        out.append(
            {
                "index": index,
                "id": petic_id,
                "data": data,
                "data_iso": to_iso(data),
                "recebido_data": recebido_data,
                "recebido_data_iso": to_iso(recebido_data),
                "recebido_por": recebido_por,
            }
        )
    return out


def extract_recursos(recursos_html: str) -> list[dict]:
    # NB: `data` here is a recurso-type label ("AG.REG. NA MEDIDA
    # CAUTELAR NO HABEAS CORPUS"), not a date — historical misnaming.
    # No *_iso companion.
    out: list[dict] = []
    for index, row in iter_lista_dados(recursos_html):
        m = P_DETAIL_BOLD.search(str(row))
        data = normalize_spaces(m.group(1)) if m else None
        out.append({"id": index, "data": data})
    return out
