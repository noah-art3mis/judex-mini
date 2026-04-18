"""Extractors for `abaPartes` — party list + derived `primeiro_autor`.

Reads from `#todas-partes` (every named party, each IMPTE lawyer listed
separately, PROC.(A/S)(ES) preserved). The sibling `#partes-resumidas`
container on the same fragment collapses multi-lawyer groups into
"E OUTRO(A/S)" and drops PROC entries on HC — we don't want that.
"""

from __future__ import annotations

from typing import Optional

from bs4 import BeautifulSoup

from src.analysis.legal_vocab import AUTHOR_PARTY_TIPOS
from src.utils.text_utils import normalize_spaces


def extract_partes(partes_html: str) -> list[dict]:
    soup = BeautifulSoup(partes_html, "lxml")
    container = soup.find(id="todas-partes")
    if container is None:
        return []
    # Inside #todas-partes, each .processo-partes row holds one-or-more
    # (label, name) pairs stored as sibling .detalhe-parte + .nome-parte
    # divs. Iterating both lists in parallel reconstructs the pairs.
    labels = container.select(".detalhe-parte")
    names = container.select(".nome-parte")
    out: list[dict] = []
    for label, name in zip(labels, names):
        tipo = normalize_spaces(label.get_text(" ", strip=True))
        nome = normalize_spaces(name.get_text(" ", strip=True))
        if tipo and nome:
            out.append({"index": len(out) + 1, "tipo": tipo, "nome": nome})
    return out


def extract_primeiro_autor(partes: list[dict]) -> Optional[str]:
    for parte in partes:
        if parte.get("tipo", "").startswith(AUTHOR_PARTY_TIPOS):
            return parte.get("nome")
    return None
