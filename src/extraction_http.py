"""
Fragment-based extractors for the HTTP scraper path.

Each function takes a single HTML string (either the full detalhe.asp
document or a specific aba*.asp fragment) and returns the value that the
corresponding Selenium extract_* function returns, with output shape held
stable so downstream consumers don't change.

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
    abaSessao         → sessao_virtual (LIMITATION: the session voting
                        data is rendered client-side from a separate
                        JSON API; returns [] for now, see TODO.)
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from src.utils.text_utils import normalize_spaces


# ---------- shared helpers ----------


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _labeled_value(soup: BeautifulSoup, label: str) -> Optional[str]:
    """
    Find a <div class="...processo-detalhes-bold...">LABEL:</div> and
    return the text of the next-sibling value div. Used throughout
    abaInformacoes where the structure is a flat label/value sequence.
    """
    target = label.strip().rstrip(":")
    for bold in soup.select(".processo-detalhes-bold"):
        text = normalize_spaces(bold.get_text(strip=True)).rstrip(":")
        if text == target:
            sib = bold.find_next_sibling("div")
            if sib is None:
                return None
            return normalize_spaces(sib.get_text(strip=True)) or None
    return None


# ---------- detalhe.asp extractors ----------


def extract_incidente(detalhe_html: str) -> Optional[int]:
    soup = _soup(detalhe_html)
    el = soup.find(id="incidente")
    if el is None:
        return None
    value = el.get("value")
    if value and str(value).isdigit():
        return int(value)
    return None


def extract_numero_unico(detalhe_html: str) -> Optional[str]:
    soup = _soup(detalhe_html)
    el = soup.select_one(".processo-rotulo")
    if not el:
        return None
    text = el.get_text(" ", strip=True)
    if "Número Único:" not in text:
        return None
    value = text.split("Número Único:", 1)[1].strip()
    if not value or value.lower().startswith("sem número único"):
        return None
    return value


def extract_classe(detalhe_html: str) -> Optional[str]:
    soup = _soup(detalhe_html)
    for div in soup.select(".processo-dados"):
        text = div.get_text(" ", strip=True)
        if text.startswith("Classe:"):
            return text.split(":", 1)[1].strip() or None
    return None


def extract_relator(detalhe_html: str) -> Optional[str]:
    soup = _soup(detalhe_html)
    for div in soup.select(".processo-dados"):
        text = div.get_text(" ", strip=True)
        if text.startswith("Relator(a):"):
            relator = normalize_spaces(text.split(":", 1)[1])
            if relator.startswith("MIN. "):
                relator = relator[5:]
            return relator or None
    return None


def _badges(detalhe_html: str) -> list[str]:
    soup = _soup(detalhe_html)
    return [b.get_text(" ", strip=True) for b in soup.select(".badge")]


def extract_meio(detalhe_html: str) -> Optional[str]:
    for b in _badges(detalhe_html):
        if "Físico" in b:
            return "FISICO"
        if "Eletrônico" in b:
            return "ELETRONICO"
    return None


def extract_publicidade(detalhe_html: str) -> Optional[str]:
    for b in _badges(detalhe_html):
        upper = b.upper()
        if "SIGILOSO" in upper:
            return "SIGILOSO"
        if "PÚBLICO" in upper or "PUBLICO" in upper:
            return "PUBLICO"
    return None


def extract_badges(detalhe_html: str) -> list[str]:
    out: list[str] = []
    for text in _badges(detalhe_html):
        upper = text.upper()
        if "MAIOR DE 60 ANOS" in upper or "DOENÇA GRAVE" in upper or "DOENCA GRAVE" in upper:
            out.append(text)
    return out


# ---------- abaInformacoes extractors ----------


def extract_assuntos(informacoes_html: str) -> list[str]:
    soup = _soup(informacoes_html)
    wrapper = soup.select_one(".informacoes__assunto") or soup
    out: list[str] = []
    for li in wrapper.find_all("li"):
        text = normalize_spaces(li.get_text(strip=True))
        if text:
            out.append(text)
    return out


def extract_data_protocolo(informacoes_html: str) -> Optional[str]:
    return _labeled_value(_soup(informacoes_html), "Data de Protocolo")


def extract_orgao_origem(informacoes_html: str) -> Optional[str]:
    soup = _soup(informacoes_html)
    span = soup.find(id="orgao-procedencia")
    if span:
        return normalize_spaces(span.get_text(strip=True)) or None
    return _labeled_value(soup, "Órgão de Origem")


def extract_origem(informacoes_html: str) -> Optional[str]:
    soup = _soup(informacoes_html)
    span = soup.find(id="descricao-procedencia")
    if span:
        return normalize_spaces(span.get_text(strip=True)) or None
    return _labeled_value(soup, "Origem")


def extract_numero_origem(informacoes_html: str) -> Optional[list[int]]:
    val = _labeled_value(_soup(informacoes_html), "Número de Origem")
    if not val:
        return None
    try:
        return [int(val)]
    except ValueError:
        return None


def _quadro_value(informacoes_html: str, label: str) -> Optional[int]:
    soup = _soup(informacoes_html)
    target = label.strip().upper()
    for box in soup.select(".processo-quadro"):
        rot = box.select_one(".rotulo")
        if not rot:
            continue
        rot_text = rot.get_text(strip=True).upper()
        if target in rot_text:
            num = box.select_one(".numero")
            if not num:
                return None
            text = num.get_text(strip=True)
            if text.isdigit():
                return int(text)
            return None
    return None


def extract_volumes(informacoes_html: str) -> Optional[int]:
    return _quadro_value(informacoes_html, "VOLUME")


def extract_folhas(informacoes_html: str) -> Optional[int]:
    return _quadro_value(informacoes_html, "FOLHA")


def extract_apensos(informacoes_html: str) -> Optional[int]:
    return _quadro_value(informacoes_html, "APENSO")


# ---------- abaPartes ----------


def extract_partes(partes_html: str) -> list[dict]:
    """
    Parse abaPartes's #partes-resumidas block into a list of {index, tipo, nome}.

    Deliberately mirrors the Selenium extractor, which reads the
    #resumo-partes container on detalhe.asp (populated by jQuery from
    #partes-resumidas). #todas-partes carries a longer list including
    amici curiae and additional advogados; consumers expect the short
    list, so we match that.
    """
    soup = _soup(partes_html)
    container = soup.find(id="partes-resumidas") or soup
    # Flat list of divs alternating [tipo, nome, tipo, nome, ...]
    cells = container.select("div[class*='processo-partes']")
    out: list[dict] = []
    for i in range(0, len(cells) - 1, 2):
        tipo = normalize_spaces(cells[i].get_text(strip=True))
        nome = normalize_spaces(cells[i + 1].get_text(strip=True))
        if not tipo or not nome:
            continue
        out.append({"index": len(out) + 1, "tipo": tipo, "nome": nome})
    return out


def extract_primeiro_autor(partes: list[dict]) -> Optional[str]:
    for parte in partes:
        if parte.get("tipo", "").startswith(("RECTE", "REQTE", "AUTOR")):
            return parte.get("nome")
    return None


# ---------- abaAndamentos ----------


def _clean_nome(nome: str) -> str:
    nome = normalize_spaces(nome)
    if nome:
        nome = re.sub(r",\s*GUIA\s*N[ºOo0]?[^,]*$", "", nome, flags=re.IGNORECASE).strip()
    return nome


def extract_andamentos(andamentos_html: str, base_url: str = "https://portal.stf.jus.br") -> list[dict]:
    soup = _soup(andamentos_html)
    items = soup.find_all(class_="andamento-item")
    total = len(items)
    out: list[dict] = []
    for i, item in enumerate(items):
        index = total - i

        data_tag = item.find(class_="andamento-data")
        data = data_tag.get_text(strip=True) if data_tag else None

        nome_tag = item.find(class_="andamento-nome")
        nome = _clean_nome(nome_tag.get_text(strip=True) if nome_tag else "")

        complemento_tag = item.find(class_="col-md-9")
        complemento_raw = complemento_tag.get_text() if complemento_tag else ""
        complemento = normalize_spaces(complemento_raw) or None

        julgador_tag = item.find(class_="andamento-julgador")
        julgador = julgador_tag.get_text(strip=True) if julgador_tag else None

        anchor = item.find("a")
        link = None
        link_descricao = None
        if anchor:
            href = anchor.get("href")
            if href:
                if href.startswith("http"):
                    link = href
                else:
                    link = f"{base_url}/processos/{href.replace('amp;', '')}"
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


_P_ENVIADO_BOLD = re.compile(r'"processo-detalhes-bold">([^<]+)')
_P_RECEBIDO_BG = re.compile(r'processo-detalhes bg-font-success">([^<]+)')
_P_ENVIADO_BG = re.compile(r'processo-detalhes bg-font-info">([^<]+)')
_P_RECEBIDO_TEXT = re.compile(r'"processo-detalhes">([^<]+)')
_P_GUIA = re.compile(r'text-right">\s*<span class="processo-detalhes">([^<]+)')
_P_EM_DATE = re.compile(r"em (\d{2}/\d{2}/\d{4})")


def _strip_boiler(text: str, prefix: str) -> str:
    t = re.sub(rf"^{prefix} ", "", text)
    t = re.sub(r" em \d{2}/\d{2}/\d{4}$", "", t)
    return t.strip()


def extract_deslocamentos(deslocamentos_html: str) -> list[dict]:
    soup = _soup(deslocamentos_html)
    rows = soup.select(".lista-dados")
    total = len(rows)
    out: list[dict] = []
    for i, row in enumerate(rows):
        index = total - i
        html = str(row)

        enviado_bold = _P_ENVIADO_BOLD.search(html)
        data_recebido_m = _P_RECEBIDO_BG.search(html)
        data_enviado_m = _P_ENVIADO_BG.search(html)
        recebido_text_m = _P_RECEBIDO_TEXT.search(html)
        guia_m = _P_GUIA.search(html)

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
        if recebido_text_m:
            raw = normalize_spaces(recebido_text_m.group(1))
            m = _P_EM_DATE.search(raw)
            if m and data_enviado is None:
                data_enviado = m.group(1)
            enviado_por = _strip_boiler(raw, "Enviado por") or None

        recebido_por = None
        if enviado_bold:
            raw = normalize_spaces(enviado_bold.group(1))
            m = _P_EM_DATE.search(raw)
            if m and data_recebido is None:
                data_recebido = m.group(1)
            recebido_por = _strip_boiler(raw, "Recebido por") or None

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


_P_DET_INFO = re.compile(r'processo-detalhes bg-font-info">([^<]+)')
_P_DET_BOLD = re.compile(r'processo-detalhes-bold">([^<]+)')
_P_DET_BASIC = re.compile(r'processo-detalhes">([^<]+)')
_P_RECEBIDO_EM = re.compile(r"Recebido em ([^<]+)")


def extract_peticoes(peticoes_html: str) -> list[dict]:
    soup = _soup(peticoes_html)
    rows = soup.select(".lista-dados")
    out: list[dict] = []
    for i, row in enumerate(rows):
        index = len(rows) - i
        html = str(row)

        data_m = _P_DET_BASIC.search(html)
        id_m = _P_DET_BOLD.search(html)
        recebido_m = _P_RECEBIDO_EM.search(html)

        data = normalize_spaces(data_m.group(1)) if data_m else None
        if data:
            data = re.sub(r"^Peticionado em\s+", "", data)
        petic_id = normalize_spaces(id_m.group(1)) if id_m else None
        recebido = normalize_spaces(recebido_m.group(1)) if recebido_m else None

        recebido_data = None
        recebido_por = None
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
    soup = _soup(recursos_html)
    rows = soup.select(".lista-dados")
    out: list[dict] = []
    for i, row in enumerate(rows):
        index = len(rows) - i
        html = str(row)
        m = _P_DET_BOLD.search(html)
        data = normalize_spaces(m.group(1)) if m else None
        # Ground-truth schema uses `id` here, not `index`.
        out.append({"id": index, "data": data})
    return out


# ---------- abaSessao ----------


def extract_sessao_virtual(sessao_html: str) -> list[dict]:
    """
    LIMITATION: The 'Tema' branch of sessao_virtual is rendered client-side
    from https://sistemas.stf.jus.br/repgeral/votacao?tema= (a separate
    JSON API) and the 'Sessão' branch requires collapse-expand click
    simulation. Neither is present as static HTML in the abaSessao
    fragment. Returning [] for now — to port, either call the JSON API
    directly or parse any server-rendered julgamento-item blocks that
    already contain data without requiring interaction.
    """
    return []


# ---------- liminar (derived from titulo) ----------


def extract_liminar(titulo_processo: Optional[str]) -> list[dict]:
    if titulo_processo and any(
        kw in titulo_processo.upper() for kw in ("LIMINAR", "TUTELA")
    ):
        return [{"tipo": "liminar", "descricao": titulo_processo}]
    return []
