"""Unit tests for src.scraping.extraction.http.extract_primeiro_autor.

The extractor scans `partes` for the first party whose `tipo` matches
one of the known "author" codes (class-specific: AUTOR for ACO, REQTE
for ADI, RECTE for RE, IMPTE for MS/MI, PACTE for HC, AGTE for AI, …).
"""

from __future__ import annotations

from judex.scraping.extraction.http import extract_primeiro_autor


def test_aco_autor():
    partes = [
        {"index": 1, "tipo": "AUTOR(A/S)(ES)", "nome": "ESTADO DE SERGIPE"},
        {"index": 2, "tipo": "PROC.(A/S)(ES)", "nome": "PGE-SE"},
        {"index": 3, "tipo": "RÉU(É)(S)", "nome": "UNIAO"},
    ]
    assert extract_primeiro_autor(partes) == "ESTADO DE SERGIPE"


def test_adi_reqte():
    partes = [
        {"index": 1, "tipo": "REQTE.(S)", "nome": "GOVERNADOR"},
        {"index": 2, "tipo": "INTDO.(A/S)", "nome": "ASSEMBLEIA"},
    ]
    assert extract_primeiro_autor(partes) == "GOVERNADOR"


def test_re_recte():
    partes = [
        {"index": 1, "tipo": "RECTE.(S)", "nome": "GUNARS SPROGIS"},
        {"index": 2, "tipo": "RECDO.(A/S)", "nome": "UNIAO"},
    ]
    assert extract_primeiro_autor(partes) == "GUNARS SPROGIS"


def test_hc_returns_pacte_when_first():
    # HCs list PACTE first, then IMPTE (the filer, often a lawyer).
    # For the deep-dive, the pacient (subject of the HC) is what matters.
    partes = [
        {"index": 1, "tipo": "PACTE.(S)", "nome": "OSVALDO PARDO CASAS NETO"},
        {"index": 2, "tipo": "IMPTE.(S)", "nome": "GUILHERME NEHLS PINHEIRO"},
        {"index": 3, "tipo": "COATOR(A/S)(ES)", "nome": "STJ"},
    ]
    assert extract_primeiro_autor(partes) == "OSVALDO PARDO CASAS NETO"


def test_ms_mi_impte_when_no_pacte():
    # MS/MI list IMPTE directly (no pacient).
    partes = [
        {"index": 1, "tipo": "IMPTE.(S)", "nome": "SERGIO ROCHA CAMARA"},
        {"index": 2, "tipo": "ADV.(A/S)", "nome": "EM CAUSA PROPRIA"},
        {"index": 3, "tipo": "IMPDO.(A/S)", "nome": "CONGRESSO NACIONAL"},
    ]
    assert extract_primeiro_autor(partes) == "SERGIO ROCHA CAMARA"


def test_ai_agte():
    partes = [
        {"index": 1, "tipo": "AGTE.(S)", "nome": "TESTE"},
        {"index": 2, "tipo": "ADV.(A/S)", "nome": "ADVOGADO TESTE"},
        {"index": 3, "tipo": "AGDO.(A/S)", "nome": "ESTADO DO ACRE"},
    ]
    assert extract_primeiro_autor(partes) == "TESTE"


def test_empty_partes_returns_none():
    assert extract_primeiro_autor([]) is None


def test_unknown_tipo_only_returns_none():
    partes = [
        {"index": 1, "tipo": "PROC.(A/S)(ES)", "nome": "Someone"},
        {"index": 2, "tipo": "ADV.(A/S)", "nome": "Lawyer"},
    ]
    assert extract_primeiro_autor(partes) is None
