"""
HTTP-only scraper for STF process pages.

Replays what the browser would do: resolve (classe, numero) -> incidente
via the 302 from listarProcessos.asp, GET detalhe.asp to establish
session cookies, then fetch each tab fragment directly
(abaAndamentos.asp, abaPartes.asp, ...) with the XHR headers that
jQuery's .load() would set.

Fragment parsing lives in src/extraction_http.py — this module only
handles fetching, caching, and the end-to-end orchestration that
mirrors extract_processo() from the Selenium path.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src import extraction_http as ex
from src.data.types import StfItem
from src.utils import html_cache

BASE = "https://portal.stf.jus.br/processos"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

DETALHE = "detalhe"
TAB_INFORMACOES = "abaInformacoes"
TAB_PARTES = "abaPartes"
TAB_ANDAMENTOS = "abaAndamentos"
TAB_DECISOES = "abaDecisoes"
TAB_DESLOCAMENTOS = "abaDeslocamentos"
TAB_PETICOES = "abaPeticoes"
TAB_RECURSOS = "abaRecursos"
TAB_PAUTAS = "abaPautas"
TAB_SESSAO = "abaSessao"

TABS: tuple[str, ...] = (
    TAB_INFORMACOES,
    TAB_PARTES,
    TAB_ANDAMENTOS,
    TAB_DECISOES,
    TAB_DESLOCAMENTOS,
    TAB_PETICOES,
    TAB_RECURSOS,
    TAB_PAUTAS,
    TAB_SESSAO,
)

# Per-process tab concurrency. Tabs fan out fast enough in practice that
# a small pool is plenty and stays polite under STF's progressive rate
# limiting.
_TAB_WORKERS = 4


@dataclass
class ProcessFetch:
    incidente: int
    detalhe_html: str
    tabs: dict[str, str]


def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": DEFAULT_UA})
    s.verify = False  # WSL sandbox lacks full CA bundle; site is public anyway
    return s


def _decode(r: requests.Response) -> str:
    """STF serves UTF-8 without a charset; requests defaults to Latin-1 → mojibake."""
    r.encoding = "utf-8"
    return r.text


def resolve_incidente(
    session: requests.Session, classe: str, processo: int
) -> Optional[int]:
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
        logging.warning(
            f"{classe} {processo}: no incidente in redirect ({r.status_code} {loc!r})"
        )
        return None
    return int(m.group(1))


def fetch_detalhe(session: requests.Session, incidente: int) -> str:
    r = session.get(f"{BASE}/detalhe.asp", params={"incidente": incidente}, timeout=30)
    r.raise_for_status()
    return _decode(r)


def fetch_tab(session: requests.Session, incidente: int, tab: str) -> str:
    params: dict = {"incidente": incidente}
    if tab == TAB_ANDAMENTOS:
        params["imprimir"] = ""
    elif tab == TAB_SESSAO:
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
    session: Optional[requests.Session] = None,
) -> Optional[ProcessFetch]:
    """Fetch detalhe + all tabs for one process. Caches fragments + incidente on disk."""
    owns_session = session is None
    if session is None:
        session = new_session()

    try:
        incidente: Optional[int] = (
            html_cache.read_incidente(classe, processo) if use_cache else None
        )
        if incidente is None:
            incidente = resolve_incidente(session, classe, processo)
            if incidente is None:
                return None
            html_cache.write_incidente(classe, processo, incidente)

        def cached(tab: str, fetcher) -> str:
            if use_cache:
                hit = html_cache.read(classe, processo, tab)
                if hit is not None:
                    return hit
            html = fetcher()
            html_cache.write(classe, processo, tab, html)
            return html

        detalhe_html = cached(DETALHE, partial(fetch_detalhe, session, incidente))

        with ThreadPoolExecutor(max_workers=_TAB_WORKERS) as pool:
            futures = {
                tab: pool.submit(cached, tab, partial(fetch_tab, session, incidente, tab))
                for tab in TABS
            }
            tabs = {tab: f.result() for tab, f in futures.items()}

        return ProcessFetch(incidente=incidente, detalhe_html=detalhe_html, tabs=tabs)
    finally:
        if owns_session:
            session.close()


def scrape_processo_http(
    classe: str,
    processo: int,
    *,
    use_cache: bool = True,
    session: Optional[requests.Session] = None,
) -> Optional[StfItem]:
    """Full-process scrape via HTTP. Returns the same StfItem shape as the Selenium path."""
    fetched = fetch_process(classe, processo, use_cache=use_cache, session=session)
    if fetched is None:
        return None

    detalhe_soup = BeautifulSoup(fetched.detalhe_html, "lxml")
    info_soup = BeautifulSoup(fetched.tabs.get(TAB_INFORMACOES, ""), "lxml")

    partes = ex.extract_partes(fetched.tabs.get(TAB_PARTES, ""))

    return StfItem(
        incidente=fetched.incidente,
        classe=classe,
        processo_id=processo,
        numero_unico=ex.extract_numero_unico(detalhe_soup),
        meio=ex.extract_meio(detalhe_soup),
        publicidade=ex.extract_publicidade(detalhe_soup),
        badges=ex.extract_badges(detalhe_soup),
        assuntos=ex.extract_assuntos(info_soup),
        data_protocolo=ex.extract_data_protocolo(info_soup),
        orgao_origem=ex.extract_orgao_origem(info_soup),
        origem=ex.extract_origem(info_soup),
        numero_origem=ex.extract_numero_origem(info_soup),
        volumes=ex.extract_volumes(info_soup),
        folhas=ex.extract_folhas(info_soup),
        apensos=ex.extract_apensos(info_soup),
        relator=ex.extract_relator(detalhe_soup),
        primeiro_autor=ex.extract_primeiro_autor(partes),
        partes=partes,
        andamentos=ex.extract_andamentos(fetched.tabs.get(TAB_ANDAMENTOS, "")),
        sessao_virtual=ex.extract_sessao_virtual(fetched.tabs.get(TAB_SESSAO, "")),
        deslocamentos=ex.extract_deslocamentos(fetched.tabs.get(TAB_DESLOCAMENTOS, "")),
        peticoes=ex.extract_peticoes(fetched.tabs.get(TAB_PETICOES, "")),
        recursos=ex.extract_recursos(fetched.tabs.get(TAB_RECURSOS, "")),
        pautas=[],
        status=200,
        extraido=datetime.now().isoformat(),
        html=fetched.detalhe_html,
    )
