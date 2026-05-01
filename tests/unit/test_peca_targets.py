"""collect_peca_targets — generic filter for substantive-doc PDF URLs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from judex.sweeps.peca_targets import PecaTarget, collect_peca_targets


def _write_item(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, ensure_ascii=False))


def _make_rec(
    *,
    classe: str = "HC",
    processo_id: int = 100000,
    impte_names: tuple[str, ...] = ("JOÃO DA SILVA",),
    relator: str = "MIN. EXEMPLO",
    andamentos: list | None = None,
) -> dict:
    return {
        "classe": classe,
        "processo_id": processo_id,
        "relator": relator,
        "partes": [{"tipo": "IMPTE.(S)", "nome": n} for n in impte_names],
        "andamentos": andamentos or [],
    }


def _andamento(desc: str, pdf_name: str = "doc.pdf") -> dict:
    """Build a v5 andamento stub — the doc-type label lives on link.tipo."""
    return {
        "link": {
            "tipo":      desc,
            "url":       f"https://portal.stf.jus.br/processos/{pdf_name}",
            "text":      None,
            "extractor": None,
        },
    }


def test_no_filters_collects_all_pdfs(tmp_path: Path) -> None:
    _write_item(tmp_path / "judex-mini_HC_1.json", _make_rec(
        processo_id=1,
        andamentos=[
            _andamento("DECISÃO MONOCRÁTICA", "a.pdf"),
            _andamento("DESPACHO", "b.pdf"),
        ],
    ))
    targets = collect_peca_targets([tmp_path])
    urls = {t.url for t in targets}
    assert len(targets) == 2
    assert urls == {
        "https://portal.stf.jus.br/processos/a.pdf",
        "https://portal.stf.jus.br/processos/b.pdf",
    }


def test_classe_filter(tmp_path: Path) -> None:
    _write_item(tmp_path / "judex-mini_HC_1.json", _make_rec(
        classe="HC", processo_id=1,
        andamentos=[_andamento("DECISÃO MONOCRÁTICA", "a.pdf")],
    ))
    _write_item(tmp_path / "judex-mini_RE_2.json", _make_rec(
        classe="RE", processo_id=2,
        andamentos=[_andamento("DECISÃO MONOCRÁTICA", "b.pdf")],
    ))
    targets = collect_peca_targets([tmp_path], classe="HC")
    assert len(targets) == 1
    assert targets[0].processo_id == 1


def test_impte_contains_filter(tmp_path: Path) -> None:
    _write_item(tmp_path / "judex-mini_HC_1.json", _make_rec(
        processo_id=1,
        impte_names=("ALBERTO ZACHARIAS TORON",),
        andamentos=[_andamento("DECISÃO MONOCRÁTICA", "a.pdf")],
    ))
    _write_item(tmp_path / "judex-mini_HC_2.json", _make_rec(
        processo_id=2,
        impte_names=("DEFENSORIA PÚBLICA",),
        andamentos=[_andamento("DECISÃO MONOCRÁTICA", "b.pdf")],
    ))
    targets = collect_peca_targets([tmp_path], impte_contains=["TORON"])
    assert {t.processo_id for t in targets} == {1}
    assert targets[0].context["impte_hits"] == ["TORON"]


def test_doc_types_filter(tmp_path: Path) -> None:
    _write_item(tmp_path / "judex-mini_HC_1.json", _make_rec(
        processo_id=1,
        andamentos=[
            _andamento("DECISÃO MONOCRÁTICA", "a.pdf"),
            _andamento("DESPACHO", "b.pdf"),
        ],
    ))
    targets = collect_peca_targets([tmp_path], doc_types=["DECISÃO MONOCRÁTICA"])
    assert len(targets) == 1
    assert targets[0].doc_type == "DECISÃO MONOCRÁTICA"


def test_relator_contains_filter(tmp_path: Path) -> None:
    _write_item(tmp_path / "judex-mini_HC_1.json", _make_rec(
        processo_id=1, relator="MIN. EDSON FACHIN",
        andamentos=[_andamento("DECISÃO MONOCRÁTICA", "a.pdf")],
    ))
    _write_item(tmp_path / "judex-mini_HC_2.json", _make_rec(
        processo_id=2, relator="MIN. ROSA WEBER",
        andamentos=[_andamento("DECISÃO MONOCRÁTICA", "b.pdf")],
    ))
    targets = collect_peca_targets([tmp_path], relator_contains=["FACHIN"])
    assert len(targets) == 1
    assert targets[0].processo_id == 1


def test_multiple_filters_and_together(tmp_path: Path) -> None:
    _write_item(tmp_path / "judex-mini_HC_1.json", _make_rec(
        classe="HC", processo_id=1,
        impte_names=("TORON",),
        andamentos=[
            _andamento("DECISÃO MONOCRÁTICA", "a.pdf"),
            _andamento("DESPACHO", "b.pdf"),
        ],
    ))
    targets = collect_peca_targets(
        [tmp_path],
        classe="HC", impte_contains=["TORON"],
        doc_types=["DECISÃO MONOCRÁTICA"],
    )
    assert len(targets) == 1
    assert targets[0].doc_type == "DECISÃO MONOCRÁTICA"


def test_exclude_doc_types_filter(tmp_path: Path) -> None:
    _write_item(tmp_path / "judex-mini_HC_1.json", _make_rec(
        processo_id=1,
        andamentos=[
            _andamento("DECISÃO MONOCRÁTICA", "a.pdf"),
            _andamento("DESPACHO", "b.pdf"),
        ],
    ))
    targets = collect_peca_targets([tmp_path], exclude_doc_types=["DESPACHO"])
    assert len(targets) == 1
    assert targets[0].doc_type == "DECISÃO MONOCRÁTICA"


def test_dedupes_by_url_across_files(tmp_path: Path) -> None:
    shared_url = "https://portal.stf.jus.br/processos/shared.pdf"
    shared_link = {"url": shared_url, "text": None}
    _write_item(tmp_path / "judex-mini_HC_1.json", _make_rec(
        processo_id=1,
        andamentos=[
            {"link": shared_link, "link_descricao": "DECISÃO MONOCRÁTICA"},
            {"link": shared_link, "link_descricao": "DECISÃO MONOCRÁTICA"},
        ],
    ))
    _write_item(tmp_path / "judex-mini_HC_2.json", _make_rec(
        processo_id=2,
        andamentos=[{"link": shared_link, "link_descricao": "DECISÃO MONOCRÁTICA"}],
    ))
    targets = collect_peca_targets([tmp_path])
    assert len(targets) == 1


def test_skips_unsupported_doc_formats(tmp_path: Path) -> None:
    # PDF + RTF are accepted; HTML / bare `.asp` tab pages are not.
    # STF's andamento RTFs end in `?...&ext=RTF` — no `.rtf` suffix —
    # so the filter has to recognise the query-string form too.
    _write_item(tmp_path / "judex-mini_HC_1.json", _make_rec(
        processo_id=1,
        andamentos=[
            {"link": {"url": "https://x.test/a.pdf",  "text": None}, "link_descricao": "DECISÃO MONOCRÁTICA"},
            {"link": {"url": "https://portal.stf.jus.br/processos/downloadTexto.asp?id=1&ext=RTF", "text": None}, "link_descricao": "DECISÃO DE JULGAMENTO"},
            {"link": {"url": "https://x.test/b.html", "text": None}, "link_descricao": "DECISÃO MONOCRÁTICA"},
        ],
    ))
    targets = collect_peca_targets([tmp_path])
    urls = {t.url for t in targets}
    assert urls == {
        "https://x.test/a.pdf",
        "https://portal.stf.jus.br/processos/downloadTexto.asp?id=1&ext=RTF",
    }


def test_collects_rtf_downloadTexto_urls(tmp_path: Path) -> None:
    # STF's `downloadTexto.asp?...&ext=RTF` serves `DECISÃO DE JULGAMENTO`
    # as RTF bytes. The extraction layer already handles RTF (striprtf),
    # but targets were historically filtered on `.pdf` suffix only and
    # silently dropped these. Regression guard: RTFs come through.
    rtf_url = "https://portal.stf.jus.br/processos/downloadTexto.asp?id=6799728&ext=RTF"
    _write_item(tmp_path / "judex-mini_HC_1.json", _make_rec(
        processo_id=1,
        andamentos=[
            {"link": {"url": rtf_url, "tipo": "DECISÃO DE JULGAMENTO"}},
        ],
    ))
    targets = collect_peca_targets([tmp_path])
    assert len(targets) == 1
    assert targets[0].url == rtf_url
    assert targets[0].doc_type == "DECISÃO DE JULGAMENTO"


def test_empty_impte_list_skips_filter(tmp_path: Path) -> None:
    # No impte_contains → all processes match regardless of parties.
    _write_item(tmp_path / "judex-mini_HC_1.json", _make_rec(
        processo_id=1,
        impte_names=("DEFENSORIA PÚBLICA",),
        andamentos=[_andamento("DECISÃO MONOCRÁTICA", "a.pdf")],
    ))
    targets = collect_peca_targets([tmp_path], impte_contains=[])
    assert len(targets) == 1


# ----- ADR-0001: surface-2 (sessao_virtual) + surface-3 (DJe) collection -----


def test_collects_sessao_virtual_documentos(tmp_path: Path) -> None:
    """Surface 2: sessao_virtual[].documentos[] URLs come through tagged
    with surface='sessao_virtual' and doc_type from documentos[].tipo
    (Voto / Relatório). Pre-ADR-0001 these were fetched synchronously
    inside varrer-processos and never appeared as targets."""
    rec = _make_rec(
        processo_id=1,
        andamentos=[_andamento("DECISÃO MONOCRÁTICA", "a.pdf")],
    )
    rec["sessao_virtual"] = [{
        "documentos": [
            {"tipo": "Voto",      "url": "https://digital.stf.jus.br/votos/v.pdf"},
            {"tipo": "Relatório", "url": "https://digital.stf.jus.br/relatorios/r.pdf"},
        ],
    }]
    _write_item(tmp_path / "judex-mini_HC_1.json", rec)

    targets = collect_peca_targets([tmp_path])
    by_url = {t.url: t for t in targets}
    assert "https://digital.stf.jus.br/votos/v.pdf" in by_url
    assert "https://digital.stf.jus.br/relatorios/r.pdf" in by_url
    assert by_url["https://digital.stf.jus.br/votos/v.pdf"].surface == "sessao_virtual"
    assert by_url["https://digital.stf.jus.br/votos/v.pdf"].doc_type == "Voto"
    assert by_url["https://digital.stf.jus.br/relatorios/r.pdf"].doc_type == "Relatório"


def test_skips_sessao_virtual_documentos_with_url_none(tmp_path: Path) -> None:
    """CLAUDE.md gotcha: sessao_virtual documentos with url=None are
    capture gaps, not inline-text documents. Must not produce a target."""
    rec = _make_rec(
        processo_id=1,
        andamentos=[_andamento("DECISÃO MONOCRÁTICA", "a.pdf")],
    )
    rec["sessao_virtual"] = [{
        "documentos": [
            {"tipo": "Voto", "url": None},
            {"tipo": "Voto", "url": "https://digital.stf.jus.br/votos/real.pdf"},
        ],
    }]
    _write_item(tmp_path / "judex-mini_HC_1.json", rec)

    targets = collect_peca_targets([tmp_path])
    sessao_targets = [t for t in targets if t.surface == "sessao_virtual"]
    assert [t.url for t in sessao_targets] == ["https://digital.stf.jus.br/votos/real.pdf"]


def test_collects_publicacoes_dje_decisoes_rtf(tmp_path: Path) -> None:
    """Surface 3: publicacoes_dje[].decisoes[].rtf URLs come through with
    surface='dje' and doc_type derived from decisoes[].kind (the controlled
    'decisao' / 'ementa' label, not the rtf Documento.tipo which the
    scraper leaves None on this surface)."""
    rec = _make_rec(
        processo_id=1,
        andamentos=[_andamento("DECISÃO MONOCRÁTICA", "a.pdf")],
    )
    rec["publicacoes_dje"] = [{
        "decisoes": [
            {
                "kind": "decisao",
                "texto": "Decisão monocrática …",
                "rtf": {"tipo": None, "url": "https://portal.stf.jus.br/processos/verDecisao.asp?id=1&ext=RTF"},
            },
            {
                "kind": "ementa",
                "texto": "Ementa: …",
                "rtf": {"tipo": None, "url": "https://portal.stf.jus.br/processos/verDecisao.asp?id=2&ext=RTF"},
            },
        ],
    }]
    _write_item(tmp_path / "judex-mini_HC_1.json", rec)

    targets = collect_peca_targets([tmp_path])
    dje_targets = [t for t in targets if t.surface == "dje"]
    assert len(dje_targets) == 2
    by_kind = {t.doc_type: t.url for t in dje_targets}
    assert by_kind["decisao"].endswith("&ext=RTF")
    assert by_kind["ementa"].endswith("&ext=RTF")


def test_skips_dje_decisoes_with_url_none(tmp_path: Path) -> None:
    """Mirror of the sessao_virtual capture-gap test for surface 3."""
    rec = _make_rec(
        processo_id=1,
        andamentos=[_andamento("DECISÃO MONOCRÁTICA", "a.pdf")],
    )
    rec["publicacoes_dje"] = [{
        "decisoes": [
            {"kind": "decisao", "texto": "…", "rtf": {"tipo": None, "url": None}},
        ],
    }]
    _write_item(tmp_path / "judex-mini_HC_1.json", rec)

    targets = collect_peca_targets([tmp_path])
    assert not any(t.surface == "dje" for t in targets)


def test_dedupes_url_across_surfaces(tmp_path: Path) -> None:
    """Apenso/conexão pattern: the same PARECER URL can appear under both
    an andamento and a sessao_virtual documento on the same case (or
    across cases). The sha1(url)-keyed cache dedupes silently; targets
    must mirror that — one PecaTarget per URL, keeping whichever surface
    walked first."""
    shared = "https://digital.stf.jus.br/shared/parecer.pdf"
    rec = _make_rec(
        processo_id=1,
        andamentos=[
            {"link": {"tipo": "PARECER", "url": shared}},
        ],
    )
    rec["sessao_virtual"] = [{
        "documentos": [{"tipo": "Voto", "url": shared}],
    }]
    _write_item(tmp_path / "judex-mini_HC_1.json", rec)

    targets = collect_peca_targets([tmp_path])
    same_url = [t for t in targets if t.url == shared]
    assert len(same_url) == 1


def test_filter_args_apply_only_to_andamento_surface(tmp_path: Path) -> None:
    """Andamento-tipo-specific filters (doc_types / exclude_doc_types)
    aren't meaningful for surface 2 / surface 3 — those use different
    discriminators (documentos[].tipo and decisoes[].kind respectively).
    The filter for now applies to surface-1 targets only; surface 2 and
    3 always come through. ADR-0001 flags surface-aware filtering as a
    follow-up question."""
    rec = _make_rec(
        processo_id=1,
        andamentos=[
            _andamento("DECISÃO MONOCRÁTICA", "a.pdf"),
            _andamento("DESPACHO",            "b.pdf"),
        ],
    )
    rec["sessao_virtual"] = [{
        "documentos": [{"tipo": "Voto", "url": "https://digital.stf.jus.br/votos/v.pdf"}],
    }]
    _write_item(tmp_path / "judex-mini_HC_1.json", rec)

    # doc_types restricts the andamento side; the sessao_virtual Voto
    # still comes through.
    targets = collect_peca_targets([tmp_path], doc_types=["DECISÃO MONOCRÁTICA"])
    surfaces = {t.surface for t in targets}
    assert surfaces == {"andamento", "sessao_virtual"}
    assert any(t.url.endswith("a.pdf") for t in targets)
    assert any(t.url.endswith("v.pdf") for t in targets)
    assert not any(t.url.endswith("b.pdf") for t in targets)
