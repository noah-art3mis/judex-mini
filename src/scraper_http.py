"""
HTTP-only scraper for STF process pages.

Proof-of-concept replacement for the Selenium path. Replays what the
browser would do: resolve (classe, numero) -> incidente via the 302 from
listarProcessos.asp, GET detalhe.asp to establish session cookies, then
fetch each tab fragment directly (abaAndamentos.asp, abaPartes.asp, ...)
with the XHR headers that jQuery's .load() would set.

Currently implements andamentos only — other tabs are structurally
identical but require adapting the corresponding extract_* function to
take an HTML fragment instead of a driver handle.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.utils import html_cache

BASE = "https://portal.stf.jus.br/processos"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

TABS = (
    "abaInformacoes",
    "abaPartes",
    "abaAndamentos",
    "abaDecisoes",
    "abaDeslocamentos",
    "abaPeticoes",
    "abaRecursos",
    "abaPautas",
    "abaSessao",
)


@dataclass
class ProcessFetch:
    classe: str
    processo: int
    incidente: int
    detalhe_html: str
    tabs: dict[str, str]


def _new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": DEFAULT_UA})
    s.verify = False  # WSL sandbox lacks full CA bundle; site is public anyway
    return s


def resolve_incidente(session: requests.Session, classe: str, processo: int) -> Optional[int]:
    """Follow the listarProcessos 302 to extract the incidente id."""
    r = session.get(
        f"{BASE}/listarProcessos.asp",
        params={"classe": classe, "numeroProcesso": processo},
        allow_redirects=False,
        timeout=30,
    )
    loc = r.headers.get("Location", "")
    m = re.search(r"incidente=(\d+)", loc)
    if not m:
        logging.warning(f"{classe} {processo}: no incidente in redirect ({r.status_code} {loc!r})")
        return None
    return int(m.group(1))


def _decode(r: requests.Response) -> str:
    """STF serves UTF-8 without a charset; requests defaults to Latin-1 → mojibake."""
    r.encoding = "utf-8"
    return r.text


def fetch_detalhe(session: requests.Session, incidente: int) -> str:
    r = session.get(f"{BASE}/detalhe.asp", params={"incidente": incidente}, timeout=30)
    r.raise_for_status()
    return _decode(r)


def fetch_tab(session: requests.Session, incidente: int, tab: str) -> str:
    params = {"incidente": incidente}
    if tab == "abaAndamentos":
        params["imprimir"] = ""
    elif tab == "abaSessao":
        params["tema"] = ""
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE}/detalhe.asp?incidente={incidente}",
        "Accept": "text/html, */*; q=0.01",
    }
    r = session.get(f"{BASE}/{tab}.asp", params=params, headers=headers, timeout=30)
    r.raise_for_status()
    return _decode(r)


def fetch_process(
    classe: str,
    processo: int,
    *,
    use_cache: bool = True,
    max_workers: int = 8,
) -> Optional[ProcessFetch]:
    """Fetch detalhe + all tabs for one process. Caches each fragment on disk."""
    session = _new_session()

    incidente = resolve_incidente(session, classe, processo)
    if incidente is None:
        return None

    def cached_fetch(tab: str, fetcher) -> str:
        if use_cache:
            hit = html_cache.read(classe, processo, tab)
            if hit is not None:
                return hit
        html = fetcher()
        html_cache.write(classe, processo, tab, html)
        return html

    detalhe_html = cached_fetch("detalhe", lambda: fetch_detalhe(session, incidente))

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            tab: ex.submit(cached_fetch, tab, lambda t=tab: fetch_tab(session, incidente, t))
            for tab in TABS
        }
        tabs = {tab: f.result() for tab, f in futures.items()}

    return ProcessFetch(
        classe=classe,
        processo=processo,
        incidente=incidente,
        detalhe_html=detalhe_html,
        tabs=tabs,
    )


# ---------- extractor: andamentos from the abaAndamentos fragment ----------

from src.utils.text_utils import normalize_spaces


def _clean_nome(nome: str) -> str:
    nome = normalize_spaces(nome)
    if nome:
        nome = re.sub(r",\s*GUIA\s*N[ºOo0]?[^,]*$", "", nome, flags=re.IGNORECASE).strip()
    return nome


def extract_andamentos_http(fragment_html: str, base_url: str = "https://portal.stf.jus.br") -> list[dict]:
    """Parse the abaAndamentos.asp fragment into the same shape as extract_andamentos."""
    soup = BeautifulSoup(fragment_html, "lxml")
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
        complemento = normalize_spaces(complemento_tag.get_text()) if complemento_tag else None
        complemento = complemento or None

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
