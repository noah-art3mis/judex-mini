"""Unit tests for src.extraction_http.derive_outcome.

Given a partially-built StfItem dict (sessao_virtual + andamentos are
what matter), derive a coarse `outcome` label that says who won:

    concedido              HC/MS/MI: ordem concedida (pacient wins)
    concedido_parcial      HC/MS/MI: ordem concedida em parte
    denegado               HC/MS/MI: ordem denegada (pacient loses on merits)
    nao_conhecido          petition not admitted (procedural rejection)
    prejudicado            moot / lost its object
    extinto                extinguished without judgement of merits
    provido                RE/AI: appeal granted
    provido_parcial        RE/AI: provimento parcial
    nao_provido            RE/AI: appeal denied
    procedente             ADI/ADC: direct action granted (prevails)
    improcedente           ADI/ADC: direct action denied
    None                   pending or couldn't be derived

Sources checked (in order): sessao_virtual[-1].voto_relator text,
andamentos nome+complemento.
"""

from __future__ import annotations

from src.extraction_http import derive_outcome


def _make_item(**kwargs):
    base = dict(
        sessao_virtual=[],
        andamentos=[],
    )
    base.update(kwargs)
    return base


# ---- voto_relator signals --------------------------------------------


def test_denego_a_ordem_returns_denegado():
    item = _make_item(sessao_virtual=[{
        "voto_relator": (
            "Ante o exposto, DENEGO A ORDEM, restando "
            "prejudicado o agravo regimental."
        ),
    }])
    assert derive_outcome(item) == "denegado"


def test_concedo_a_ordem_returns_concedido():
    item = _make_item(sessao_virtual=[{
        "voto_relator": "Ante o exposto, CONCEDO A ORDEM de habeas corpus.",
    }])
    assert derive_outcome(item) == "concedido"


def test_ordem_parcialmente_concedida_returns_concedido_parcial():
    item = _make_item(sessao_virtual=[{
        "voto_relator": (
            "Voto pela CONCESSÃO PARCIAL da ordem para determinar que..."
        ),
    }])
    assert derive_outcome(item) == "concedido_parcial"


def test_nao_conheço_returns_nao_conhecido():
    item = _make_item(sessao_virtual=[{
        "voto_relator": "NÃO CONHEÇO do habeas corpus, por inadequação da via.",
    }])
    assert derive_outcome(item) == "nao_conhecido"


def test_nego_provimento_returns_nao_provido():
    item = _make_item(sessao_virtual=[{
        "voto_relator": "NEGO PROVIMENTO ao recurso extraordinário.",
    }])
    assert derive_outcome(item) == "nao_provido"


def test_dou_provimento_returns_provido():
    item = _make_item(sessao_virtual=[{
        "voto_relator": "DOU PROVIMENTO ao recurso para reformar o acórdão.",
    }])
    assert derive_outcome(item) == "provido"


def test_julgo_procedente_returns_procedente():
    item = _make_item(sessao_virtual=[{
        "voto_relator": "JULGO PROCEDENTE a ação direta para declarar...",
    }])
    assert derive_outcome(item) == "procedente"


def test_julgo_improcedente_returns_improcedente():
    item = _make_item(sessao_virtual=[{
        "voto_relator": "JULGO IMPROCEDENTE a ação.",
    }])
    assert derive_outcome(item) == "improcedente"


# ---- andamento fallback ---------------------------------------------


def test_andamento_concedida_a_ordem():
    item = _make_item(andamentos=[
        {"nome": "CONCEDIDA A ORDEM DE HABEAS CORPUS", "complemento": None},
    ])
    assert derive_outcome(item) == "concedido"


def test_andamento_denegada_a_ordem():
    item = _make_item(andamentos=[
        {"nome": "DENEGADA A ORDEM", "complemento": None},
    ])
    assert derive_outcome(item) == "denegado"


def test_nego_seguimento_returns_nao_conhecido():
    # Monocratic procedural denial under RISTF art. 21 §1. Lumped in
    # with nao_conhecido for the coarse deep-dive bucket.
    item = _make_item(andamentos=[{
        "nome": "NEGADO SEGUIMENTO",
        "complemento": "Pelo exposto, nego seguimento ao habeas corpus (§ 1º do art. 21 do RISTF)",
    }])
    assert derive_outcome(item) == "nao_conhecido"


def test_nego_seguimento_with_prejudicada_liminar_still_nao_conhecido():
    # Real case (HC 220000): main verdict is NEGO SEGUIMENTO but the
    # complemento also says "prejudicada a medida liminar". The main
    # verdict must win; the side-clause about the liminar must not.
    item = _make_item(andamentos=[{
        "nome": "NEGADO SEGUIMENTO",
        "complemento": (
            "12. Pelo exposto, nego seguimento ao habeas corpus "
            "(§ 1º do art. 21 do Regimento Interno do STF), "
            "prejudicada a medida liminar requerida."
        ),
    }])
    assert derive_outcome(item) == "nao_conhecido"


def test_andamento_prejudicado():
    item = _make_item(andamentos=[
        {"nome": "PREJUDICADO", "complemento": "Pelo julgamento do HC X"},
    ])
    assert derive_outcome(item) == "prejudicado"


def test_andamento_extinto_sem_resolucao():
    item = _make_item(andamentos=[
        {"nome": "EXTINTO SEM RESOLUÇÃO DE MÉRITO", "complemento": None},
    ])
    assert derive_outcome(item) == "extinto"


# ---- priority: voto_relator beats andamento ------------------------


def test_voto_relator_beats_andamento():
    item = _make_item(
        sessao_virtual=[{"voto_relator": "DENEGO A ORDEM"}],
        andamentos=[{"nome": "PREJUDICADO", "complemento": None}],
    )
    assert derive_outcome(item) == "denegado"


def test_last_session_wins_when_multiple():
    item = _make_item(sessao_virtual=[
        {"voto_relator": "CONCEDO A ORDEM"},  # earlier session
        {"voto_relator": "DENEGO A ORDEM"},   # later session — final verdict
    ])
    assert derive_outcome(item) == "denegado"


# ---- pending / no signal -------------------------------------------


def test_empty_returns_none():
    assert derive_outcome(_make_item()) is None


def test_only_procedural_andamentos_returns_none():
    item = _make_item(andamentos=[
        {"nome": "PROTOCOLADO", "complemento": None},
        {"nome": "AUTUADO", "complemento": None},
        {"nome": "CONCLUSOS AO(À) RELATOR(A)", "complemento": None},
    ])
    assert derive_outcome(item) is None


def test_sessao_virtual_without_voto_relator_returns_none():
    # Virtual session exists but the voto text hasn't been published yet.
    item = _make_item(sessao_virtual=[
        {"metadata": {"status": "aberta"}, "voto_relator": ""},
    ])
    assert derive_outcome(item) is None
