"""Tests for `extract_badges` on the detalhe.asp fragment."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.scraping.extraction.detalhe import extract_badges


def _soup(inner: str) -> BeautifulSoup:
    return BeautifulSoup(f"<html><body>{inner}</body></html>", "lxml")


def test_extract_badges_keeps_only_bg_danger_flags_in_document_order():
    html = """
        <span class="badge bg-primary">Processo Eletrônico</span>
        <span class="badge bg-success">Público</span>
        <span class="badge bg-danger">Criminal</span>
        <span class="badge bg-danger">Medida Liminar</span>
        <span class="badge bg-danger">Réu Preso</span>
    """
    assert extract_badges(_soup(html)) == [
        "Criminal",
        "Medida Liminar",
        "Réu Preso",
    ]


def test_extract_badges_keeps_maior_de_60_anos():
    html = '<span class="badge bg-danger">Maior de 60 anos ou portador de doença grave</span>'
    assert extract_badges(_soup(html)) == [
        "Maior de 60 anos ou portador de doença grave",
    ]


def test_extract_badges_drops_primary_and_success_even_when_unique():
    # `Convertido em processo eletrônico` is bg-primary on ADI 2820 and is
    # unique information, but we filter it out here because `meio` captures
    # the current state and consumers can get history elsewhere.
    html = """
        <span class="badge bg-primary">Convertido em processo eletrônico</span>
        <span class="badge bg-success">Público</span>
    """
    assert extract_badges(_soup(html)) == []


def test_extract_badges_empty_when_no_badges():
    assert extract_badges(_soup("<p>no badges here</p>")) == []
