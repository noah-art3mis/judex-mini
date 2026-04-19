"""Unit tests for the DD/MM/YYYY → YYYY-MM-DD helper used to stamp
``*_iso`` companions on every date-bearing StfItem field.
"""

from __future__ import annotations

from src.scraping.extraction._shared import to_iso


def test_plain_ddmmyyyy():
    assert to_iso("28/08/2020") == "2020-08-28"


def test_trailing_time_as():
    # andamento.data shape on some rows: "17/08/2020 às 11:51"
    assert to_iso("17/08/2020 às 11:51") == "2020-08-17"


def test_trailing_seconds():
    # peticao.recebido_data shape: "20/08/2020 11:51:26"
    assert to_iso("20/08/2020 11:51:26") == "2020-08-20"


def test_leading_boiler():
    assert to_iso("Data: 01/01/2024") == "2024-01-01"


def test_none_and_empty_return_none():
    assert to_iso(None) is None
    assert to_iso("") is None


def test_no_date_returns_none():
    assert to_iso("pendente") is None


def test_invalid_day_returns_none():
    # Calendar plausibility only (not strict validation — Feb 30 passes
    # but Month 13 does not, since it's trivially wrong).
    assert to_iso("01/13/2024") is None


def test_year_out_of_range_returns_none():
    assert to_iso("01/01/1800") is None
