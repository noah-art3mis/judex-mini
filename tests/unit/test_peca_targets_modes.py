"""Behavior tests for the three direct-selector target resolvers.

Shared by `baixar-pecas` and `extrair-pecas`. The fallback filter mode
(`collect_peca_targets`) is tested separately; this file covers
`targets_from_range`, `targets_from_csv`, and `targets_for_replay`.
"""

from __future__ import annotations

import json
from pathlib import Path

from judex.sweeps.peca_targets import (
    PecaTarget,
    targets_for_replay,
    targets_from_csv,
    targets_from_range,
)


def _write_case(
    path: Path,
    *,
    classe: str,
    processo_id: int,
    urls: list[tuple[str, str]],  # (url, doc_type)
    relator: str = "MIN. FULANO",
) -> None:
    """Minimal judex-mini_*.json fixture.

    We only populate the fields the resolvers actually touch —
    `classe`, `processo_id`, `andamentos[].link.{url,tipo}`, `relator`.
    Everything else is elided to keep the fixture readable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "classe": classe,
        "processo_id": processo_id,
        "relator": relator,
        "andamentos": [
            {"link": {"url": u, "tipo": t}} for u, t in urls
        ],
    }
    path.write_text(json.dumps(rec))


# ----- targets_from_range --------------------------------------------------


def test_range_walks_inclusive_bounds(tmp_path: Path) -> None:
    """inicio and fim are both inclusive — the range covers 4 cases."""
    for n in (100, 101, 102, 103, 104):
        _write_case(
            tmp_path / "HC" / f"judex-mini_HC_{n}.json",
            classe="HC", processo_id=n,
            urls=[(f"https://stf.test/{n}.pdf", "DECISÃO MONOCRÁTICA")],
        )

    out = targets_from_range("HC", 101, 103, roots=[tmp_path])

    assert sorted(t.url for t in out) == [
        "https://stf.test/101.pdf",
        "https://stf.test/102.pdf",
        "https://stf.test/103.pdf",
    ]


def test_range_lookup_does_not_recurse_into_subdirs(tmp_path: Path) -> None:
    """`_find_case_file` probes ``<root>/<classe>/<file>`` and
    ``<root>/<file>`` directly — it does **not** walk arbitrary
    subdirectories. A case file buried below the bucket level is
    invisible. This locks in the O(1)-per-pid lookup contract:
    regressing to ``rglob`` would make this test pass (because rglob
    finds the file) but balloon baixar-pecas startup at sharded
    scale, which is exactly what we just fixed.
    """
    # File buried deeper than the per-classe bucket — only an rglob
    # would find it.
    buried = tmp_path / "HC" / "extra" / "nested" / "judex-mini_HC_100.json"
    _write_case(
        buried,
        classe="HC", processo_id=100,
        urls=[("https://stf.test/100.pdf", "DECISÃO")],
    )

    out = targets_from_range("HC", 100, 100, roots=[tmp_path])

    assert out == [], (
        "buried case file should be invisible to the direct-probe "
        "lookup; finding it implies a regression to rglob"
    )


def test_range_skips_missing_case_files(tmp_path: Path) -> None:
    """Gaps in the scraped range don't raise — they're silently absent.

    The preview surfaces the `targets resolved: X` count so the user
    sees how many case files the resolver actually found.
    """
    _write_case(
        tmp_path / "HC" / "judex-mini_HC_100.json",
        classe="HC", processo_id=100,
        urls=[("https://stf.test/100.pdf", "DECISÃO")],
    )
    # Numbers 101, 102 intentionally missing.

    out = targets_from_range("HC", 100, 102, roots=[tmp_path])
    assert [t.url for t in out] == ["https://stf.test/100.pdf"]


def test_range_filters_to_supported_doc_urls(tmp_path: Path) -> None:
    """PDF + RTF URLs are collected; HTML and linkless andamentos are
    skipped — parity with `collect_peca_targets`.
    """
    _write_case(
        tmp_path / "HC" / "judex-mini_HC_100.json",
        classe="HC", processo_id=100,
        urls=[
            ("https://stf.test/100.pdf", "DECISÃO"),
            ("https://stf.test/100.rtf", "DESPACHO"),
            ("https://stf.test/100.html", "CERTIDÃO"),
        ],
    )

    out = targets_from_range("HC", 100, 100, roots=[tmp_path])
    assert {t.url for t in out} == {
        "https://stf.test/100.pdf",
        "https://stf.test/100.rtf",
    }


def test_range_matches_start_end_filename_shape(tmp_path: Path) -> None:
    """Real case files are `judex-mini_HC_100-100.json` — the resolver
    must accept the `-<N>` suffix form in addition to the plain one.
    Missing this breaks every production invocation.
    """
    _write_case(
        tmp_path / "HC" / "judex-mini_HC_100-100.json",
        classe="HC", processo_id=100,
        urls=[("https://stf.test/100.pdf", "DECISÃO")],
    )

    out = targets_from_range("HC", 100, 100, roots=[tmp_path])
    assert [t.url for t in out] == ["https://stf.test/100.pdf"]


def test_range_accepts_v3_bare_string_link(tmp_path: Path) -> None:
    """Production v3 case files (the dominant on-disk shape) have
    `andamento.link` as a bare URL string and `link_descricao` as the
    doc type. Pre-v5 → v5 schema migration of case JSON hasn't been
    run corpus-wide, so resolvers MUST handle both shapes.
    """
    import json
    path = tmp_path / "HC" / "judex-mini_HC_100-100.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([
        {
            "classe": "HC", "processo_id": 100,
            "andamentos": [
                {
                    "index_num": 1,
                    "nome": "TRANSITADO EM JULGADO",
                    "link_descricao": "CERTIDÃO DE TRÂNSITO EM JULGADO",
                    "link": "https://portal.stf.jus.br/x.pdf",
                },
                {"index_num": 2, "nome": "BAIXA", "link": None},
            ],
        },
    ]))

    out = targets_from_range("HC", 100, 100, roots=[tmp_path])
    assert len(out) == 1
    assert out[0].url == "https://portal.stf.jus.br/x.pdf"
    assert out[0].doc_type == "CERTIDÃO DE TRÂNSITO EM JULGADO"


def test_range_accepts_list_wrapped_case_files(tmp_path: Path) -> None:
    """Some case files wrap records in a list (single-process dump from
    a range row). The resolver must iterate list entries, not silently
    skip them — otherwise hit-rate halves on the production corpus.
    """
    import json
    path = tmp_path / "HC" / "judex-mini_HC_100-100.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([
        {
            "classe": "HC", "processo_id": 100,
            "andamentos": [
                {"link": {"url": "https://stf.test/100.pdf", "tipo": "DECISÃO"}},
            ],
        },
    ]))

    out = targets_from_range("HC", 100, 100, roots=[tmp_path])
    assert [t.url for t in out] == ["https://stf.test/100.pdf"]


def test_range_populates_target_fields(tmp_path: Path) -> None:
    """PecaTarget carries processo_id, classe, doc_type from the case."""
    _write_case(
        tmp_path / "HC" / "judex-mini_HC_42.json",
        classe="HC", processo_id=42,
        urls=[("https://stf.test/42.pdf", "INTEIRO TEOR DO ACÓRDÃO")],
    )

    out = targets_from_range("HC", 42, 42, roots=[tmp_path])
    assert len(out) == 1
    assert out[0] == PecaTarget(
        url="https://stf.test/42.pdf",
        processo_id=42,
        classe="HC",
        doc_type="INTEIRO TEOR DO ACÓRDÃO",
        surface="andamento",
    )


# ----- targets_from_csv ----------------------------------------------------


def test_csv_resolves_listed_pairs(tmp_path: Path) -> None:
    """CSV columns are `classe,processo`; rows are resolved via the
    same case-file walk as `targets_from_range`.
    """
    _write_case(
        tmp_path / "HC" / "judex-mini_HC_100.json",
        classe="HC", processo_id=100,
        urls=[("https://stf.test/100.pdf", "DECISÃO")],
    )
    _write_case(
        tmp_path / "RE" / "judex-mini_RE_200.json",
        classe="RE", processo_id=200,
        urls=[("https://stf.test/200.pdf", "ACÓRDÃO")],
    )
    _write_case(
        tmp_path / "HC" / "judex-mini_HC_999.json",
        classe="HC", processo_id=999,
        urls=[("https://stf.test/999.pdf", "DECISÃO")],
    )

    csv_path = tmp_path / "alvos.csv"
    csv_path.write_text("classe,processo\nHC,100\nRE,200\n")

    out = targets_from_csv(csv_path, roots=[tmp_path])

    assert sorted(t.url for t in out) == [
        "https://stf.test/100.pdf",
        "https://stf.test/200.pdf",
    ]


# ----- targets_for_replay -------------------------------------------------


def test_replay_rehydrates_transient_target_fields(tmp_path: Path) -> None:
    """Re-retry reads the prior run's errors log and rebuilds PdfTargets.

    Crucially, the rehydrated target carries processo_id / classe /
    doc_type so the retry run records them back under the same
    structure — lose those and the report loses its groupings.
    """
    errors_path = tmp_path / "pdfs.errors.jsonl"
    errors_path.write_text(
        json.dumps({
            "url": "https://stf.test/a.pdf",
            "status": "http_error",
            "error": "HTTPError: 502 Bad Gateway",
            "http_status": 502,
            "processo_id": 100,
            "classe": "HC",
            "doc_type": "DECISÃO MONOCRÁTICA",
            "context": {"impte_hits": ["TORON"]},
        }) + "\n"
        + json.dumps({
            "url": "https://stf.test/b.pdf",
            "status": "provider_error",
            "error": "HTTPError: 502 Bad Gateway for url: fly.dev/extract",
            "processo_id": 101,
            "classe": "HC",
            "doc_type": "INTEIRO TEOR DO ACÓRDÃO",
            "context": {},
        }) + "\n"
    )

    out = targets_for_replay(errors_path, stage="extrair")
    # extrair stage: provider_error is transient, http_error rows
    # don't appear under extrair in the wild but are classified
    # `terminal` by the extrair classifier and filtered out.
    assert [t.url for t in out] == ["https://stf.test/b.pdf"]
    assert out[0] == PecaTarget(
        url="https://stf.test/b.pdf",
        processo_id=101,
        classe="HC",
        doc_type="INTEIRO TEOR DO ACÓRDÃO",
        context={},
    )

    # Same file, baixar stage: http_error 502 is transient, provider_error
    # is not a baixar status (terminal default).
    out_baixar = targets_for_replay(errors_path, stage="baixar")
    assert [t.url for t in out_baixar] == ["https://stf.test/a.pdf"]


def test_replay_drops_terminal_rows(tmp_path: Path) -> None:
    """Terminal rows (não_alocado, real 404, no_bytes) must not be
    replayed — they will fail again deterministically and burn retry
    budget. Pinned by the live HC 2026 backfill data: 903 varrer
    `fail` rows all classified terminal (não_alocado).
    """
    errors_path = tmp_path / "pdfs.errors.jsonl"
    errors_path.write_text(
        # Terminal: real 404, peça gone from STF.
        json.dumps({
            "url": "https://stf.test/gone.pdf",
            "status": "http_error",
            "error": "HTTPError: 404 Not Found",
            "http_status": 404,
        }) + "\n"
        # Transient: WAF 403.
        + json.dumps({
            "url": "https://stf.test/blocked.pdf",
            "status": "http_error",
            "error": "HTTPError: 403 Forbidden",
            "http_status": 403,
        }) + "\n"
    )

    out = targets_for_replay(errors_path, stage="baixar")
    assert [t.url for t in out] == ["https://stf.test/blocked.pdf"]


def test_replay_drops_cross_stage_rows(tmp_path: Path) -> None:
    """`no_bytes` rows surfaced by extrair are cross_stage — fixable
    by baixar-retry, not by re-running extrair on the same URL.
    Reported as count, not replayed.
    """
    errors_path = tmp_path / "pdfs.errors.jsonl"
    errors_path.write_text(
        json.dumps({
            "url": "https://stf.test/no-bytes.pdf",
            "status": "no_bytes",
            "error": "run baixar-pecas first",
        }) + "\n"
        + json.dumps({
            "url": "https://stf.test/fly-flake.pdf",
            "status": "provider_error",
            "error": "HTTPError: 502 Bad Gateway",
        }) + "\n"
    )

    out = targets_for_replay(errors_path, stage="extrair")
    assert [t.url for t in out] == ["https://stf.test/fly-flake.pdf"]


def test_replay_drops_cached_rows(tmp_path: Path) -> None:
    """baixar's errors.jsonl doubles as a state-snapshot of all non-ok
    rows; `cached` rows are terminal-ok (already in cache) and
    historically slipped through into replay, blowing up the target
    count by orders of magnitude. Status-aware filter must drop them.
    """
    errors_path = tmp_path / "pdfs.errors.jsonl"
    errors_path.write_text(
        json.dumps({"url": "https://stf.test/a.pdf", "status": "cached"}) + "\n"
        + json.dumps({"url": "https://stf.test/b.pdf", "status": "cached"}) + "\n"
        + json.dumps({
            "url": "https://stf.test/real-fail.pdf",
            "status": "empty_response",
            "error": "200 OK with empty body",
        }) + "\n"
    )

    out = targets_for_replay(errors_path, stage="baixar")
    assert [t.url for t in out] == ["https://stf.test/real-fail.pdf"]


def test_range_and_csv_collect_rtf_urls(tmp_path: Path) -> None:
    # Direct-selector resolvers (range + CSV) must surface RTF andamento
    # links the same as PDFs — the `.pdf`-only filter historically dropped
    # `DECISÃO DE JULGAMENTO` RTFs even though extraction supports them.
    rtf_url = "https://portal.stf.jus.br/processos/downloadTexto.asp?id=42&ext=RTF"
    pdf_url = "https://portal.stf.jus.br/processos/downloadPeca.asp?id=43&ext=.pdf"
    case = tmp_path / "judex-mini_HC_100-100.json"
    _write_case(case, classe="HC", processo_id=100, urls=[
        (pdf_url, "DECISÃO MONOCRÁTICA"),
        (rtf_url, "DECISÃO DE JULGAMENTO"),
    ])

    out_range = targets_from_range("HC", 100, 100, roots=[tmp_path])
    assert {t.url for t in out_range} == {pdf_url, rtf_url}
    assert any(t.doc_type == "DECISÃO DE JULGAMENTO" for t in out_range)

    csv_path = tmp_path / "alvos.csv"
    csv_path.write_text("classe,processo\nHC,100\n")
    out_csv = targets_from_csv(csv_path, roots=[tmp_path])
    assert {t.url for t in out_csv} == {pdf_url, rtf_url}


def test_replay_tolerates_blank_lines(tmp_path: Path) -> None:
    """Editor-added trailing newlines or re-concatenated log files
    must not break the resolver — skip blank lines silently.
    """
    errors_path = tmp_path / "pdfs.errors.jsonl"
    errors_path.write_text(
        json.dumps({
            "url": "https://stf.test/a.pdf",
            "status": "provider_error",
            "error": "HTTPError: 502",
        }) + "\n"
        + "\n"
        + json.dumps({
            "url": "https://stf.test/b.pdf",
            "status": "provider_error",
            "error": "HTTPError: 502",
        }) + "\n"
        + "   \n"
    )

    out = targets_for_replay(errors_path, stage="extrair")
    assert [t.url for t in out] == [
        "https://stf.test/a.pdf",
        "https://stf.test/b.pdf",
    ]
