"""DJe (Diário da Justiça Eletrônica) fetch + cache helpers.

Split out of `scraper.py` to keep that file under the 600-line ceiling
called out in CLAUDE.md. Every function here lives on
`portal.stf.jus.br/servicos/dje/...` URLs and has a single consumer:
`scrape_processo_http` in `scraper.py`. DJe HTML parsing lives in
`judex.scraping.extraction.dje`; this module only handles fetching,
caching, and the per-case fetcher factories that close over a
shared `_CacheBuf`.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, Optional

import requests

from judex.config import ScraperConfig
from judex.scraping.extraction import dje as dje_ex
from judex.scraping.http_session import _decode, _http_get_with_retry
from judex.utils import html_cache

if TYPE_CHECKING:
    from judex.scraping.scraper import _CacheBuf

_BASE_PROCESSOS = "https://portal.stf.jus.br/processos"
BASE_DJE = "https://portal.stf.jus.br/servicos/dje"
TAB_DJE_LISTING = "dje_listing"


def fetch_dje_listing(
    session: requests.Session,
    classe: str,
    processo: int,
    *,
    config: Optional[ScraperConfig] = None,
) -> str:
    """GET the `listarDiarioJustica.asp` HTML for a (classe, processo).

    This endpoint is keyed on `(classe, numero)` — not `incidente`
    like the `abaX.asp` tabs — because the DJe indexes by the
    publication identifier, which the portal maps to the case. Same
    WAF bucket as `portal.stf.jus.br`.
    """
    r = _http_get_with_retry(
        session,
        f"{BASE_DJE}/listarDiarioJustica.asp",
        params={"tipoPesquisaDJ": "AP", "classe": classe, "numero": processo},
        headers={
            "Referer": f"{_BASE_PROCESSOS}/detalhe.asp",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "text/html, */*; q=0.01",
        },
        config=config,
    )
    return _decode(r)


def fetch_dje_detail(
    session: requests.Session,
    url: str,
    *,
    classe: str,
    processo: int,
    config: Optional[ScraperConfig] = None,
) -> str:
    """GET a `verDiarioProcesso.asp` detail page. `url` is absolute."""
    r = _http_get_with_retry(
        session,
        url,
        headers={
            "Referer": (
                f"{BASE_DJE}/listarDiarioJustica.asp"
                f"?tipoPesquisaDJ=AP&classe={classe}&numero={processo}"
            ),
            "Accept": "text/html, */*; q=0.01",
        },
        config=config,
    )
    return _decode(r)


def _dje_detail_cache_key(url: str) -> str:
    """Tab-key for a DJe detail HTML in the per-case html_cache archive."""
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"dje_detail_{h}"


def _make_dje_listing_fetcher(
    classe: str,
    processo: int,
    session: requests.Session,
    *,
    cache_buf: "_CacheBuf",
    use_cache: bool,
    config: Optional[ScraperConfig],
) -> Any:
    def fetcher() -> str:
        tab = TAB_DJE_LISTING
        if use_cache:
            hit = html_cache.read(classe, processo, tab)
            if hit is not None:
                cache_buf.put(tab, hit, from_network=False)
                return hit
        html = fetch_dje_listing(session, classe, processo, config=config)
        cache_buf.put(tab, html, from_network=True)
        return html
    return fetcher


def _make_dje_detail_fetcher(
    classe: str,
    processo: int,
    session: requests.Session,
    *,
    cache_buf: "_CacheBuf",
    use_cache: bool,
    config: Optional[ScraperConfig],
) -> Any:
    def fetcher(url: str) -> str:
        tab = _dje_detail_cache_key(url)
        if use_cache:
            hit = html_cache.read(classe, processo, tab)
            if hit is not None:
                cache_buf.put(tab, hit, from_network=False)
                return hit
        html = fetch_dje_detail(
            session, url, classe=classe, processo=processo, config=config
        )
        cache_buf.put(tab, html, from_network=True)
        return html
    return fetcher


def _resolve_publicacoes_dje(
    entries: list[dict],
    *,
    detail_fetcher: Any,
) -> list[dict]:
    """Fill each listing entry with detail-page fields.

    Per ADR-0001 the case-scrape no longer fetches RTF bytes inline:
    ``decisoes[].rtf`` stays a URL-only pointer (``text`` + ``extractor``
    are None). The bytes-first ``baixar-pecas`` + ``extrair-pecas``
    pipeline materialises canonical text into ``peca_cache`` on demand.
    ``decisoes[].texto`` (HTML-extracted) remains as the DJe fast-path.

    Phase 1 (ADR-0003) redirect-form entries have ``detail_url=None``
    (post-2022-12-19 STF DJe migration — content moved to
    ``digital.stf.jus.br`` behind AWS WAF, no legacy detail page to
    fetch). Skip the fetch for those; their metadata is sufficient.
    Full content recovery is Phase 2 (Playwright, deferred).
    """
    for entry in entries:
        if entry.get("detail_url") is None:
            continue
        detail_html = detail_fetcher(entry["detail_url"])
        detail = dje_ex.parse_dje_detail(detail_html)
        entry.update(detail)
    return entries
