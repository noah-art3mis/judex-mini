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

from judex.warehouse import builder


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


def _make_case(
    *, version: int = 8, classe: str = "HC", n: int = 1, **overrides,
) -> dict:
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
    if version >= 3:
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
    if version >= 8:
        base["_meta"] = {
            "schema_version": 8,
            "status_http": base.pop("status_http"),
            "extraido": base.pop("extraido"),
        }
        base.pop("schema_version", None)
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
    _write_case(cases, _make_case(version=1))
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
    _write_case(cases, _make_case(version=3, classe="ADI", n=100))
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
    _write_case(cases, _make_case(version=1, data_protocolo="07/11/2019"))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        iso = con.execute("SELECT data_protocolo_iso FROM cases").fetchone()[0]
    assert str(iso) == "2019-11-07"


def test_partes_one_row_per_entry(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _make_case())
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        rows = con.execute(
            "SELECT seq, tipo, nome FROM partes WHERE classe='HC' AND processo_id=1 ORDER BY seq"
        ).fetchall()
    assert rows == [(0, "IMPTE", "Fulano da Silva"), (1, "PROC", "Defensor Público")]


def test_andamentos_flatten_link_struct(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _make_case(andamentos=[
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
    _write_case(cases, _make_case(sessao_virtual=[
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
    _write_case(cases, _make_case(sessao_virtual=[
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
    _write_case(cases, _make_case(sessao_virtual=[
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
    _write_case(cases, _make_case(andamentos=[
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


def test_v8_warehouse_resolves_link_text_and_extractor_from_cache_when_json_is_null(tmp_path: Path) -> None:
    """v8: JSONs carry pointer-only Documentos (`text`/`extractor` both
    None). The warehouse must still surface the extracted text + extractor
    label by resolving sha1(url) against `pdf_cache_root`."""
    cases = tmp_path / "cases"
    pdfs = tmp_path / "pdf"
    url = "https://portal.stf.jus.br/processos/downloadPeca.asp?id=42&ext=.pdf"
    # Seed the cache: text body + extractor sidecar.
    sha1 = _write_pdf(pdfs, url, "full cached text body")
    (pdfs / f"{sha1}.extractor").write_text("mistral", encoding="utf-8")

    # v8-shape case JSON: link carries url only, text/extractor are None.
    _write_case(cases, _make_case(andamentos=[
        {
            "index_num": 0, "data": "16/03/2020", "nome": "DESPACHO",
            "complemento": None, "julgador": None, "link_descricao": None,
            "link": {"url": url, "text": None, "extractor": None, "tipo": "INTEIRO TEOR"},
        },
    ]))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=pdfs, output_path=out)

    with _connect(out) as con:
        row = con.execute(
            "SELECT link_text, link_extractor FROM andamentos WHERE seq=0"
        ).fetchone()
    assert row == ("full cached text body", "mistral")


def test_v8_warehouse_cache_wins_over_stale_inline_text(tmp_path: Path) -> None:
    """If a pre-v8 JSON still has inline text but the cache has a newer
    extracted body (e.g. re-OCR with a better provider), the cache wins.
    This is the whole point of making the cache canonical."""
    cases = tmp_path / "cases"
    pdfs = tmp_path / "pdf"
    url = "https://portal.stf.jus.br/processos/downloadPeca.asp?id=99&ext=.pdf"
    sha1 = _write_pdf(pdfs, url, "FRESH cache body (from re-OCR)")
    (pdfs / f"{sha1}.extractor").write_text("chandra", encoding="utf-8")

    # Stale inline text from a pre-v8 migration that pre-dates the re-OCR.
    _write_case(cases, _make_case(andamentos=[
        {
            "index_num": 0, "data": "16/03/2020", "nome": "DESPACHO",
            "complemento": None, "julgador": None, "link_descricao": None,
            "link": {"url": url, "text": "OLD inline text", "extractor": "pypdf_plain"},
        },
    ]))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=pdfs, output_path=out)

    with _connect(out) as con:
        row = con.execute(
            "SELECT link_text, link_extractor FROM andamentos WHERE seq=0"
        ).fetchone()
    assert row == ("FRESH cache body (from re-OCR)", "chandra")


def test_andamentos_link_extractor_null_on_v1_missing_field(tmp_path: Path) -> None:
    """Pre-v4 case JSONs don't carry link.extractor; builder must still
    write a row (NULL in link_extractor) rather than crashing."""
    cases = tmp_path / "cases"
    _write_case(cases, _make_case(andamentos=[
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
    _write_case(cases, _make_case(andamentos=[
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
    _write_case(cases, _make_case(andamentos=[
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


def test_pautas_v6_flatten(tmp_path: Path) -> None:
    """v6 — pautas list flattens to one row per entry; ISO `data`
    lands in both `data` (VARCHAR) and `data_iso` (DATE), mirroring
    the andamentos pattern."""
    import datetime

    cases = tmp_path / "cases"
    _write_case(cases, _make_case(pautas=[
        {
            "index": 2, "data": "2020-05-10", "nome": "PAUTA PUBLICADA",
            "complemento": "DJE 80", "julgador": "1ª TURMA",
        },
        {
            "index": 1, "data": "2020-06-15", "nome": "SESSÃO VIRTUAL",
            "complemento": None, "julgador": None,
        },
    ]))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        rows = con.execute(
            "SELECT seq, data, data_iso, nome, complemento, julgador "
            "FROM pautas WHERE classe='HC' AND processo_id=1 ORDER BY seq"
        ).fetchall()
    assert rows == [
        (0, "2020-05-10", datetime.date(2020, 5, 10), "PAUTA PUBLICADA", "DJE 80", "1ª TURMA"),
        (1, "2020-06-15", datetime.date(2020, 6, 15), "SESSÃO VIRTUAL", None, None),
    ]


def test_pautas_absent_or_empty_produces_no_rows(tmp_path: Path) -> None:
    """Pre-v6 cases lack the pautas key; shape-only migrated cases have
    pautas=None; v6 cases with no scheduled session have pautas=[].
    All three yield zero rows without crashing the builder."""
    cases = tmp_path / "cases"
    _write_case(cases, _make_case(n=1, pautas=None))
    _write_case(cases, _make_case(n=2, pautas=[]))
    c3 = _make_case(n=3)
    c3.pop("pautas", None)
    _write_case(cases, c3)
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        n = con.execute("SELECT COUNT(*) FROM pautas").fetchone()[0]
    assert n == 0


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
    _write_case(cases, _make_case(andamentos=[
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


def _dje_case(**overrides) -> dict:
    """Minimal v8 case with populated publicacoes_dje for warehouse tests."""
    base = _make_case(version=8, classe="HC", n=158802)
    base["publicacoes_dje"] = [
        {
            "numero": 204, "data": "2020-08-17",
            "secao": "Acórdãos", "subsecao": "Acórdãos 2ª Turma",
            "titulo": "AG.REG. NA MEDIDA CAUTELAR NO HABEAS CORPUS 158802",
            "detail_url": "https://portal.stf.jus.br/servicos/dje/verDiarioProcesso.asp?numDj=204",
            "incidente_linked": 5522739,
            "classe": "HC", "procedencia": "DISTRITO FEDERAL", "relator": "MIN. GILMAR MENDES",
            "partes": ["AGTE.(S) - MPF", "AGDO.(A/S) - FULANO"],
            "materia": ["DIREITO PROCESSUAL PENAL | Prisão Preventiva"],
            "decisoes": [
                {
                    "kind": "decisao",
                    "texto": "Decisão: curta sumário da sessão.",
                    "rtf": {
                        "tipo": "DJE",
                        "url": "https://portal.stf.jus.br/servicos/dje/verDecisao.asp?texto=8783507",
                        "text": None, "extractor": None,
                    },
                },
                {
                    "kind": "ementa",
                    "texto": "EMENTA: AGRAVO REGIMENTAL... (2 pages of reasoning)",
                    "rtf": {
                        "tipo": "DJE",
                        "url": "https://portal.stf.jus.br/servicos/dje/verDecisao.asp?texto=8900854",
                        "text": None, "extractor": None,
                    },
                },
            ],
        },
        {
            "numero": 126, "data": "2018-06-26",
            "secao": "Presidência", "subsecao": "Distribuição",
            "titulo": "HABEAS CORPUS 158802",
            "detail_url": "https://portal.stf.jus.br/servicos/dje/verDiarioProcesso.asp?numDj=126",
            "incidente_linked": 5494703,
            "classe": "HC", "procedencia": "RIO DE JANEIRO", "relator": "MIN. GILMAR MENDES",
            "partes": [], "materia": [],
            "decisoes": [],  # distribuição entries often have no RTF
        },
    ]
    base.update(overrides)
    return base


def test_publicacoes_dje_flattens_one_row_per_entry(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _dje_case())
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        rows = con.execute(
            "SELECT numero, data_iso, secao, subsecao, incidente_linked, "
            "procedencia FROM publicacoes_dje ORDER BY numero DESC"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0] == (204, __import__("datetime").date(2020, 8, 17),
                       "Acórdãos", "Acórdãos 2ª Turma", 5522739, "DISTRITO FEDERAL")
    assert rows[1][0] == 126  # 2018 distribuição
    assert rows[1][5] == "RIO DE JANEIRO"


def test_decisoes_dje_flattens_decisao_and_ementa_kinds(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _dje_case())
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        rows = con.execute(
            "SELECT dje_seq, dec_seq, kind, LEFT(texto, 20), rtf_url_sha1 IS NOT NULL "
            "FROM decisoes_dje ORDER BY dje_seq, dec_seq"
        ).fetchall()
    assert len(rows) == 2  # DJ 204 has 2 decisões; DJ 126 has none
    # Both rows are under publicacao seq=0 (DJ 204 is the first in reverse-chrono).
    assert [(r[0], r[1], r[2]) for r in rows] == [(0, 0, "decisao"), (0, 1, "ementa")]
    assert rows[0][3].startswith("Decisão: curta sum")
    assert rows[1][3].startswith("EMENTA: AGRAVO REGIM")
    # Every decisão carries a joinable sha1.
    assert all(r[4] for r in rows)


def test_decisoes_dje_rtf_text_resolved_from_cache(tmp_path: Path) -> None:
    """v8 resolver: decisoes_dje.rtf_text populates from peca_cache even
    when the JSON carries rtf.text=null."""
    cases = tmp_path / "cases"
    pdfs = tmp_path / "pdf"
    # Seed the cache for both RTF URLs.
    rtf_decisao_url = "https://portal.stf.jus.br/servicos/dje/verDecisao.asp?texto=8783507"
    rtf_ementa_url = "https://portal.stf.jus.br/servicos/dje/verDecisao.asp?texto=8900854"
    decisao_sha = _write_pdf(pdfs, rtf_decisao_url, "cached decisao body")
    (pdfs / f"{decisao_sha}.extractor").write_text("rtf", encoding="utf-8")
    ementa_sha = _write_pdf(pdfs, rtf_ementa_url, "cached EMENTA body with full reasoning")
    (pdfs / f"{ementa_sha}.extractor").write_text("rtf", encoding="utf-8")

    _write_case(cases, _dje_case())
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=pdfs, output_path=out)

    with _connect(out) as con:
        rows = con.execute(
            "SELECT kind, rtf_text, rtf_extractor "
            "FROM decisoes_dje ORDER BY dec_seq"
        ).fetchall()
    assert rows == [
        ("decisao", "cached decisao body", "rtf"),
        ("ementa", "cached EMENTA body with full reasoning", "rtf"),
    ]


def test_decisoes_dje_join_to_pdfs_by_rtf_sha1(tmp_path: Path) -> None:
    """A realistic cross-table query — join DJe decisões to the pdfs
    table by sha1(rtf.url) to pull extracted text stats."""
    cases = tmp_path / "cases"
    pdfs = tmp_path / "pdf"
    _write_pdf(pdfs, "https://portal.stf.jus.br/servicos/dje/verDecisao.asp?texto=8900854",
               "EMENTA body" * 100)
    _write_case(cases, _dje_case())
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=pdfs, output_path=out)

    with _connect(out) as con:
        # "Give me every ementa acórdão's char count."
        row = con.execute(
            "SELECT d.kind, p.n_chars "
            "FROM decisoes_dje d JOIN pdfs p ON d.rtf_url_sha1 = p.sha1 "
            "WHERE d.kind='ementa'"
        ).fetchone()
    assert row == ("ementa", len("EMENTA body" * 100))


def test_classes_filter_limits_ingest(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _make_case(classe="HC", n=1))
    _write_case(cases, _make_case(classe="ADI", n=10))
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
    _write_case(cases, _make_case(relator="MIN. FIRST"))
    out = tmp_path / "judex.duckdb"
    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    # Replace the case and rebuild
    for p in cases.rglob("*.json"):
        p.unlink()
    _write_case(cases, _make_case(relator="MIN. SECOND"))
    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        rows = con.execute("SELECT relator FROM cases").fetchall()
    assert rows == [("MIN. SECOND",)]


def test_atomic_write_leaves_no_tmp(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _make_case())
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    assert out.exists()
    tmp_leftovers = list(tmp_path.glob("*.tmp")) + list(tmp_path.glob(".*.tmp"))
    assert tmp_leftovers == []


def test_manifest_records_row_counts_and_commit(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _write_case(cases, _make_case())
    _write_case(cases, _make_case(classe="ADI", n=20))
    out = tmp_path / "judex.duckdb"

    builder.build(cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out)

    with _connect(out) as con:
        row = con.execute(
            "SELECT n_cases, n_andamentos, n_pdfs, classes, n_pautas FROM manifest"
        ).fetchone()
    assert row[0] == 2
    assert row[1] == 2               # one andamento per fixture
    assert row[2] == 0
    assert sorted(row[3]) == ["ADI", "HC"]
    assert row[4] == 0               # fixtures have no pautas


# --- build-stats validation (catch silent regressions) --------------------


def _healthy_case(n: int) -> dict:
    """A case that exercises every populated-rate field above its threshold,
    so a corpus of these alone produces zero validation warnings."""
    c = _make_case(n=n)
    c["sessao_virtual"] = [{
        "metadata": {"relator": "MIN. X"},
        "voto_relator": None, "votes": {},
        "documentos": [], "julgamento_item_titulo": "",
    }]
    c["pautas"] = [{
        "index": 0, "data": "2024-01-01", "nome": "PAUTA",
        "complemento": None, "julgador": None,
    }]
    c["publicacoes_dje"] = [{
        "seq": 0, "numero": 1, "data": "2024-01-02",
        "secao": "2ª Turma", "subsecao": "Sessão", "titulo": f"HC {n}",
        "detail_url": f"https://portal.stf.jus.br/dje?n={n}",
        "decisoes": [],
    }]
    return c


def test_build_stats_reports_population_rates(tmp_path: Path) -> None:
    """The build returns population rates for the key fields the builder
    knows how to track, so callers (and CI) can diff them across builds."""
    cases = tmp_path / "cases"
    for n in range(1, 11):
        _write_case(cases, _healthy_case(n))

    summary = builder.build(
        cases_root=cases, pdf_cache_root=tmp_path / "pdf",
        output_path=tmp_path / "out.duckdb",
    )

    rates = summary.population_rates
    # Every healthy case has partes + andamentos + pautas + sessao + DJe.
    assert rates["partes"] == 1.0
    assert rates["andamentos"] == 1.0
    assert rates["pautas"] == 1.0
    assert rates["sessao_virtual"] == 1.0
    assert rates["publicacoes_dje"] == 1.0


def test_build_stats_warns_when_dje_below_threshold(tmp_path: Path) -> None:
    """The canonical regression test: if `publicacoes_dje` population drops
    across the corpus (e.g. because STF changed the listing endpoint to
    JS-rendered and our parser now returns []), the builder must surface
    a warning. Prevents the 2026-04-21 silent-regression scenario where
    0/3118 cases had DJe and nobody noticed."""
    cases = tmp_path / "cases"
    for n in range(1, 21):
        c = _healthy_case(n)
        c["publicacoes_dje"] = []  # simulate the STF-migration regression
        _write_case(cases, c)

    summary = builder.build(
        cases_root=cases, pdf_cache_root=tmp_path / "pdf",
        output_path=tmp_path / "out.duckdb",
    )

    assert summary.population_rates["publicacoes_dje"] == 0.0
    # Warning must mention the field by name so grep-for-bug works.
    warnings_str = " ".join(summary.validation_warnings)
    assert "publicacoes_dje" in warnings_str
    # Other fields still healthy — their warnings must NOT fire.
    assert not any("partes" in w for w in summary.validation_warnings)


def test_build_strict_raises_on_validation_warning(tmp_path: Path) -> None:
    """Under --strict (for CI / scheduled rebuilds) a threshold miss is
    a hard failure, not just a warning line. Ad-hoc builds stay permissive."""
    cases = tmp_path / "cases"
    for n in range(1, 21):
        c = _healthy_case(n)
        c["publicacoes_dje"] = []
        _write_case(cases, c)

    import pytest
    with pytest.raises(builder.BuildValidationError) as excinfo:
        builder.build(
            cases_root=cases, pdf_cache_root=tmp_path / "pdf",
            output_path=tmp_path / "out.duckdb",
            strict=True,
        )
    assert "publicacoes_dje" in str(excinfo.value)


def test_build_strict_passes_when_all_thresholds_met(tmp_path: Path) -> None:
    """Healthy data under strict mode must not raise — strict only gates
    on threshold misses, not on merely having data."""
    cases = tmp_path / "cases"
    for n in range(1, 11):
        _write_case(cases, _healthy_case(n))

    summary = builder.build(
        cases_root=cases, pdf_cache_root=tmp_path / "pdf",
        output_path=tmp_path / "out.duckdb",
        strict=True,
    )
    assert summary.validation_warnings == []


def test_chunked_scan_preserves_counts_and_rates(
    tmp_path: Path, monkeypatch
) -> None:
    """The case-scan loop flushes rows to DuckDB in chunks to keep peak
    RAM bounded — this test shrinks the chunk size and writes enough
    cases to cross several chunk boundaries, then verifies the visible
    build output (row counts, population rates, manifest) matches what
    a single-chunk build would produce.

    Regression guard for the 2026-04-24 refactor that turned the
    list-accumulation build into a streamed chunked scan. Prevents
    chunk-boundary bugs like: double-counting across flushes, losing
    the last partial chunk, populated-case dedup breaking at a flush.
    """
    monkeypatch.setattr(builder, "_CHUNK_SIZE", 3)

    cases = tmp_path / "cases"
    # 10 cases across 4 chunks (3+3+3+1).
    for n in range(1, 11):
        _write_case(cases, _healthy_case(n))
    # One case with no partes — so the populated-cases set must dedup
    # correctly across chunks without over-counting.
    sparse = _healthy_case(99)
    sparse["partes"] = []
    _write_case(cases, sparse)

    out = tmp_path / "out.duckdb"
    summary = builder.build(
        cases_root=cases, pdf_cache_root=tmp_path / "pdf", output_path=out,
    )

    # Row counts: 11 cases × 2 partes/case, minus the 1 sparse case = 20.
    assert summary.n_cases == 11
    assert summary.n_partes == 20
    assert summary.n_andamentos == 11  # 1 per case
    assert summary.n_pautas == 11

    # Population rates: 10/11 cases have partes; everyone has the rest.
    assert summary.population_rates["partes"] == 10 / 11
    assert summary.population_rates["andamentos"] == 1.0
    assert summary.population_rates["pautas"] == 1.0
    assert summary.population_rates["sessao_virtual"] == 1.0
    assert summary.population_rates["publicacoes_dje"] == 1.0

    # DB state mirrors the summary.
    with _connect(out) as con:
        assert con.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 11
        assert con.execute("SELECT COUNT(*) FROM partes").fetchone()[0] == 20
        assert con.execute("SELECT COUNT(*) FROM andamentos").fetchone()[0] == 11
        # Manifest written once, not per chunk.
        assert con.execute("SELECT COUNT(*) FROM manifest").fetchone()[0] == 1
        n_cases_manifest, n_partes_manifest = con.execute(
            "SELECT n_cases, n_partes FROM manifest"
        ).fetchone()
        assert n_cases_manifest == 11
        assert n_partes_manifest == 20
