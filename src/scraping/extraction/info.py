"""Extractors for the `abaInformacoes` fragment.

All functions take a BeautifulSoup for the tab fragment and return
either a scalar or a small list. Shares two private helpers
(`_labeled_value`, `_quadro_value`) used by most extractors.
"""

from __future__ import annotations

from typing import Optional

from bs4 import BeautifulSoup

from src.utils.text_utils import normalize_spaces


def _labeled_value(soup: BeautifulSoup, label: str) -> Optional[str]:
    target = label.strip().rstrip(":")
    for bold in soup.select(".processo-detalhes-bold"):
        text = normalize_spaces(bold.get_text(strip=True)).rstrip(":")
        if text == target:
            sib = bold.find_next_sibling("div")
            if sib is None:
                return None
            return normalize_spaces(sib.get_text(strip=True)) or None
    return None


def _quadro_value(info_soup: BeautifulSoup, label: str) -> Optional[int]:
    target = label.strip().upper()
    for box in info_soup.select(".processo-quadro"):
        rot = box.select_one(".rotulo")
        if not rot:
            continue
        if target in rot.get_text(strip=True).upper():
            num = box.select_one(".numero")
            if not num:
                return None
            text = num.get_text(strip=True)
            return int(text) if text.isdigit() else None
    return None


def extract_assuntos(info_soup: BeautifulSoup) -> list[str]:
    wrapper = info_soup.select_one(".informacoes__assunto") or info_soup
    out: list[str] = []
    for li in wrapper.find_all("li"):
        text = normalize_spaces(li.get_text(strip=True))
        if text:
            out.append(text)
    return out


def extract_data_protocolo(info_soup: BeautifulSoup) -> Optional[str]:
    return _labeled_value(info_soup, "Data de Protocolo")


def extract_orgao_origem(info_soup: BeautifulSoup) -> Optional[str]:
    span = info_soup.find(id="orgao-procedencia")
    if span:
        return normalize_spaces(span.get_text(strip=True)) or None
    return _labeled_value(info_soup, "Órgão de Origem")


def extract_origem(info_soup: BeautifulSoup) -> Optional[str]:
    span = info_soup.find(id="descricao-procedencia")
    if span:
        return normalize_spaces(span.get_text(strip=True)) or None
    return _labeled_value(info_soup, "Origem")


def extract_numero_origem(info_soup: BeautifulSoup) -> Optional[list[str]]:
    # STF emits comma-separated origin numbers on multi-source processes
    # (HC 158802 has 7 of them). Leading zeros carry meaning — keep as
    # strings rather than cast to int.
    val = _labeled_value(info_soup, "Número de Origem")
    if not val:
        return None
    parts = [p.strip() for p in val.split(",") if p.strip()]
    return parts or None


def extract_volumes(info_soup: BeautifulSoup) -> Optional[int]:
    return _quadro_value(info_soup, "VOLUME")


def extract_folhas(info_soup: BeautifulSoup) -> Optional[int]:
    return _quadro_value(info_soup, "FOLHA")


def extract_apensos(info_soup: BeautifulSoup) -> Optional[int]:
    return _quadro_value(info_soup, "APENSO")
