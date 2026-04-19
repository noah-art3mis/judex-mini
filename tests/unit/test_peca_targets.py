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
