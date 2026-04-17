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
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src import extraction_http as ex
from src import extraction_http_sessao as sessao_ex
from src.config import ScraperConfig
from src.data.types import StfItem
from src.utils import html_cache, pdf_cache
from src.utils.pdf_utils import extract_document_text

SESSAO_JSON_BASE = "https://sistemas.stf.jus.br/repgeral/votacao"

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


class RetryableHTTPError(Exception):
    """Raised for HTTP status codes that warrant a retry (429, 5xx)."""

    def __init__(self, status_code: int, url: str = "") -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(f"HTTP {status_code} {url}".rstrip())


_RETRYABLE_NETWORK_EXCS = (
    requests.ConnectionError,
    requests.Timeout,
)


def _should_retry(exc: BaseException) -> bool:
    return isinstance(exc, (RetryableHTTPError,) + _RETRYABLE_NETWORK_EXCS)


def _http_get_with_retry(
    session: requests.Session,
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: int = 30,
    allow_redirects: bool = True,
    config: Optional[ScraperConfig] = None,
) -> requests.Response:
    """GET with tenacity retries on 429, 5xx, and network errors.

    4xx responses other than 429 raise immediately (no retry) — they signal
    a client-side problem that won't resolve on its own.
    """
    cfg = config or ScraperConfig()

    @retry(
        stop=stop_after_attempt(cfg.driver_max_retries),
        wait=wait_exponential(
            multiplier=cfg.driver_backoff_multiplier,
            min=cfg.driver_backoff_min,
            max=cfg.driver_backoff_max,
        ),
        retry=retry_if_exception(_should_retry),
        reraise=True,
        before_sleep=lambda st: logging.debug(
            f"Retry {st.attempt_number}/{cfg.driver_max_retries} for GET {url}: "
            f"{st.outcome.exception()}"
        ),
    )
    def _go() -> requests.Response:
        host = urlparse(url).hostname or ""
        if cfg.throttle is not None:
            cfg.throttle.wait(host)

        started = time.perf_counter()
        try:
            r = session.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout,
                allow_redirects=allow_redirects,
            )
        except Exception:
            elapsed = time.perf_counter() - started
            if cfg.throttle is not None:
                cfg.throttle.record(host, elapsed, was_error=True)
            if cfg.request_log is not None:
                cfg.request_log.log(
                    url=url, status=None,
                    elapsed_ms=int(elapsed * 1000),
                )
            raise

        elapsed = time.perf_counter() - started
        is_error = r.status_code >= 400
        if cfg.throttle is not None:
            cfg.throttle.record(host, elapsed, was_error=is_error)
        if cfg.request_log is not None:
            cfg.request_log.log(
                url=url,
                status=r.status_code,
                elapsed_ms=int(elapsed * 1000),
                bytes=len(r.content) if r.content is not None else None,
            )

        if (
            r.status_code == 429
            or 500 <= r.status_code < 600
            or (cfg.retry_403 and r.status_code == 403)
        ):
            raise RetryableHTTPError(r.status_code, url)
        r.raise_for_status()  # non-429 4xx: don't retry
        return r

    return _go()


def _decode(r: requests.Response) -> str:
    """STF serves UTF-8 without a charset; requests defaults to Latin-1 → mojibake."""
    r.encoding = "utf-8"
    return r.text


def resolve_incidente(
    session: requests.Session,
    classe: str,
    processo: int,
    *,
    config: Optional[ScraperConfig] = None,
) -> Optional[int]:
    """Follow the listarProcessos 302 to extract the incidente id."""
    r = _http_get_with_retry(
        session,
        f"{BASE}/listarProcessos.asp",
        params={"classe": classe, "numeroProcesso": processo},
        allow_redirects=False,
        config=config,
    )
    loc = r.headers.get("Location", "")
    m = re.search(r"incidente=(\d+)", loc)
    if not m:
        logging.warning(
            f"{classe} {processo}: no incidente in redirect ({r.status_code} {loc!r})"
        )
        return None
    return int(m.group(1))


def fetch_detalhe(
    session: requests.Session,
    incidente: int,
    *,
    config: Optional[ScraperConfig] = None,
) -> str:
    r = _http_get_with_retry(
        session,
        f"{BASE}/detalhe.asp",
        params={"incidente": incidente},
        config=config,
    )
    return _decode(r)


def fetch_tab(
    session: requests.Session,
    incidente: int,
    tab: str,
    *,
    config: Optional[ScraperConfig] = None,
) -> str:
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
    r = _http_get_with_retry(
        session,
        f"{BASE}/{tab}.asp",
        params=params,
        headers=headers,
        config=config,
    )
    return _decode(r)


def fetch_process(
    classe: str,
    processo: int,
    *,
    use_cache: bool = True,
    session: Optional[requests.Session] = None,
    config: Optional[ScraperConfig] = None,
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
            incidente = resolve_incidente(session, classe, processo, config=config)
            if incidente is None:
                return None
            html_cache.write_incidente(classe, processo, incidente)

        def cached(tab: str, fetcher: Any) -> str:
            if use_cache:
                hit = html_cache.read(classe, processo, tab)
                if hit is not None:
                    return hit
            html = fetcher()
            html_cache.write(classe, processo, tab, html)
            return html

        detalhe_html = cached(
            DETALHE, partial(fetch_detalhe, session, incidente, config=config)
        )

        with ThreadPoolExecutor(max_workers=_TAB_WORKERS) as pool:
            futures = {
                tab: pool.submit(
                    cached,
                    tab,
                    partial(fetch_tab, session, incidente, tab, config=config),
                )
                for tab in TABS
            }
            tabs = {tab: f.result() for tab, f in futures.items()}

        return ProcessFetch(incidente=incidente, detalhe_html=detalhe_html, tabs=tabs)
    finally:
        if owns_session:
            session.close()


def run_scraper_http(
    classe: str,
    processo_inicial: int,
    processo_final: int,
    output_format: str,
    output_dir: str,
    overwrite: bool,
    config: ScraperConfig,
    fetch_pdfs: bool = True,
) -> None:
    """HTTP-backed equivalent of src.scraper.run_scraper.

    Shares the output path and missing-retry shape; swaps the per-process
    Selenium drive for fetch_process + parse under a shared session.
    """
    from src.data.export import export_item
    from src.data.missing import check_missing_processes
    from src.data.output import OutputConfig
    from src.utils.timing import ProcessTimer

    out_file = f"{output_dir}/judex-mini_{classe}_{processo_inicial}-{processo_final}"
    output_config = OutputConfig.from_format_string(output_format)
    timer = ProcessTimer()
    all_exported_files: list[str] = []

    try:
        with new_session() as session:
            processos = list(range(processo_inicial, processo_final + 1))
            all_exported_files.extend(
                _scrape_http_batch(
                    processos,
                    classe,
                    config,
                    session,
                    out_file,
                    output_dir,
                    output_config,
                    overwrite,
                    timer,
                    export_item,
                    fetch_pdfs=fetch_pdfs,
                )
            )

            for attempt in range(config.driver_max_retries_for_missing):
                missing = check_missing_processes(
                    classe,
                    processo_inicial,
                    processo_final,
                    output_dir,
                    output_config,
                )
                if not missing:
                    break
                logging.info(
                    f"Retrying {len(missing)} missing processes "
                    f"(attempt {attempt + 1}/{config.driver_max_retries_for_missing})"
                )
                all_exported_files.extend(
                    _scrape_http_batch(
                        missing,
                        classe,
                        config,
                        session,
                        out_file,
                        output_dir,
                        output_config,
                        overwrite,
                        timer,
                        export_item,
                        fetch_pdfs=fetch_pdfs,
                    )
                )

        if all_exported_files:
            for file_info in all_exported_files:
                logging.info(f"Exported file: {file_info}")
        else:
            logging.warning(
                f"{classe} {processo_inicial}-{processo_final}: NO FILES EXPORTED"
            )
    finally:
        if timer.process_times:
            logging.info("=== SCRAPER ENDED - SHOWING REPORT ===")
            timer.log_summary()


def _scrape_http_batch(
    processos: list[int],
    classe: str,
    config: ScraperConfig,
    session: requests.Session,
    out_file: str,
    output_dir: str,
    output_config: Any,
    overwrite: bool,
    timer: Any,
    export_item: Any,
    *,
    fetch_pdfs: bool = True,
) -> list[str]:
    exported: list[str] = []
    for processo in processos:
        processo_name = f"{classe} {processo}"
        start = timer.start_process(processo_name)
        logging.info(f"{processo_name}: iniciado")

        try:
            item = scrape_processo_http(
                classe,
                processo,
                session=session,
                config=config,
                fetch_pdfs=fetch_pdfs,
            )
        except Exception as e:
            logging.error(f"{processo_name}: {type(e).__name__}: {e}")
            item = None

        if item:
            files = export_item(item, out_file, output_dir, output_config, overwrite)
            exported.extend(files)
            timer.end_process(processo_name, start, success=True)
        else:
            timer.end_process(processo_name, start, success=False)

    return exported


_TEMA_IN_ABASESSAO = re.compile(r"repgeral/votacao\?tema=(\d+)")


def _extract_tema_from_abasessao(sessao_html: str) -> Optional[int]:
    """The abaSessao fragment embeds the tema number in its `?tema=<N>` AJAX URL."""
    m = _TEMA_IN_ABASESSAO.search(sessao_html)
    if not m:
        return None
    return int(m.group(1))


def _make_pdf_fetcher(*, use_cache: bool = True) -> Any:
    """Return a `fetcher(url) -> Optional[str]` that caches extracted text.

    Cache is URL-keyed (sha1); misses hit sistemas.stf.jus.br via
    src.utils.pdf_utils.extract_document_text (which handles both PDF
    and RTF). Fetch failures propagate as None so resolve_documentos
    can keep the URL for a later retry.
    """

    def fetcher(url: str) -> Optional[str]:
        if use_cache:
            hit = pdf_cache.read(url)
            if hit is not None:
                return hit
        text = extract_document_text(url)
        if text is not None:
            pdf_cache.write(url, text)
        return text

    return fetcher


def _make_sessao_fetcher(
    classe: str,
    processo: int,
    session: requests.Session,
    *,
    use_cache: bool,
    config: Optional[ScraperConfig],
) -> Any:
    """Return a fetcher(param, value) that caches JSON responses on disk.

    404 on the ?oi= endpoint is treated as "no sessions for this process"
    and returns an empty-list JSON; STF uses it that way rather than an
    empty 200 response.
    """

    def fetcher(param: str, value: int) -> str:
        tab = f"sessao_{param}_{value}"
        if use_cache:
            hit = html_cache.read(classe, processo, tab)
            if hit is not None:
                return hit
        try:
            r = _http_get_with_retry(
                session,
                SESSAO_JSON_BASE,
                params={param: value},
                headers={"Accept": "application/json, */*; q=0.01"},
                config=config,
            )
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                html_cache.write(classe, processo, tab, "[]")
                return "[]"
            raise
        text = _decode(r)
        html_cache.write(classe, processo, tab, text)
        return text

    return fetcher


def scrape_processo_http(
    classe: str,
    processo: int,
    *,
    use_cache: bool = True,
    session: Optional[requests.Session] = None,
    config: Optional[ScraperConfig] = None,
    fetch_pdfs: bool = True,
) -> Optional[StfItem]:
    """Full-process scrape via HTTP. Returns the same StfItem shape as the Selenium path.

    When fetch_pdfs is True (default), sessao_virtual documentos URLs
    are replaced with extracted text; the URL-keyed pdf cache makes
    repeated runs cheap.
    """
    fetched = fetch_process(
        classe, processo, use_cache=use_cache, session=session, config=config
    )
    if fetched is None:
        return None

    detalhe_soup = BeautifulSoup(fetched.detalhe_html, "lxml")
    info_soup = BeautifulSoup(fetched.tabs.get(TAB_INFORMACOES, ""), "lxml")

    partes = ex.extract_partes(fetched.tabs.get(TAB_PARTES, ""))

    owns_session = session is None
    sessao_session = session or new_session()
    try:
        tema = _extract_tema_from_abasessao(fetched.tabs.get(TAB_SESSAO, ""))
        sessao_fetcher = _make_sessao_fetcher(
            classe, processo, sessao_session, use_cache=use_cache, config=config
        )
        pdf_fetcher = _make_pdf_fetcher(use_cache=use_cache) if fetch_pdfs else None
        sessao_virtual = sessao_ex.extract_sessao_virtual_from_json(
            incidente=fetched.incidente,
            tema=tema,
            fetcher=sessao_fetcher,
            pdf_fetcher=pdf_fetcher,
        )
    finally:
        if owns_session:
            sessao_session.close()

    andamentos = ex.extract_andamentos(fetched.tabs.get(TAB_ANDAMENTOS, ""))
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
        andamentos=andamentos,
        sessao_virtual=sessao_virtual,
        deslocamentos=ex.extract_deslocamentos(fetched.tabs.get(TAB_DESLOCAMENTOS, "")),
        peticoes=ex.extract_peticoes(fetched.tabs.get(TAB_PETICOES, "")),
        recursos=ex.extract_recursos(fetched.tabs.get(TAB_RECURSOS, "")),
        pautas=[],
        outcome=ex.derive_outcome({
            "sessao_virtual": sessao_virtual,
            "andamentos": andamentos,
        }),
        status=200,
        extraido=datetime.now().isoformat(),
        html=fetched.detalhe_html,
    )
