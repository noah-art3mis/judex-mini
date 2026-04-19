"""Unit tests for src.scraping.extraction.http.derive_outcome.

Given a partially-built StfItem dict (sessao_virtual + andamentos are
what matter), derive an OutcomeInfo dict with the verdict label and
enough provenance to trace it back to the source record:

    {verdict, source: "sessao_virtual"|"andamentos",
     source_index, date_iso}

Verdict vocabulary (values of ``verdict``):

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

from src.scraping.extraction.http import derive_outcome


def _make_item(**kwargs):
    base = dict(
        sessao_virtual=[],
        andamentos=[],
    )
    base.update(kwargs)
    return base


def _verdict(item):
    out = derive_outcome(item)
    return None if out is None else out["verdict"]


# ---- voto_relator signals --------------------------------------------


def test_denego_a_ordem_returns_denegado():
    item = _make_item(sessao_virtual=[{
        "voto_relator": (
            "Ante o exposto, DENEGO A ORDEM, restando "
            "prejudicado o agravo regimental."
        ),
    }])
    assert _verdict(item) == "denegado"


def test_concedo_a_ordem_returns_concedido():
    item = _make_item(sessao_virtual=[{
        "voto_relator": "Ante o exposto, CONCEDO A ORDEM de habeas corpus.",
    }])
    assert _verdict(item) == "concedido"


def test_ordem_parcialmente_concedida_returns_concedido_parcial():
    item = _make_item(sessao_virtual=[{
        "voto_relator": (
            "Voto pela CONCESSÃO PARCIAL da ordem para determinar que..."
        ),
    }])
    assert _verdict(item) == "concedido_parcial"


def test_nao_conheço_returns_nao_conhecido():
    item = _make_item(sessao_virtual=[{
        "voto_relator": "NÃO CONHEÇO do habeas corpus, por inadequação da via.",
    }])
    assert _verdict(item) == "nao_conhecido"


def test_nego_provimento_returns_nao_provido():
    item = _make_item(sessao_virtual=[{
        "voto_relator": "NEGO PROVIMENTO ao recurso extraordinário.",
    }])
    assert _verdict(item) == "nao_provido"


def test_dou_provimento_returns_provido():
    item = _make_item(sessao_virtual=[{
        "voto_relator": "DOU PROVIMENTO ao recurso para reformar o acórdão.",
    }])
    assert _verdict(item) == "provido"


def test_julgo_procedente_returns_procedente():
    item = _make_item(sessao_virtual=[{
        "voto_relator": "JULGO PROCEDENTE a ação direta para declarar...",
    }])
    assert _verdict(item) == "procedente"


def test_julgo_improcedente_returns_improcedente():
    item = _make_item(sessao_virtual=[{
        "voto_relator": "JULGO IMPROCEDENTE a ação.",
    }])
    assert _verdict(item) == "improcedente"


# ---- andamento fallback ---------------------------------------------


def test_andamento_concedida_a_ordem():
    item = _make_item(andamentos=[
        {"nome": "CONCEDIDA A ORDEM DE HABEAS CORPUS", "complemento": None},
    ])
    assert _verdict(item) == "concedido"


def test_andamento_denegada_a_ordem():
    item = _make_item(andamentos=[
        {"nome": "DENEGADA A ORDEM", "complemento": None},
    ])
    assert _verdict(item) == "denegado"


def test_nego_seguimento_returns_nao_conhecido():
    # Monocratic procedural denial under RISTF art. 21 §1. Lumped in
    # with nao_conhecido for the coarse deep-dive bucket.
    item = _make_item(andamentos=[{
        "nome": "NEGADO SEGUIMENTO",
        "complemento": "Pelo exposto, nego seguimento ao habeas corpus (§ 1º do art. 21 do RISTF)",
    }])
    assert _verdict(item) == "nao_conhecido"


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
    assert _verdict(item) == "nao_conhecido"


def test_andamento_prejudicado():
    item = _make_item(andamentos=[
        {"nome": "PREJUDICADO", "complemento": "Pelo julgamento do HC X"},
    ])
    assert _verdict(item) == "prejudicado"


def test_andamento_extinto_sem_resolucao():
    item = _make_item(andamentos=[
        {"nome": "EXTINTO SEM RESOLUÇÃO DE MÉRITO", "complemento": None},
    ])
    assert _verdict(item) == "extinto"


# ---- priority: voto_relator beats andamento ------------------------


def test_voto_relator_beats_andamento():
    item = _make_item(
        sessao_virtual=[{"voto_relator": "DENEGO A ORDEM"}],
        andamentos=[{"nome": "PREJUDICADO", "complemento": None}],
    )
    assert _verdict(item) == "denegado"


def test_last_session_wins_when_multiple():
    item = _make_item(sessao_virtual=[
        {"voto_relator": "CONCEDO A ORDEM"},  # earlier session
        {"voto_relator": "DENEGO A ORDEM"},   # later session — final verdict
    ])
    assert _verdict(item) == "denegado"


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


# ---- provenance shape ----------------------------------------------


def test_sessao_source_carries_session_index_and_metadata_date():
    # v6: metadata keys are ASCII snake_case; dates are ISO 8601 on emit.
    item = _make_item(sessao_virtual=[
        {"voto_relator": "CONCEDO A ORDEM", "metadata": {"data_inicio": "2020-04-10"}},
        {"voto_relator": "DENEGO A ORDEM", "metadata": {"data_inicio": "2020-04-17"}},
    ])
    out = derive_outcome(item)
    assert out == {
        "verdict": "denegado",
        "source": "sessao_virtual",
        "source_index": 1,  # last session wins
        "date_iso": "2020-04-17",
    }


def test_andamento_source_carries_index_and_iso_date():
    # v6: `index_num` → `index`; the raw DD/MM/YYYY display field is
    # gone — `data` now carries ISO 8601 directly.
    item = _make_item(andamentos=[
        {
            "index": 42,
            "nome": "DENEGADA A ORDEM",
            "complemento": None,
            "data": "2020-08-28",
        },
    ])
    out = derive_outcome(item)
    assert out == {
        "verdict": "denegado",
        "source": "andamentos",
        "source_index": 42,
        "date_iso": "2020-08-28",
    }


def test_andamento_source_uses_data_as_date_iso():
    # v6: no `data_iso` companion; the single `data` field is ISO.
    item = _make_item(andamentos=[
        {
            "index": 7,
            "nome": "PREJUDICADO",
            "complemento": None,
            "data": "2021-06-01",
        },
    ])
    out = derive_outcome(item)
    assert out is not None
    assert out["date_iso"] == "2021-06-01"
