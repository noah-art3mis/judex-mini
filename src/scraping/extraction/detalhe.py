"""Extractors for `detalhe.asp` fragment data.

Pulled out of `http.py` on 2026-04-17 so each fragment has its own
small module. Sibling files: `info.py`, `partes.py`, `tables.py`,
`outcome.py`, plus the single-field modules (`classe.py`, `meio.py`,
`numero_unico.py`, `publicidade.py`, `relator.py`).
"""

from __future__ import annotations

from typing import Optional

from bs4 import BeautifulSoup


def extract_incidente(detalhe_soup: BeautifulSoup) -> Optional[int]:
    el = detalhe_soup.find(id="incidente")
    if el is None:
        return None
    value = el.get("value")
    if value and str(value).isdigit():
        return int(value)
    return None


def extract_badges(detalhe_soup: BeautifulSoup) -> list[str]:
    # Only bg-danger pills are actual flags (Criminal, Medida Liminar, Réu
    # Preso, Maior de 60 anos). bg-primary / bg-success duplicate `meio` /
    # `publicidade`.
    return [
        el.get_text(" ", strip=True)
        for el in detalhe_soup.select(".badge.bg-danger")
        if el.get_text(" ", strip=True)
    ]
