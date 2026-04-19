"""Tests for `extract_partes` on the abaPartes fragment.

The portal serves two containers: `#partes-resumidas` (collapses
multi-lawyer IMPTE entries into "E OUTRO(A/S)" and drops PROC.(A/S)(ES)
on HC) and `#todas-partes` (every named party in document order). We
want the latter.
"""

from __future__ import annotations

from judex.scraping.extraction.partes import extract_partes, extract_primeiro_autor


HC_158802_PARTES_HTML = """
<div id="todas-partes">
<div class="processo-partes lista-dados m-l-16 p-t-0">
    <div class="detalhe-parte">PACTE.(S)</div>
    <div class="nome-parte">ROBERTO RZEZINSKI</div>
</div>
<div class="processo-partes lista-dados m-l-16 p-t-0">
    <div class="detalhe-parte">IMPTE.(S)</div>
    <div class="nome-parte">CLAUDIO BIDINO DE SOUZA (145100/RJ, 298100/SP)</div>
    <div class="detalhe-parte">IMPTE.(S)</div>
    <div class="nome-parte">TATHIANA DE CARVALHO COSTA (119367/RJ)</div>
    <div class="detalhe-parte">IMPTE.(S)</div>
    <div class="nome-parte">BRUNO FERNANDES CARVALHO (204733/RJ, 436155/SP)</div>
</div>
<div class="processo-partes lista-dados m-l-16 p-t-0">
    <div class="detalhe-parte">COATOR(A/S)(ES)</div>
    <div class="nome-parte">RELATOR DO HC Nº 454.745 DO SUPERIOR TRIBUNAL DE JUSTIÇA</div>
</div>
<div class="processo-partes lista-dados m-l-16 p-t-0">
    <div class="detalhe-parte">INTDO.(A/S)</div>
    <div class="nome-parte">MINISTÉRIO PÚBLICO FEDERAL</div>
</div>
<div class="processo-partes lista-dados m-l-16 p-t-0">
    <div class="detalhe-parte">PROC.(A/S)(ES)</div>
    <div class="nome-parte">PROCURADOR-GERAL DA REPÚBLICA</div>
</div>
</div>
"""


def test_extract_partes_expands_all_impte_and_keeps_proc():
    partes = extract_partes(HC_158802_PARTES_HTML)
    assert partes == [
        {"index": 1, "tipo": "PACTE.(S)",       "nome": "ROBERTO RZEZINSKI"},
        {"index": 2, "tipo": "IMPTE.(S)",       "nome": "CLAUDIO BIDINO DE SOUZA (145100/RJ, 298100/SP)"},
        {"index": 3, "tipo": "IMPTE.(S)",       "nome": "TATHIANA DE CARVALHO COSTA (119367/RJ)"},
        {"index": 4, "tipo": "IMPTE.(S)",       "nome": "BRUNO FERNANDES CARVALHO (204733/RJ, 436155/SP)"},
        {"index": 5, "tipo": "COATOR(A/S)(ES)", "nome": "RELATOR DO HC Nº 454.745 DO SUPERIOR TRIBUNAL DE JUSTIÇA"},
        {"index": 6, "tipo": "INTDO.(A/S)",     "nome": "MINISTÉRIO PÚBLICO FEDERAL"},
        {"index": 7, "tipo": "PROC.(A/S)(ES)",  "nome": "PROCURADOR-GERAL DA REPÚBLICA"},
    ]


def test_extract_partes_empty_when_container_missing():
    assert extract_partes("<html><body><p>no parties</p></body></html>") == []


def test_extract_primeiro_autor_finds_first_pacte():
    partes = extract_partes(HC_158802_PARTES_HTML)
    assert extract_primeiro_autor(partes) == "ROBERTO RZEZINSKI"
