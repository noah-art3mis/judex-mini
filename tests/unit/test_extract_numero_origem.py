"""Tests for `extract_numero_origem` on the abaInformacoes fragment."""

from __future__ import annotations

from bs4 import BeautifulSoup

from judex.scraping.extraction.info import extract_numero_origem


def _soup_with_field(value: str) -> BeautifulSoup:
    html = f"""
    <html><body>
      <div class="processo-detalhes-bold">Número de Origem:</div>
      <div class="col-md-5 processo-detalhes">{value}</div>
    </body></html>
    """
    return BeautifulSoup(html, "lxml")


def test_returns_single_entry_list_for_one_number():
    assert extract_numero_origem(_soup_with_field("580")) == ["580"]


def test_splits_comma_separated_values():
    raw = "158802, 00735631120181000000, 454745"
    assert extract_numero_origem(_soup_with_field(raw)) == [
        "158802",
        "00735631120181000000",
        "454745",
    ]


def test_preserves_leading_zeros():
    # Bug in the prior `int(val)` path: leading zeros were lost even when
    # conversion succeeded. String form preserves them.
    raw = "00007356220118190060"
    assert extract_numero_origem(_soup_with_field(raw)) == ["00007356220118190060"]


def test_returns_none_when_field_missing():
    soup = BeautifulSoup("<html><body></body></html>", "lxml")
    assert extract_numero_origem(soup) is None


def test_drops_empty_fragments_from_trailing_commas():
    # Defensive: the portal has produced "2652, " / ", 000, " shapes before.
    raw = "2652, , 000"
    assert extract_numero_origem(_soup_with_field(raw)) == ["2652", "000"]
