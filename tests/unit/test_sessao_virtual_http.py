"""HTTP port of sessao_virtual extraction.

The Selenium path clicks through nested collapses and reads the rendered
DOM; the HTTP port instead calls the JSON endpoints that the rendered
template's scripts would have called and assembles the same output
shape. These tests pin down the Sessão branch (the more common one)
using captured JSON for ADI 2820.
"""

from __future__ import annotations

import json
from pathlib import Path

from judex.scraping.extraction.sessao import (
    extract_sessao_virtual_from_json,
    parse_oi_listing,
    parse_sessao_virtual,
    parse_tema,
)
from judex.scraping.scraper import _extract_tema_from_abasessao

FIX = Path(__file__).parent.parent / "fixtures" / "sessao_virtual"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_parse_oi_listing_yields_object_incidente_ids() -> None:
    ois = parse_oi_listing(_load("oi_2083816.json"))

    assert [o["id"] for o in ois] == [2083816, 6702594]
    assert ois[0]["identificacaoCompleta"] == "AÇÃO DIRETA DE INCONSTITUCIONALIDADE 2820"
    assert ois[1]["identificacaoCompleta"] == (
        "EMB.DECL. NA AÇÃO DIRETA DE INCONSTITUCIONALIDADE 2820"
    )


def test_parse_sessao_virtual_first_entry_matches_fixture_shape() -> None:
    entries = parse_sessao_virtual(_load("sv_2083816.json"))

    assert len(entries) == 2
    first = entries[0]
    # v6: ASCII snake_case keys; dates normalized to ISO 8601 on emit.
    assert first["metadata"] == {
        "relator": "MIN. NUNES MARQUES",
        "orgao_julgador": "Plenário",
        "lista": "25-2023",
        "processo": "ADI 2820",
        "data_inicio": "2023-02-24",
        "data_fim_prevista": "2023-03-03",
    }
    assert first["voto_relator"].startswith("Voto do Relator: Conheço desta ação")
    assert first["votes"] == {
        "relator": ["MIN. NUNES MARQUES"],
        "acompanha_relator": ["MIN. ALEXANDRE DE MORAES"],
        "diverge_relator": [],
        "acompanha_divergencia": [],
        "pedido_vista": ["MIN. CÁRMEN LÚCIA"],
    }
    assert first["julgamento_item_titulo"] == (
        "AÇÃO DIRETA DE INCONSTITUCIONALIDADE 2820"
    )
    # v4: documentos is a list of {tipo, url, text, extractor}; `tipo`
    # values appear in STF order, duplicates allowed.
    docs = first["documentos"]
    assert isinstance(docs, list)
    tipos = [d["tipo"] for d in docs]
    assert "Relatório" in tipos
    assert "Voto" in tipos
    relatorio = next(d for d in docs if d["tipo"] == "Relatório")
    assert relatorio["url"].startswith("https://")
    assert relatorio["text"] is None
    assert relatorio["extractor"] is None


def test_parse_sessao_virtual_strips_html_from_voto_relator() -> None:
    """STF's `cabecalho` field can be an HTML fragment (<p><span>…) or
    plain text with entities. Both should become clean text."""
    payload = json.dumps([
        {
            "objetoIncidente": {"identificacao": "HC 158802", "identificacaoCompleta": ""},
            "listasJulgamento": [
                {
                    "nomeLista": "137-2020",
                    "ministroRelator": {"descricao": "MIN. GILMAR MENDES"},
                    "sessao": {"colegiado": {"descricao": "Segunda Turma"}},
                    "cabecalho": (
                        '<p><span style="font-size: 13pt; font-family: '
                        '&quot;Palatino Linotype&quot;, serif;">'
                        'Nega agravo regimental do MPF.&nbsp;</span></p>'
                    ),
                    "votos": [],
                }
            ],
        }
    ])

    entries = parse_sessao_virtual(payload)
    assert entries[0]["voto_relator"] == "Nega agravo regimental do MPF."


def test_parse_sessao_virtual_second_entry_has_voto_vista() -> None:
    """The second session had a vista ministro who later voted — Voto Vista
    should appear in documentos (v4 list shape)."""
    entries = parse_sessao_virtual(_load("sv_2083816.json"))

    second = entries[1]
    # v6: ASCII snake_case + ISO date.
    assert second["metadata"]["data_inicio"] == "2023-05-26"
    assert "Voto Vista" in [d["tipo"] for d in second["documentos"]]


def test_extract_sessao_virtual_end_to_end_for_adi_2820() -> None:
    """Orchestrator composes oi listing + per-oi sessao_virtual calls."""
    fake_responses = {
        ("oi", 2083816): _load("oi_2083816.json"),
        ("sessaoVirtual", 2083816): _load("sv_2083816.json"),
        ("sessaoVirtual", 6702594): _load("sv_6702594.json"),
    }

    def fetcher(param: str, value: int) -> str:
        return fake_responses[(param, value)]

    result = extract_sessao_virtual_from_json(
        incidente=2083816, tema=None, fetcher=fetcher
    )

    assert len(result) == 3
    titles = [e["julgamento_item_titulo"] for e in result]
    assert titles[0] == "AÇÃO DIRETA DE INCONSTITUCIONALIDADE 2820"
    assert titles[2] == "EMB.DECL. NA AÇÃO DIRETA DE INCONSTITUCIONALIDADE 2820"
    # Every entry has the ADI shape.
    for entry in result:
        assert set(entry.keys()) >= {
            "metadata",
            "voto_relator",
            "votes",
            "documentos",
            "julgamento_item_titulo",
        }


def test_extract_sessao_virtual_empty_oi_returns_empty_list() -> None:
    """When no sessions exist (empty oi listing), return []."""
    fake_responses = {("oi", 999): "[]"}

    def fetcher(param: str, value: int) -> str:
        return fake_responses[(param, value)]

    result = extract_sessao_virtual_from_json(
        incidente=999, tema=None, fetcher=fetcher
    )

    assert result == []


def test_tema_number_extracted_from_abasessao_fragment() -> None:
    """The abaSessao template embeds ?tema=<N> in its AJAX URL when the
    process carries a repercussão-geral tema; empty otherwise."""
    html_with_tema = (
        '<script>url: "https://sistemas.stf.jus.br/repgeral/votacao?tema=1020",</script>'
    )
    html_without_tema = (
        '<script>url: "https://sistemas.stf.jus.br/repgeral/votacao?tema=",</script>'
    )

    assert _extract_tema_from_abasessao(html_with_tema) == 1020
    assert _extract_tema_from_abasessao(html_without_tema) is None


def test_extract_sessao_virtual_emits_pointer_only_documentos() -> None:
    """ADR-0001: case-scrape emits URL-only documentos. text and
    extractor are always None on disk; canonical text materialises via
    the bytes-first ``baixar-pecas`` + ``extrair-pecas`` pipeline."""
    fake_responses = {
        ("oi", 2083816): _load("oi_2083816.json"),
        ("sessaoVirtual", 2083816): _load("sv_2083816.json"),
        ("sessaoVirtual", 6702594): _load("sv_6702594.json"),
    }

    result = extract_sessao_virtual_from_json(
        incidente=2083816,
        tema=None,
        fetcher=lambda p, v: fake_responses[(p, v)],
    )

    # Every documento with a URL is pointer-only; no entry carries
    # inline text or an extractor label.
    documentos = [d for entry in result for d in entry["documentos"]]
    assert documentos, "fixture should yield at least one documento"
    assert any(d["url"] and d["url"].startswith("https://") for d in documentos)
    assert all(d["text"] is None and d["extractor"] is None for d in documentos)


def test_parse_tema_against_live_tema_1020_fixture() -> None:
    """Round-trip the parser against a captured live response for tema 1020.

    Guards against shape drift in the sistemas.stf.jus.br/repgeral/votacao
    endpoint (numeroTema/placar.ministro field names, scalar-vs-list on
    processoLeadingCase, etc.)."""
    result = parse_tema(_load("tema_1020.json"))

    assert len(result) == 1
    entry = result[0]
    assert entry["tipo"] == "tema"
    assert entry["tema"] == 1020
    assert entry["classe"] == "RE"
    assert entry["numero"] == 1167509
    assert entry["titulo"].startswith("Controvérsia alusiva")
    # 11 ministros voted (Plenário full); every one has the four vote fields.
    assert len(entry["votos"]) == 11
    for voto in entry["votos"]:
        assert set(voto.keys()) == {"ministro", "QC", "RG", "RJ"}
        assert voto["ministro"].startswith("MIN.")


def test_parse_tema_with_ministro_votes() -> None:
    """Minimal synthetic Tema response: one process, two ministros."""
    payload = {
        "package": {
            "repercussaoGeral": {
                "processoLeadingCase": {
                    "numeroTema": 1020,
                    "tituloTema": "Algum Tema",
                    "dataInicioJulgamento": "01/01/2023",
                    "dataFimPrevistaJulgamento": "10/01/2023",
                    "siglaClasse": "RE",
                    "numeroProcesso": "123456",
                    "relator": "MIN. X",
                    "placar": {
                        "ministro": [
                            {
                                "nomeMinistro": "MIN. A",
                                "votoQC": "SIM",
                                "votoRG": "SIM",
                                "votoRJ": "-",
                            },
                            {
                                "nomeMinistro": "MIN. B",
                                "votoQC": "SIM",
                                "votoRG": "NÃO",
                                "votoRJ": "-",
                            },
                        ]
                    },
                }
            }
        }
    }
    result = parse_tema(json.dumps(payload))

    assert len(result) == 1
    entry = result[0]
    assert entry["tipo"] == "tema"
    assert entry["tema"] == 1020
    assert entry["titulo"] == "Algum Tema"
    assert entry["julgamento_item_titulo"] == "Tema 1020 - Algum Tema"
    assert entry["votos"] == [
        {"ministro": "MIN. A", "QC": "SIM", "RG": "SIM", "RJ": "-"},
        {"ministro": "MIN. B", "QC": "SIM", "RG": "NÃO", "RJ": "-"},
    ]
