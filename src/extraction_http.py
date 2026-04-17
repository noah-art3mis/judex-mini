"""
Fragment-based extractors for the HTTP scraper path.

Each function takes either a BeautifulSoup (when the orchestrator has
already parsed the containing fragment) or a raw HTML string (for
self-contained tab fragments that are only parsed once anyway).

Routing summary (which fragment each reads):
    detalhe.asp       → incidente, numero_unico, classe, relator, meio,
                        publicidade, badges
    abaInformacoes    → assuntos, data_protocolo, orgao_origem,
                        numero_origem, origem, volumes, folhas, apensos
    abaPartes         → partes (primeiro_autor derives from partes)
    abaAndamentos     → andamentos
    abaDeslocamentos  → deslocamentos
    abaPeticoes       → peticoes
    abaRecursos       → recursos

(sessao_virtual is handled in src/extraction_http_sessao.py — its tab
fragment is a JS template, so the orchestrator fetches the JSON
endpoints the template would have called.)
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from src.extraction._shared import (
    P_DETAIL_BASIC,
    P_DETAIL_BOLD,
    P_DETAIL_INFO,
    P_DETAIL_SUCCESS,
    P_EM_DATE,
    P_GUIA_CELL,
    P_RECEBIDO_EM,
    clean_nome,
    extract_partes_from_soup,
    iter_lista_dados,
    strip_actor_boiler,
)

# Direct reuse of pure-soup Selenium extractors — they already take a
# BeautifulSoup, no need to reimplement.
from src.legal_vocab import AUTHOR_PARTY_TIPOS, VERDICT_PATTERNS
from src.extraction.extract_classe import extract_classe
from src.extraction.extract_meio import extract_meio
from src.extraction.extract_numero_unico import extract_numero_unico
from src.extraction.extract_publicidade import extract_publicidade
from src.extraction.extract_relator import extract_relator
from src.utils.text_utils import normalize_spaces


# ---------- detalhe.asp extractors (take BeautifulSoup) ----------


def extract_incidente(detalhe_soup: BeautifulSoup) -> Optional[int]:
    el = detalhe_soup.find(id="incidente")
    if el is None:
        return None
    value = el.get("value")
    if value and str(value).isdigit():
        return int(value)
    return None


def extract_badges(detalhe_soup: BeautifulSoup) -> list[str]:
    out: list[str] = []
    for el in detalhe_soup.select(".badge"):
        text = el.get_text(" ", strip=True)
        upper = text.upper()
        if "MAIOR DE 60 ANOS" in upper or "DOENÇA GRAVE" in upper or "DOENCA GRAVE" in upper:
            out.append(text)
    return out


# ---------- abaInformacoes extractors (take BeautifulSoup) ----------


def _labeled_value(soup: BeautifulSoup, label: str) -> Optional[str]:
    target = label.strip().rstrip(":")
    for bold in soup.select(".processo-detalhes-bold"):
        text = normalize_spaces(bold.get_text(strip=True)).rstrip(":")
        if text == target:
            sib = bold.find_next_sibling("div")
            if sib is None:
                return None
            return normalize_spaces(sib.get_text(strip=True)) or None
    return None


def extract_assuntos(info_soup: BeautifulSoup) -> list[str]:
    wrapper = info_soup.select_one(".informacoes__assunto") or info_soup
    out: list[str] = []
    for li in wrapper.find_all("li"):
        text = normalize_spaces(li.get_text(strip=True))
        if text:
            out.append(text)
    return out


def extract_data_protocolo(info_soup: BeautifulSoup) -> Optional[str]:
    return _labeled_value(info_soup, "Data de Protocolo")


def extract_orgao_origem(info_soup: BeautifulSoup) -> Optional[str]:
    span = info_soup.find(id="orgao-procedencia")
    if span:
        return normalize_spaces(span.get_text(strip=True)) or None
    return _labeled_value(info_soup, "Órgão de Origem")


def extract_origem(info_soup: BeautifulSoup) -> Optional[str]:
    span = info_soup.find(id="descricao-procedencia")
    if span:
        return normalize_spaces(span.get_text(strip=True)) or None
    return _labeled_value(info_soup, "Origem")


def extract_numero_origem(info_soup: BeautifulSoup) -> Optional[list[int]]:
    val = _labeled_value(info_soup, "Número de Origem")
    if not val:
        return None
    try:
        return [int(val)]
    except ValueError:
        return None


def _quadro_value(info_soup: BeautifulSoup, label: str) -> Optional[int]:
    target = label.strip().upper()
    for box in info_soup.select(".processo-quadro"):
        rot = box.select_one(".rotulo")
        if not rot:
            continue
        if target in rot.get_text(strip=True).upper():
            num = box.select_one(".numero")
            if not num:
                return None
            text = num.get_text(strip=True)
            return int(text) if text.isdigit() else None
    return None


def extract_volumes(info_soup: BeautifulSoup) -> Optional[int]:
    return _quadro_value(info_soup, "VOLUME")


def extract_folhas(info_soup: BeautifulSoup) -> Optional[int]:
    return _quadro_value(info_soup, "FOLHA")


def extract_apensos(info_soup: BeautifulSoup) -> Optional[int]:
    return _quadro_value(info_soup, "APENSO")


# ---------- abaPartes ----------


def extract_partes(partes_html: str) -> list[dict]:
    """Mirrors Selenium which reads from #resumo-partes (populated with #partes-resumidas)."""
    soup = BeautifulSoup(partes_html, "lxml")
    container = soup.find(id="partes-resumidas") or soup
    return extract_partes_from_soup(container)


def extract_primeiro_autor(partes: list[dict]) -> Optional[str]:
    for parte in partes:
        if parte.get("tipo", "").startswith(AUTHOR_PARTY_TIPOS):
            return parte.get("nome")
    return None


def derive_outcome(item: dict) -> Optional[str]:
    """Derive a coarse outcome label from voto_relator + andamentos.

    See `src.legal_vocab.VERDICT_PATTERNS` for the full vocabulary.
    Returns None for pending cases or when no pattern matches.
    """
    # 1. sessao_virtual: check the LAST session's voto_relator text.
    #    A later session overrides any earlier ones.
    sv = item.get("sessao_virtual") or []
    if isinstance(sv, list) and sv:
        last = sv[-1]
        if isinstance(last, dict):
            voto = (last.get("voto_relator") or "").strip()
            if voto:
                outcome = _match_verdict(voto)
                if outcome is not None:
                    return outcome

    # 2. andamentos fallback: scan nome+complemento for verdict phrases.
    for a in item.get("andamentos") or []:
        if not isinstance(a, dict):
            continue
        blob = f"{a.get('nome', '')}\n{a.get('complemento', '') or ''}"
        outcome = _match_verdict(blob)
        if outcome is not None:
            return outcome

    return None


def _match_verdict(text: str) -> Optional[str]:
    for pattern, label in VERDICT_PATTERNS:
        if pattern.search(text):
            return label
    return None


# ---------- abaAndamentos ----------


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
                link = href if href.startswith("http") else f"{base_url}/processos/{href.replace('amp;', '')}"
            text = anchor.get_text()
            if text:
                link_descricao = normalize_spaces(text).upper() or None

        out.append(
            {
                "index_num": index,
                "data": data,
                "nome": nome.upper(),
                "complemento": complemento,
                "julgador": julgador,
                "link_descricao": link_descricao,
                "link": link,
            }
        )
    return out


# ---------- abaDeslocamentos ----------


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
                "enviado_por": enviado_por,
                "data_enviado": data_enviado,
            }
        )
    return out


# ---------- abaPeticoes ----------


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
                "recebido_data": recebido_data,
                "recebido_por": recebido_por,
            }
        )
    return out


# ---------- abaRecursos ----------


def extract_recursos(recursos_html: str) -> list[dict]:
    out: list[dict] = []
    for index, row in iter_lista_dados(recursos_html):
        m = P_DETAIL_BOLD.search(str(row))
        data = normalize_spaces(m.group(1)) if m else None
        out.append({"id": index, "data": data})  # GT schema uses `id`, not `index`
    return out


# abaSessao is handled separately in src.extraction_http_sessao —
# its JS template fires two JSON endpoints on sistemas.stf.jus.br, so
# orchestration (not just fragment parsing) is needed.


# Re-exports so orchestrators import from one place.
__all__ = [
    "extract_incidente",
    "extract_numero_unico",
    "extract_classe",
    "extract_relator",
    "extract_meio",
    "extract_publicidade",
    "extract_badges",
    "extract_assuntos",
    "extract_data_protocolo",
    "extract_orgao_origem",
    "extract_origem",
    "extract_numero_origem",
    "extract_volumes",
    "extract_folhas",
    "extract_apensos",
    "extract_partes",
    "extract_primeiro_autor",
    "extract_andamentos",
    "extract_deslocamentos",
    "extract_peticoes",
    "extract_recursos",
    "derive_outcome",
]
