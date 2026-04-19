"""Row-by-row table extractors.

Sister parsers for the tab fragments whose rows share HTML structure:
andamentos, deslocamentos, peticoes, recursos, pautas. `iter_lista_dados`
and the regex helpers live in `_shared`.

v6 (2026-04-18): every date field emits ISO 8601 directly. The raw
DD/MM/YYYY display string is no longer carried on the output. `index`
replaces `index_num`/`id`. `Recurso.tipo` replaces `Recurso.data`.
`Peticao.recebido_data` carries a full ISO datetime (with time-of-day).
`extract_pautas` is new.
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from judex.scraping.extraction._shared import (
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
    to_iso_datetime,
)
from judex.utils.text_utils import normalize_spaces


def _parse_andamento_item(item, *, base_url: str, index: int) -> dict:
    """Shared row parser for `abaAndamentos` + `abaPautas` (same HTML shape).

    Pautas rows don't carry anchors — the `link` field falls out as None
    there naturally. Extractor is kept pure (no list mutation) so the
    two callers share one code path.
    """
    data_tag = item.find(class_="andamento-data")
    data_raw = data_tag.get_text(strip=True) if data_tag else None

    nome_tag = item.find(class_="andamento-nome")
    nome = clean_nome(nome_tag.get_text(strip=True) if nome_tag else "")

    complemento_tag = item.find(class_="col-md-9")
    complemento = (
        normalize_spaces(complemento_tag.get_text()) if complemento_tag else None
    ) or None

    julgador_tag = item.find(class_="andamento-julgador")
    julgador = julgador_tag.get_text(strip=True) if julgador_tag else None

    anchor = item.find("a")
    link: Optional[dict] = None
    if anchor:
        href = anchor.get("href")
        anchor_text = anchor.get_text()
        tipo = (
            normalize_spaces(anchor_text).upper() or None
            if anchor_text
            else None
        )
        if href:
            url = (
                href if href.startswith("http")
                else f"{base_url}/processos/{href.replace('amp;', '')}"
            )
        else:
            url = None
        if url or tipo:
            link = {"tipo": tipo, "url": url, "text": None, "extractor": None}

    return {
        "index": index,
        "data": to_iso(data_raw),
        "nome": nome.upper(),
        "complemento": complemento,
        "julgador": julgador,
        "link": link,
    }


def extract_andamentos(
    andamentos_html: str, base_url: str = "https://portal.stf.jus.br"
) -> list[dict]:
    soup = BeautifulSoup(andamentos_html, "lxml")
    items = soup.find_all(class_="andamento-item")
    total = len(items)
    out: list[dict] = []
    for i, item in enumerate(items):
        index = total - i
        out.append(_parse_andamento_item(item, base_url=base_url, index=index))
    return out


def extract_pautas(pautas_html: str) -> list[dict]:
    """Parse the `abaPautas.asp` fragment.

    The HTML uses the same `andamento-item` scaffolding as
    `abaAndamentos`, but pauta rows carry no anchors. We reuse the
    andamento parser and drop the (always-None) link field to match
    the `Pauta` TypedDict.
    """
    soup = BeautifulSoup(pautas_html, "lxml")
    items = soup.find_all(class_="andamento-item")
    total = len(items)
    out: list[dict] = []
    for i, item in enumerate(items):
        index = total - i
        parsed = _parse_andamento_item(item, base_url="", index=index)
        parsed.pop("link", None)
        out.append(parsed)
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

        data_recebido_raw: Optional[str] = None
        if data_recebido_m:
            data_recebido_raw = (
                normalize_spaces(data_recebido_m.group(1))
                .replace("Recebido em ", "")
                .replace(" em ", "")
                .strip()
            )

        data_enviado_raw: Optional[str] = None
        if data_enviado_m:
            data_enviado_raw = (
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

        enviado_por: Optional[str] = None
        if basic_m:
            raw = normalize_spaces(basic_m.group(1))
            m = P_EM_DATE.search(raw)
            if m and data_enviado_raw is None:
                data_enviado_raw = m.group(1)
            enviado_por = strip_actor_boiler(raw, "Enviado por") or None

        recebido_por: Optional[str] = None
        if bold:
            raw = normalize_spaces(bold.group(1))
            m = P_EM_DATE.search(raw)
            if m and data_recebido_raw is None:
                data_recebido_raw = m.group(1)
            recebido_por = strip_actor_boiler(raw, "Recebido por") or None

        out.append(
            {
                "index": index,
                "guia": guia,
                "recebido_por": recebido_por,
                "data_recebido": to_iso(data_recebido_raw),
                "enviado_por": enviado_por,
                "data_enviado": to_iso(data_enviado_raw),
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

        data_raw = normalize_spaces(data_m.group(1)) if data_m else None
        if data_raw:
            data_raw = re.sub(r"^Peticionado em\s+", "", data_raw)
        petic_id = normalize_spaces(id_m.group(1)) if id_m else None
        recebido = normalize_spaces(recebido_m.group(1)) if recebido_m else None

        recebido_data_raw: Optional[str] = None
        recebido_por: Optional[str] = None
        if recebido:
            parts = recebido.split(" por ", 1)
            if len(parts) == 2:
                recebido_data_raw, recebido_por = parts[0].strip(), parts[1].strip()
            else:
                recebido_data_raw = recebido

        out.append(
            {
                "index": index,
                "id": petic_id,
                "data": to_iso(data_raw),
                "recebido_data": to_iso_datetime(recebido_data_raw),
                "recebido_por": recebido_por,
            }
        )
    return out


def extract_recursos(recursos_html: str) -> list[dict]:
    """v6: field renamed to `tipo` (was `data`). The value is a
    recurso-type label ("AG.REG. NA MEDIDA CAUTELAR NO HABEAS CORPUS"),
    not a date."""
    out: list[dict] = []
    for index, row in iter_lista_dados(recursos_html):
        m = P_DETAIL_BOLD.search(str(row))
        tipo = normalize_spaces(m.group(1)) if m else None
        out.append({"index": index, "tipo": tipo})
    return out
