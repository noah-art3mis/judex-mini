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
from typing import Optional

import requests

from src import extraction_http as ex
from src.data.types import StfItem
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


def _decode(r: requests.Response) -> str:
    """STF serves UTF-8 without a charset; requests defaults to Latin-1 → mojibake."""
    r.encoding = "utf-8"
    return r.text


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

    with ThreadPoolExecutor(max_workers=max_workers) as ex_pool:
        futures = {
            tab: ex_pool.submit(cached_fetch, tab, lambda t=tab: fetch_tab(session, incidente, t))
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


def scrape_processo_http(
    classe: str,
    processo: int,
    *,
    use_cache: bool = True,
) -> Optional[StfItem]:
    """Full-process scrape via HTTP. Returns the same StfItem shape as the Selenium path."""
    fetched = fetch_process(classe, processo, use_cache=use_cache)
    if fetched is None:
        return None

    detalhe = fetched.detalhe_html
    info_html = fetched.tabs.get("abaInformacoes", "")

    partes = ex.extract_partes(fetched.tabs.get("abaPartes", ""))

    item: StfItem = {
        "incidente": fetched.incidente,
        "classe": classe,
        "processo_id": processo,
        "numero_unico": ex.extract_numero_unico(detalhe),
        "meio": ex.extract_meio(detalhe),  # type: ignore[typeddict-item]
        "publicidade": ex.extract_publicidade(detalhe),  # type: ignore[typeddict-item]
        "badges": ex.extract_badges(detalhe),
        "assuntos": ex.extract_assuntos(info_html),
        "data_protocolo": ex.extract_data_protocolo(info_html),  # type: ignore[typeddict-item]
        "orgao_origem": ex.extract_orgao_origem(info_html),  # type: ignore[typeddict-item]
        "origem": ex.extract_origem(info_html),  # type: ignore[typeddict-item]
        "numero_origem": ex.extract_numero_origem(info_html),  # type: ignore[typeddict-item]
        "volumes": ex.extract_volumes(info_html),  # type: ignore[typeddict-item]
        "folhas": ex.extract_folhas(info_html),  # type: ignore[typeddict-item]
        "apensos": ex.extract_apensos(info_html),  # type: ignore[typeddict-item]
        "relator": ex.extract_relator(detalhe),
        "primeiro_autor": ex.extract_primeiro_autor(partes),
        "partes": partes,
        "andamentos": ex.extract_andamentos(fetched.tabs.get("abaAndamentos", "")),
        "sessao_virtual": ex.extract_sessao_virtual(fetched.tabs.get("abaSessao", "")),
        "deslocamentos": ex.extract_deslocamentos(fetched.tabs.get("abaDeslocamentos", "")),
        "peticoes": ex.extract_peticoes(fetched.tabs.get("abaPeticoes", "")),
        "recursos": ex.extract_recursos(fetched.tabs.get("abaRecursos", "")),
        # pautas isn't parsed server-side in any current fragment; mirror
        # Selenium's placeholder. Note: ground-truth fixtures are
        # inconsistent here — ACO_2652 has null, the others have [].
        "pautas": [],
        "status": 200,
        "extraido": datetime.now().isoformat(),
        "html": detalhe,
    }
    return item


# Legacy name kept as alias so the existing bench script keeps working.
extract_andamentos_http = ex.extract_andamentos
