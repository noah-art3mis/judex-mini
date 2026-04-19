"""DuckDB warehouse builder.

Reads case JSON + PDF text cache and produces a single .duckdb file
with flat analytical tables. Full-rebuild on every invocation (no
incremental logic in v1).

Schema-version drift: most production case JSONs predate the v3
schema bump and lack `schema_version`, `url`, `data_protocolo_iso`,
`status_http`, and `outcome` as a dict. The builder handles both
shapes — these tests pin that behavior.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import duckdb

from src.warehouse import builder


def _write_case(root: Path, item: dict) -> None:
    classe = item["classe"]
    n = item["processo_id"]
    d = root / classe
    d.mkdir(parents=True, exist_ok=True)
    (d / f"judex-mini_{classe}_{n}.json").write_text(json.dumps([item]))


def _write_pdf(cache: Path, url: str, text: str, *, with_elements: bool = False) -> str:
    cache.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha1(url.encode()).hexdigest()
    (cache / f"{sha}.txt.gz").write_bytes(gzip.compress(text.encode("utf-8")))
    if with_elements:
        (cache / f"{sha}.elements.json.gz").write_bytes(
            gzip.compress(json.dumps([{"type": "NarrativeText", "text": text}]).encode())
        )
    return sha


def _v1_case(classe: str = "HC", n: int = 1, **overrides) -> dict:
    base = {
        "incidente": 12345,
        "classe": classe,
        "processo_id": n,
        "numero_unico": f"0000{n}-00.2020.1.00.0000",
        "meio": "ELETRONICO",
        "publicidade": "PUBLICO",
        "badges": ["BADGE-A"],
        "assuntos": ["Habeas corpus"],
        "data_protocolo": "15/03/2020",
        "orgao_origem": "STJ",
        "origem": "SP",
        "numero_origem": ["123"],
        "volumes": 1,
        "folhas": 50,
        "apensos": 0,
        "relator": "MIN. TESTE",
        "primeiro_autor": "Fulano",
        "partes": [
            {"index": 0, "tipo": "IMPTE", "nome": "Fulano da Silva"},
            {"index": 1, "tipo": "PROC", "nome": "Defensor Público"},
        ],
        "andamentos": [
            {
                "index_num": 0, "data": "16/03/2020", "nome": "RECEBIMENTO",
                "complemento": None, "julgador": None, "link_descricao": None, "link": None,
            },
        ],
        "sessao_virtual": [],
        "deslocamentos": [], "peticoes": [], "recursos": [], "pautas": None,
        "outcome": "pending",
        "status": 200,
        "extraido": "2026-04-01T12:00:00",
        "html": "<html/>",
    }
    base.update(overrides)
    return base


def _v3_case(classe: str = "ADI", n: int = 100, **overrides) -> dict:
    base = _v1_case(classe=classe, n=n)
    base.pop("status", None)
    base.pop("html", None)
    base.update({
        "schema_version": 3,
        "url": f"https://portal.stf.jus.br/processos/detalhe.asp?incidente={base['incidente']}",
        "data_protocolo_iso": "2020-03-15",
        "status_http": 200,
        "outcome": {
            "verdict": "granted",
            "source": "sessao_virtual",
            "source_index": 0,
            "date_iso": "2020-06-01",
        },
    })
    base.update(overrides)
    return base


def _connect(db: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db), read_only=True)


def test_empty_build_creates_db_with_manifest(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    cases.mkdir()
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    out = tmp_path / "judex.duckdb"

    summary = builder.build(cases_root=cases, pdf_cache_root=pdfs, output_path=out)

    assert out.exists()
    with _connect(out) as con:
        manifest_rows = con.execute("SELECT COUNT(*) FROM manifest").fetchone()[0]
        cases_rows = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    assert manifest_rows == 1
    assert cases_rows == 0
    assert summary.n_cases == 0


def test_v1_case_flattens_correctly(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _v1_case())
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        row = con.execute(
            "SELECT classe, processo_id, incidente, relator, schema_version, "
            "outcome_verdict, outcome_source, status_http, url "
            "FROM cases WHERE classe='HC' AND processo_id=1"
        ).fetchone()
    classe, pid, inc, relator, sv, oc_v, oc_s, st, url = row
    assert (classe, pid, inc, relator) == ("HC", 1, 12345, "MIN. TESTE")
    assert sv == 1                        # default for v1 cases
    assert oc_v == "pending"              # bare-string outcome split to verdict
    assert oc_s is None                   # no OutcomeInfo source in v1
    assert st == 200                      # fell back from `status`
    assert url is None                    # v1 has no canonical url


def test_v3_case_unpacks_outcome_dict(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _v3_case())
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        row = con.execute(
            "SELECT outcome_verdict, outcome_source, outcome_source_index, "
            "outcome_date_iso, url, data_protocolo_iso, schema_version "
            "FROM cases WHERE classe='ADI' AND processo_id=100"
        ).fetchone()
    assert row[0] == "granted"
    assert row[1] == "sessao_virtual"
    assert row[2] == 0
    assert str(row[3]) == "2020-06-01"
    assert row[4].startswith("https://portal.stf.jus.br/")
    assert str(row[5]) == "2020-03-15"
    assert row[6] == 3


def test_data_protocolo_iso_derived_from_ddmmyyyy_when_missing(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _v1_case(data_protocolo="07/11/2019"))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        iso = con.execute("SELECT data_protocolo_iso FROM cases").fetchone()[0]
    assert str(iso) == "2019-11-07"


def test_partes_one_row_per_entry(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _v1_case())
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        rows = con.execute(
            "SELECT seq, tipo, nome FROM partes WHERE classe='HC' AND processo_id=1 ORDER BY seq"
        ).fetchall()
    assert rows == [(0, "IMPTE", "Fulano da Silva"), (1, "PROC", "Defensor Público")]


def test_andamentos_flatten_link_struct(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _v1_case(andamentos=[
        {
            "index_num": 0, "data": "16/03/2020", "nome": "DESPACHO",
            "complemento": None, "julgador": "Min. X", "link_descricao": "Ver",
            "link": {"url": "https://portal.stf.jus.br/peca.pdf", "text": None},
        },
    ]))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        row = con.execute(
            "SELECT data_iso, nome, julgador, link_url, link_url_sha1 FROM andamentos"
        ).fetchone()
    assert str(row[0]) == "2020-03-16"
    assert row[1] == "DESPACHO"
    assert row[2] == "Min. X"
    assert row[3] == "https://portal.stf.jus.br/peca.pdf"
    assert row[4] == hashlib.sha1(row[3].encode()).hexdigest()


def test_sessao_documentos_split_text_vs_url(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _v1_case(sessao_virtual=[
        {
            "metadata": {},
            "voto_relator": "",
            "votes": {},
            "documentos": {
                "Relatório": "Texto do relatório",
                "Voto": "https://sistemas.stf.jus.br/repgeral/voto.pdf",
            },
        },
    ]))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        rows = con.execute(
            "SELECT doc_type, text IS NOT NULL, url IS NOT NULL, extractor "
            "FROM documentos ORDER BY doc_type"
        ).fetchall()
    assert rows == [
        ("Relatório", True, False, None),
        ("Voto", False, True, None),
    ]


def test_sessao_documentos_v2_dict_of_dict_shape(tmp_path: Path) -> None:
    """v2/v3 — documentos is dict[tipo, {url, text}]."""
    cases = tmp_path / "cases"
    _write_case(cases, _v1_case(sessao_virtual=[
        {
            "metadata": {}, "voto_relator": "", "votes": {},
            "documentos": {
                "Relatório": {
                    "url": "https://sistemas.stf.jus.br/repgeral/voto.pdf",
                    "text": "Texto extraído do relatório",
                },
                "Voto": {
                    "url": "https://sistemas.stf.jus.br/repgeral/voto2.pdf",
                    "text": None,
                },
            },
        },
    ]))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        rows = con.execute(
            "SELECT doc_type, text, url IS NOT NULL, url_sha1 IS NOT NULL "
            "FROM documentos ORDER BY doc_type"
        ).fetchall()
    assert rows == [
        ("Relatório", "Texto extraído do relatório", True, True),
        ("Voto", None, True, True),
    ]


def test_sessao_documentos_v4_list_shape_preserves_duplicates(tmp_path: Path) -> None:
    """v4 — documentos is list[{tipo, url, text, extractor}]; duplicate tipos
    must survive the flatten, disambiguated by doc_seq."""
    cases = tmp_path / "cases"
    _write_case(cases, _v1_case(sessao_virtual=[
        {
            "metadata": {}, "voto_relator": "", "votes": {},
            "documentos": [
                {
                    "tipo": "Voto",
                    "url": "https://sistemas.stf.jus.br/repgeral/voto1.pdf",
                    "text": "Voto do relator",
                    "extractor": "pypdf_plain",
                },
                {
                    "tipo": "Voto",            # duplicate tipo — legal in v4
                    "url": "https://sistemas.stf.jus.br/repgeral/voto2.pdf",
                    "text": None,
                    "extractor": "chandra",
                },
                {
                    "tipo": "Relatório",
                    "url": "https://sistemas.stf.jus.br/repgeral/rel.pdf",
                    "text": "Relatório",
                    "extractor": "rtf",
                },
            ],
        },
    ]))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        rows = con.execute(
            "SELECT doc_seq, doc_type, extractor, text "
            "FROM documentos WHERE session_idx = 0 ORDER BY doc_seq"
        ).fetchall()
    assert rows == [
        (0, "Voto",      "pypdf_plain", "Voto do relator"),
        (1, "Voto",      "chandra",     None),
        (2, "Relatório", "rtf",         "Relatório"),
    ]


def test_andamentos_link_extractor_propagates(tmp_path: Path) -> None:
    """v4 — AndamentoLink.extractor lands in the warehouse so provenance
    queries (e.g. `WHERE link_extractor = 'unstructured'`) work."""
    cases = tmp_path / "cases"
    _write_case(cases, _v1_case(andamentos=[
        {
            "index_num": 0, "data": "16/03/2020", "nome": "DESPACHO",
            "complemento": None, "julgador": None, "link_descricao": None,
            "link": {
                "url": "https://portal.stf.jus.br/a.pdf",
                "text": "texto extraído",
                "extractor": "unstructured",
            },
        },
        {
            "index_num": 1, "data": "17/03/2020", "nome": "RTF",
            "complemento": None, "julgador": None, "link_descricao": None,
            "link": {
                "url": "https://portal.stf.jus.br/downloadTexto.asp?id=1&ext=RTF",
                "text": "corpo",
                "extractor": "rtf",
            },
        },
        {
            # null extractor — unextracted link, most common case
            "index_num": 2, "data": "18/03/2020", "nome": "RECEBIMENTO",
            "complemento": None, "julgador": None, "link_descricao": None,
            "link": {
                "url": "https://portal.stf.jus.br/b.pdf",
                "text": None,
                "extractor": None,
            },
        },
    ]))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        rows = con.execute(
            "SELECT nome, link_extractor FROM andamentos ORDER BY seq"
        ).fetchall()
    assert rows == [
        ("DESPACHO",    "unstructured"),
        ("RTF",         "rtf"),
        ("RECEBIMENTO", None),
    ]


def test_andamentos_link_extractor_null_on_v1_missing_field(tmp_path: Path) -> None:
    """Pre-v4 case JSONs don't carry link.extractor; builder must still
    write a row (NULL in link_extractor) rather than crashing."""
    cases = tmp_path / "cases"
    _write_case(cases, _v1_case(andamentos=[
        {
            "index_num": 0, "data": "16/03/2020", "nome": "DESPACHO",
            "complemento": None, "julgador": None, "link_descricao": None,
            "link": {"url": "https://portal.stf.jus.br/a.pdf", "text": None},
        },
    ]))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        row = con.execute(
            "SELECT link_url, link_extractor FROM andamentos"
        ).fetchone()
    assert row == ("https://portal.stf.jus.br/a.pdf", None)


def test_andamentos_v5_link_tipo_read_from_link_struct(tmp_path: Path) -> None:
    """v5 — anchor label lives in `link.tipo`, not as a sibling field.
    No `link_descricao` key on the andamento at all in fresh v5 scrapes."""
    cases = tmp_path / "cases"
    _write_case(cases, _v1_case(andamentos=[
        # v5 shape: no link_descricao sibling; tipo is inside link
        {
            "index_num": 0, "data": "16/03/2020", "nome": "DESPACHO",
            "complemento": None, "julgador": None,
            "link": {
                "tipo": "Ver peça",
                "url": "https://portal.stf.jus.br/a.pdf",
                "text": None,
                "extractor": None,
            },
        },
    ]))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        row = con.execute(
            "SELECT link_tipo, link_url FROM andamentos"
        ).fetchone()
    assert row == ("Ver peça", "https://portal.stf.jus.br/a.pdf")


def test_andamentos_v5_link_text_only_anchor(tmp_path: Path) -> None:
    """v5 option-2 behavior: anchor with visible label but no href must
    round-trip as `link={tipo, url=None, text=None, extractor=None}` —
    the row survives, url/sha1 are NULL, link_tipo carries the label."""
    cases = tmp_path / "cases"
    _write_case(cases, _v1_case(andamentos=[
        {
            "index_num": 0, "data": "16/03/2020", "nome": "DECISÃO",
            "complemento": None, "julgador": None,
            "link": {
                "tipo": "Ver inteiro teor",
                "url": None,
                "text": None,
                "extractor": None,
            },
        },
    ]))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        row = con.execute(
            "SELECT link_tipo, link_url, link_url_sha1, link_text FROM andamentos"
        ).fetchone()
    assert row == ("Ver inteiro teor", None, None, None)


def test_pdfs_ingested_with_sha1_and_n_chars(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    pdfs = tmp_path / "pdf"
    _write_pdf(pdfs, "https://portal.stf.jus.br/peca.pdf", "Corpo do despacho\n" * 10, with_elements=True)
    _write_pdf(pdfs, "https://portal.stf.jus.br/other.pdf", "Short")
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=pdfs, output_path=out)

    with _connect(out) as con:
        rows = con.execute(
            "SELECT COUNT(*), SUM(n_chars), SUM(CAST(has_elements AS INT)) FROM pdfs"
        ).fetchone()
    assert rows[0] == 2
    assert rows[1] > 0
    assert rows[2] == 1


def test_pdf_cache_joins_to_andamento_by_sha1(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    pdfs = tmp_path / "pdf"
    url = "https://portal.stf.jus.br/peca.pdf"
    _write_pdf(pdfs, url, "Body text")
    _write_case(cases, _v1_case(andamentos=[
        {"index_num": 0, "data": "16/03/2020", "nome": "DESPACHO",
         "complemento": None, "julgador": None, "link_descricao": None,
         "link": {"url": url, "text": None}},
    ]))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=pdfs, output_path=out)

    with _connect(out) as con:
        row = con.execute(
            "SELECT a.nome, p.n_chars "
            "FROM andamentos a JOIN pdfs p ON a.link_url_sha1 = p.sha1"
        ).fetchone()
    assert row == ("DESPACHO", len("Body text"))


def test_classes_filter_limits_ingest(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _v1_case(classe="HC", n=1))
    _write_case(cases, _v1_case(classe="ADI", n=10))
    out = tmp_path / "judex.duckdb"

    builder.build(
        cases_root=cases, pdf_cache_root=tmp_path / "pdf",
        output_path=out, classes=["HC"],
    )

    with _connect(out) as con:
        classes_seen = [r[0] for r in con.execute(
            "SELECT DISTINCT classe FROM cases ORDER BY classe"
        ).fetchall()]
    assert classes_seen == ["HC"]


def test_rebuild_overwrites_prior_content(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _v1_case(relator="MIN. FIRST"))
    out = tmp_path / "judex.duckdb"
    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    # Replace the case and rebuild
    for p in cases.rglob("*.json"):
        p.unlink()
    _write_case(cases, _v1_case(relator="MIN. SECOND"))
    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        rows = con.execute("SELECT relator FROM cases").fetchall()
    assert rows == [("MIN. SECOND",)]


def test_atomic_write_leaves_no_tmp(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _v1_case())
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    assert out.exists()
    tmp_leftovers = list(tmp_path.glob("*.tmp")) + list(tmp_path.glob(".*.tmp"))
    assert tmp_leftovers == []


def test_manifest_records_row_counts_and_commit(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _v1_case())
    _write_case(cases, _v1_case(classe="ADI", n=20))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        row = con.execute(
            "SELECT n_cases, n_andamentos, n_pdfs, classes FROM manifest"
        ).fetchone()
    assert row[0] == 2
    assert row[1] == 2               # one andamento per fixture
    assert row[2] == 0
    assert sorted(row[3]) == ["ADI", "HC"]
