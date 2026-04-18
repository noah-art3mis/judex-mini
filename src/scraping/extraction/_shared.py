"""
Shared helpers used by both the Selenium extractors (src/scraping/extraction/)
and the HTTP extractors (src/scraping/extraction/http.py).

These are pure functions/constants that operate on BeautifulSoup trees
or raw HTML strings — no driver dependency.
"""

from __future__ import annotations

import re
from typing import Iterable

from bs4 import BeautifulSoup, Tag

from src.utils.text_utils import normalize_spaces


_GUIA_SUFFIX = re.compile(r",\s*GUIA\s*N[ºOo0]?[^,]*$", re.IGNORECASE)


def clean_nome(nome: str) -> str:
    nome = normalize_spaces(nome)
    if nome:
        nome = _GUIA_SUFFIX.sub("", nome).strip()
    return nome


P_DETAIL_BOLD = re.compile(r'processo-detalhes-bold">([^<]+)')
P_DETAIL_BASIC = re.compile(r'"processo-detalhes">([^<]+)')
P_DETAIL_INFO = re.compile(r'processo-detalhes bg-font-info">([^<]+)')
P_DETAIL_SUCCESS = re.compile(r'processo-detalhes bg-font-success">([^<]+)')
P_GUIA_CELL = re.compile(r'text-right">\s*<span class="processo-detalhes">([^<]+)')
P_EM_DATE = re.compile(r"em (\d{2}/\d{2}/\d{4})")
P_RECEBIDO_EM = re.compile(r"Recebido em ([^<]+)")


def strip_actor_boiler(text: str, prefix: str) -> str:
    """Remove 'Enviado por '/'Recebido por ' prefix and trailing ' em DD/MM/YYYY'."""
    t = re.sub(rf"^{prefix} ", "", text)
    t = re.sub(r" em \d{2}/\d{2}/\d{4}$", "", t)
    return t.strip()


def iter_lista_dados(html: str) -> Iterable[tuple[int, Tag]]:
    """
    Yield (reverse_index, row_tag) for each .lista-dados row in a tab
    fragment. Reverse index matches the ordering the Selenium extractors
    produce (newest item gets the highest number).
    """
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select(".lista-dados")
    total = len(rows)
    for i, row in enumerate(rows):
        yield total - i, row


