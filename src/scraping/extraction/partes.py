"""Extractors for `abaPartes` — party list + derived `primeiro_autor`.

Reads from `#partes-resumidas` (mirroring Selenium's `#resumo-partes`,
which is populated from it), 4 entries on ADI 2820.
"""

from __future__ import annotations

from typing import Optional

from bs4 import BeautifulSoup

from src.analysis.legal_vocab import AUTHOR_PARTY_TIPOS
from src.scraping.extraction._shared import extract_partes_from_soup


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
