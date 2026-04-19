"""Tests for `parse_dje_listing` + `parse_dje_detail`.

Captured fixtures:
    tests/fixtures/dje/HC_158802_listing.html       — full listing (6 entries)
    tests/fixtures/dje/HC_158802_dj137_sessao.html  — Sessão Virtual variant
    tests/fixtures/dje/HC_158802_dj204_acordao.html — Acórdão variant (has EMENTA)

Design note: the listing parser returns PublicacaoDJe entries with
listing-only fields populated; detail-side fields are at their
empty defaults (None / []). The orchestrator in scraper.py fetches
each `detail_url`, parses it with `parse_dje_detail`, and merges
the result. Keeps each extractor pure and independently testable.
"""

from __future__ import annotations

from pathlib import Path

from judex.scraping.extraction.dje import parse_dje_detail, parse_dje_listing

FIX = Path(__file__).parent.parent / "fixtures" / "dje"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# ----- parse_dje_listing ---------------------------------------------------


def test_parse_dje_listing_yields_six_entries_for_hc_158802() -> None:
    entries = parse_dje_listing(_load("HC_158802_listing.html"))
    assert len(entries) == 6


def test_parse_dje_listing_first_entry_is_acordao_dj204_listing_shape() -> None:
    entries = parse_dje_listing(_load("HC_158802_listing.html"))
    first = entries[0]
    assert first["numero"] == 204
    assert first["data"] == "2020-08-17"
    assert first["secao"] == "Acórdãos"
    assert first["subsecao"] == "Acórdãos 2ª Turma"
    assert first["titulo"] == "AG.REG. NA MEDIDA CAUTELAR NO HABEAS CORPUS 158802"
    assert first["incidente_linked"] == 5522739
    # Absolute URL, built from the onclick args.
    assert first["detail_url"] == (
        "https://portal.stf.jus.br/servicos/dje/verDiarioProcesso.asp?"
        "numDj=204&dataPublicacaoDj=17/08/2020&incidente=5522739"
        "&codCapitulo=5&numMateria=132&codMateria=3"
    )
    # Detail-side fields are at defaults; detail parser fills them in.
    assert first["classe"] is None
    assert first["procedencia"] is None
    assert first["relator"] is None
    assert first["partes"] == []
    assert first["materia"] == []
    assert first["decisoes"] == []


def test_parse_dje_listing_incidente_linked_can_differ_across_entries() -> None:
    """AG.REG./distribuição entries file under different incidentes.

    HC 158802 was originally distributed under incidente 5494703; the
    AG.REG. got its own incidente 5522739; another filing shows up under
    5494713. The listing parser must preserve the 3rd onclick arg as
    given, not collapse to the parent case's incidente.
    """
    entries = parse_dje_listing(_load("HC_158802_listing.html"))
    linked = {e["incidente_linked"] for e in entries}
    assert linked == {5522739, 5494713, 5494703}


def test_parse_dje_listing_preserves_chronological_ordering_from_source() -> None:
    entries = parse_dje_listing(_load("HC_158802_listing.html"))
    assert [e["numero"] for e in entries] == [204, 137, 99, 78, 127, 126]


# ----- parse_dje_detail: Sessão Virtual variant (no EMENTA) ----------------


def test_parse_dje_detail_sessao_variant_identity_fields() -> None:
    d = parse_dje_detail(_load("HC_158802_dj137_sessao.html"))
    assert d["classe"] == "HC"
    assert d["procedencia"] == "DISTRITO FEDERAL"
    assert d["relator"] == "MIN. GILMAR MENDES"


def test_parse_dje_detail_sessao_variant_partes_are_raw_tipo_dash_nome_strings() -> None:
    d = parse_dje_detail(_load("HC_158802_dj137_sessao.html"))
    # Raw "TIPO - NOME" strings, not split — these are a temporal DJe
    # snapshot and don't need to match abaPartes' structured shape.
    assert d["partes"] == [
        "AGTE.(S) - MINISTÉRIO PÚBLICO FEDERAL",
        "PROC.(A/S)(ES) - PROCURADOR-GERAL DA REPÚBLICA",
        "AGDO.(A/S) - ROBERTO RZEZINSKI",
        "ADV.(A/S) - CLAUDIO BIDINO DE SOUZA",
    ]


def test_parse_dje_detail_sessao_variant_materia_is_pipeline_string() -> None:
    d = parse_dje_detail(_load("HC_158802_dj137_sessao.html"))
    assert d["materia"] == [
        "DIREITO PROCESSUAL PENAL | Prisão Preventiva | Revogação"
    ]


def test_parse_dje_detail_sessao_variant_has_two_decisao_blocks_no_ementa() -> None:
    d = parse_dje_detail(_load("HC_158802_dj137_sessao.html"))
    assert len(d["decisoes"]) == 2
    assert [b["kind"] for b in d["decisoes"]] == ["decisao", "decisao"]

    first = d["decisoes"][0]
    assert first["kind"] == "decisao"
    assert first["texto"].startswith(
        "Decisão: Após o voto do Ministro Relator"
    )
    assert first["texto"].rstrip().endswith("10.4.2020 a 17.4.2020.")
    assert first["rtf"] == {
        "tipo": "DJE",
        "url": (
            "https://portal.stf.jus.br/servicos/dje/verDecisao.asp?"
            "numDj=137&dataPublicacao=03/06/2020&incidente=5522739"
            "&capitulo=4&codigoMateria=12&numeroMateria=16&texto=8783507"
        ),
        "text": None,
        "extractor": None,
    }

    second = d["decisoes"][1]
    assert second["kind"] == "decisao"
    assert "deu provimento ao agravo regimental" in second["texto"]
    assert second["rtf"]["url"].endswith("texto=8857670")


# ----- parse_dje_detail: Acórdão variant (has EMENTA) ----------------------


def test_parse_dje_detail_acordao_variant_has_three_blocks_with_ementa_tag() -> None:
    d = parse_dje_detail(_load("HC_158802_dj204_acordao.html"))
    # Two session decisões + one EMENTA/acórdão block — all share the
    # <p>+<a> scaffolding; kind="ementa" is detected by the "EMENTA:" prefix.
    assert len(d["decisoes"]) == 3
    assert [b["kind"] for b in d["decisoes"]] == ["decisao", "decisao", "ementa"]


def test_parse_dje_detail_acordao_ementa_block_carries_full_text() -> None:
    d = parse_dje_detail(_load("HC_158802_dj204_acordao.html"))
    ementa = d["decisoes"][2]
    assert ementa["kind"] == "ementa"
    assert ementa["texto"].startswith("EMENTA: AGRAVO REGIMENTAL NA MEDIDA CAUTELAR")
    # Numbered paragraphs are in the same block, not separate entries.
    assert "1. A teor do art. 102, I" in ementa["texto"]
    assert "10. Agravo regimental provido" in ementa["texto"]
    assert ementa["rtf"]["url"].endswith("texto=8900854")
    assert ementa["rtf"]["text"] is None
    assert ementa["rtf"]["extractor"] is None
