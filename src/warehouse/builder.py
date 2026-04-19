"""Full-rebuild warehouse builder.

Walks `data/cases/**/*.json` + `data/cache/pdf/*.txt.gz` and emits a
single `.duckdb` file with flat analytical tables. No incremental
logic — the whole thing rebuilds every run, which keeps the code
trivial (no UPSERT, no orphaned-row cleanup, no change-tracking
manifest) and stays well under a few minutes at current scale.

Schema-version tolerance: ~97 % of production case JSONs pre-date
the StfItem v3 schema bump and use `status` (not `status_http`),
lack `schema_version`/`url`/`data_protocolo_iso`, and carry a
bare-string or None `outcome` (not an `OutcomeInfo` dict). The
`_flatten_case` normalizer handles both shapes transparently.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import duckdb
import pyarrow as pa

from src.scraping.extraction._shared import to_iso


_SCHEMA_SQL = """
CREATE TABLE cases (
    classe                VARCHAR NOT NULL,
    processo_id           INTEGER NOT NULL,
    incidente             INTEGER,
    url                   VARCHAR,
    schema_version        INTEGER,
    numero_unico          VARCHAR,
    meio                  VARCHAR,
    publicidade           VARCHAR,
    badges                VARCHAR[],
    assuntos              VARCHAR[],
    data_protocolo        VARCHAR,
    data_protocolo_iso    DATE,
    orgao_origem          VARCHAR,
    origem                VARCHAR,
    numero_origem         VARCHAR[],
    volumes               INTEGER,
    folhas                INTEGER,
    apensos               INTEGER,
    relator               VARCHAR,
    primeiro_autor        VARCHAR,
    outcome_verdict       VARCHAR,
    outcome_source        VARCHAR,
    outcome_source_index  INTEGER,
    outcome_date_iso      DATE,
    status_http           INTEGER,
    extraido              TIMESTAMP,
    source_path           VARCHAR,
    source_mtime          TIMESTAMP,
    PRIMARY KEY (classe, processo_id)
);

CREATE TABLE partes (
    classe        VARCHAR NOT NULL,
    processo_id   INTEGER NOT NULL,
    seq           INTEGER NOT NULL,
    tipo          VARCHAR,
    nome          VARCHAR,
    PRIMARY KEY (classe, processo_id, seq)
);

CREATE TABLE andamentos (
    classe           VARCHAR NOT NULL,
    processo_id      INTEGER NOT NULL,
    seq              INTEGER NOT NULL,
    data             VARCHAR,
    data_iso         DATE,
    nome             VARCHAR,
    complemento      VARCHAR,
    julgador         VARCHAR,
    link_tipo        VARCHAR,
    link_url         VARCHAR,
    link_url_sha1    VARCHAR,
    link_text        VARCHAR,
    link_extractor   VARCHAR,
    PRIMARY KEY (classe, processo_id, seq)
);

CREATE TABLE documentos (
    classe        VARCHAR NOT NULL,
    processo_id   INTEGER NOT NULL,
    session_idx   INTEGER NOT NULL,
    doc_seq       INTEGER NOT NULL,
    doc_type      VARCHAR NOT NULL,
    text          VARCHAR,
    url           VARCHAR,
    url_sha1      VARCHAR,
    extractor     VARCHAR,
    PRIMARY KEY (classe, processo_id, session_idx, doc_seq)
);

CREATE TABLE pdfs (
    sha1          VARCHAR PRIMARY KEY,
    n_chars       INTEGER NOT NULL,
    has_elements  BOOLEAN NOT NULL,
    text          VARCHAR NOT NULL,
    cache_path    VARCHAR NOT NULL
);

CREATE TABLE manifest (
    built_at      TIMESTAMP NOT NULL,
    classes       VARCHAR[],
    n_cases       INTEGER,
    n_partes      INTEGER,
    n_andamentos  INTEGER,
    n_documentos  INTEGER,
    n_pdfs        INTEGER,
    build_wall_s  DOUBLE,
    judex_commit  VARCHAR
);

CREATE INDEX cases_relator_idx        ON cases (relator);
CREATE INDEX cases_autuacao_idx       ON cases (data_protocolo_iso);
CREATE INDEX cases_primeiro_autor_idx ON cases (primeiro_autor);
CREATE INDEX partes_nome_idx          ON partes (nome);
CREATE INDEX partes_tipo_idx          ON partes (tipo);
CREATE INDEX andamentos_sha1_idx      ON andamentos (link_url_sha1);
CREATE INDEX andamentos_nome_idx      ON andamentos (nome);
CREATE INDEX andamentos_extractor_idx ON andamentos (link_extractor);
CREATE INDEX documentos_sha1_idx      ON documentos (url_sha1);
CREATE INDEX documentos_extractor_idx ON documentos (extractor);
"""


@dataclass
class BuildSummary:
    n_cases: int
    n_partes: int
    n_andamentos: int
    n_documentos: int
    n_pdfs: int
    wall_s: float
    output_path: Path


def _load_case(path: Path) -> Optional[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw[0] if raw else None
    return raw if isinstance(raw, dict) else None


def _unpack_outcome(oc: Any) -> tuple[Optional[str], Optional[str], Optional[int], Optional[str]]:
    if oc is None:
        return (None, None, None, None)
    if isinstance(oc, str):
        return (oc, None, None, None)
    if isinstance(oc, dict):
        return (
            oc.get("verdict"),
            oc.get("source"),
            oc.get("source_index"),
            oc.get("date_iso"),
        )
    return (None, None, None, None)


def _flatten_case(item: dict, source: Path) -> dict:
    """Flatten across schema versions. v6 moves scrape metadata under
    `_meta` and replaces the DD/MM `data_protocolo` + `data_protocolo_iso`
    pair with a single ISO-valued `data_protocolo`. Pre-v6 files still
    carry the old shape — read from either."""
    meta = item.get("_meta") or {}
    raw_protocolo = item.get("data_protocolo")
    # v6: `data_protocolo` is ISO already; pre-v6 needs conversion.
    # Keep the raw string for the `data_protocolo` column (human-readable
    # DD/MM on old rows; ISO on v6 rows — it's a display column).
    iso = (
        item.get("data_protocolo_iso")
        or (raw_protocolo if raw_protocolo and "-" in (raw_protocolo or "") else None)
        or to_iso(raw_protocolo)
    )
    oc_v, oc_s, oc_i, oc_d = _unpack_outcome(item.get("outcome"))
    return {
        "classe":               item["classe"],
        "processo_id":          item["processo_id"],
        "incidente":            item.get("incidente"),
        "url":                  item.get("url"),
        "schema_version":       meta.get("schema_version", item.get("schema_version", 1)),
        "numero_unico":         item.get("numero_unico"),
        "meio":                 item.get("meio"),
        "publicidade":          item.get("publicidade"),
        "badges":               item.get("badges") or [],
        "assuntos":             item.get("assuntos") or [],
        "data_protocolo":       raw_protocolo,
        "data_protocolo_iso":   iso,
        "orgao_origem":         item.get("orgao_origem"),
        "origem":               item.get("origem"),
        "numero_origem":        item.get("numero_origem") or [],
        "volumes":              item.get("volumes"),
        "folhas":               item.get("folhas"),
        "apensos":              item.get("apensos"),
        "relator":              item.get("relator"),
        "primeiro_autor":       item.get("primeiro_autor"),
        "outcome_verdict":      oc_v,
        "outcome_source":       oc_s,
        "outcome_source_index": oc_i,
        "outcome_date_iso":     oc_d,
        "status_http":          meta.get("status_http", item.get("status_http", item.get("status"))),
        "extraido":             meta.get("extraido", item.get("extraido")),
        "source_path":          str(source),
        "source_mtime":         datetime.fromtimestamp(source.stat().st_mtime),
    }


def _flatten_partes(item: dict) -> list[dict]:
    out = []
    for seq, p in enumerate(item.get("partes") or []):
        out.append({
            "classe":      item["classe"],
            "processo_id": item["processo_id"],
            "seq":         seq,
            "tipo":        p.get("tipo"),
            "nome":        p.get("nome"),
        })
    return out


def _flatten_andamentos(item: dict) -> list[dict]:
    """Flatten andamentos into warehouse rows.

    v5+: `link = {tipo, url, text, extractor}` or None.
    v6: the `data` field carries ISO 8601 directly; pre-v6 files carry
    DD/MM with a sibling `data_iso`. We read from either.
    """
    out = []
    for seq, a in enumerate(item.get("andamentos") or []):
        link = a.get("link") if isinstance(a.get("link"), dict) else {}
        url = link.get("url")
        text = link.get("text")
        extractor = link.get("extractor")
        tipo = link.get("tipo") if link else None
        raw_data = a.get("data")
        # v6: data is already ISO. Pre-v6: data_iso sibling holds it.
        iso = (
            a.get("data_iso")
            or (raw_data if raw_data and len(raw_data) == 10 and raw_data[4] == "-" else None)
            or to_iso(raw_data)
        )
        sha1 = hashlib.sha1(url.encode()).hexdigest() if url else None
        out.append({
            "classe":         item["classe"],
            "processo_id":    item["processo_id"],
            "seq":            seq,
            "data":           raw_data,
            "data_iso":       iso,
            "nome":           a.get("nome"),
            "complemento":    a.get("complemento"),
            "julgador":       a.get("julgador"),
            "link_tipo":      tipo,
            "link_url":       url,
            "link_url_sha1":  sha1,
            "link_text":      text,
            "link_extractor": extractor,
        })
    return out


def _flatten_documentos(item: dict) -> list[dict]:
    """Flatten sessao_virtual[*].documentos across all schema versions.

    Handles three shapes:
    - v1:  dict[tipo, str]                               — str is text OR url
    - v2/v3: dict[tipo, {url, text}]                     — dedup'd by tipo
    - v4:  list[{tipo, url, text, extractor}]            — duplicates allowed

    Emits one row per documento with a positional `doc_seq` within each
    session so the warehouse PK stays unique under v4 duplicates.
    """
    out = []
    for session_idx, sess in enumerate(item.get("sessao_virtual") or []):
        if not isinstance(sess, dict):
            continue
        docs = sess.get("documentos")
        entries = _normalize_documentos(docs)
        for doc_seq, row in enumerate(entries):
            url = row.get("url")
            out.append({
                "classe":      item["classe"],
                "processo_id": item["processo_id"],
                "session_idx": session_idx,
                "doc_seq":     doc_seq,
                "doc_type":    row.get("tipo"),
                "text":        row.get("text"),
                "url":         url,
                "url_sha1":    hashlib.sha1(url.encode()).hexdigest() if url else None,
                "extractor":   row.get("extractor"),
            })
    return out


def _normalize_documentos(docs: Any) -> list[dict]:
    """Coerce any schema version's documentos container to a v4-shape list.

    Missing fields are filled with None. Unknown shapes become an empty
    list so `_flatten_documentos` can keep iterating without exploding
    on malformed inputs.
    """
    if isinstance(docs, list):
        out: list[dict] = []
        for row in docs:
            if not isinstance(row, dict):
                continue
            out.append({
                "tipo":      row.get("tipo"),
                "url":       row.get("url"),
                "text":      row.get("text"),
                "extractor": row.get("extractor"),
            })
        return out
    if isinstance(docs, dict):
        out = []
        for tipo, val in docs.items():
            if isinstance(val, dict):
                out.append({
                    "tipo":      tipo,
                    "url":       val.get("url"),
                    "text":      val.get("text"),
                    "extractor": val.get("extractor"),
                })
            elif isinstance(val, str):
                is_url = val.startswith("http://") or val.startswith("https://")
                out.append({
                    "tipo":      tipo,
                    "url":       val if is_url else None,
                    "text":      None if is_url else val,
                    "extractor": None,
                })
        return out
    return []


def _iter_pdf_rows(pdf_cache_root: Path) -> Iterable[dict]:
    # Generator (not materialised list) — PDF text decompresses to ~1 GB
    # at production scale; holding it all in memory pushes peak RSS over
    # WSL2's available limit.
    if not pdf_cache_root.exists():
        return
    for txt_gz in pdf_cache_root.glob("*.txt.gz"):
        sha1 = txt_gz.name.removesuffix(".txt.gz")
        text = gzip.decompress(txt_gz.read_bytes()).decode("utf-8", errors="replace")
        has_elements = (pdf_cache_root / f"{sha1}.elements.json.gz").exists()
        yield {
            "sha1":         sha1,
            "n_chars":      len(text),
            "has_elements": has_elements,
            "text":         text,
            "cache_path":   str(txt_gz),
        }


def _bulk_insert_iter(
    con: duckdb.DuckDBPyConnection,
    table: str,
    rows_iter: Iterable[dict],
    batch_size: int = 5000,
) -> int:
    batch: list[dict] = []
    n = 0
    for row in rows_iter:
        batch.append(row)
        if len(batch) >= batch_size:
            _bulk_insert(con, table, batch)
            n += len(batch)
            batch.clear()
    if batch:
        _bulk_insert(con, table, batch)
        n += len(batch)
    return n


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _iter_case_files(
    cases_root: Path,
    classes: Optional[Iterable[str]],
    id_range: Optional[tuple[int, int]] = None,
) -> Iterable[Path]:
    if classes is None:
        gen: Iterable[Path] = cases_root.rglob("judex-mini_*.json")
    else:
        gen = (
            p
            for classe in classes
            for p in (cases_root / classe).glob("judex-mini_*.json")
        )
    if id_range is None:
        yield from gen
        return
    lo, hi = id_range
    for p in gen:
        stem = p.stem
        if "_" not in stem:
            continue
        rng = stem.rsplit("_", 1)[1]
        if "-" not in rng:
            continue
        a, _, b = rng.partition("-")
        try:
            ia, ib = int(a), int(b)
        except ValueError:
            continue
        if ia >= lo and ib <= hi:
            yield p


def _bulk_insert(con: duckdb.DuckDBPyConnection, table: str, rows: list[dict]) -> None:
    # Bulk-insert via Arrow registration. ~10–100x faster than
    # `executemany` parameter-binding (which becomes the dominant wall on
    # multi-million-row inserts). Coerces values to schema-aligned types
    # first — pyarrow's auto type inference picks a type from the first
    # rows it sees, then chokes on later rows whose dtypes differ. The
    # corpus has int/str mismatches in both scalar and list-element form.
    if not rows:
        return
    cols = list(rows[0].keys())
    schema_info = con.execute(f"PRAGMA table_info('{table}')").fetchall()
    int_cols = {r[1] for r in schema_info if r[2] in ("INTEGER", "BIGINT")}
    str_cols = {r[1] for r in schema_info if r[2] in ("VARCHAR", "TEXT")}
    str_list_cols = {r[1] for r in schema_info if r[2] in ("VARCHAR[]", "TEXT[]")}
    for row in rows:
        for c in int_cols:
            v = row.get(c)
            if v is None or isinstance(v, int):
                continue
            try:
                row[c] = int(v)
            except (ValueError, TypeError):
                row[c] = None
        for c in str_cols:
            v = row.get(c)
            if v is None or isinstance(v, str):
                continue
            row[c] = str(v)
        for c in str_list_cols:
            v = row.get(c)
            if v is None or not isinstance(v, list):
                continue
            row[c] = [str(x) if x is not None else None for x in v]
    arrow_table = pa.Table.from_pylist(rows)
    view = f"__bulk_{table}"
    con.register(view, arrow_table)
    try:
        col_list = ", ".join(cols)
        con.execute(
            f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM {view}"
        )
    finally:
        con.unregister(view)


def build(
    *,
    cases_root: Path,
    pdf_cache_root: Path,
    output_path: Path,
    classes: Optional[Iterable[str]] = None,
    id_range: Optional[tuple[int, int]] = None,
    progress_every: int = 10_000,
) -> BuildSummary:
    t0 = time.monotonic()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_name(output_path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()

    cases_rows: list[dict] = []
    partes_rows: list[dict] = []
    andamentos_rows: list[dict] = []
    documentos_rows: list[dict] = []

    for i, path in enumerate(_iter_case_files(cases_root, classes, id_range)):
        item = _load_case(path)
        if item is None or "classe" not in item or "processo_id" not in item:
            continue
        cases_rows.append(_flatten_case(item, path))
        partes_rows.extend(_flatten_partes(item))
        andamentos_rows.extend(_flatten_andamentos(item))
        documentos_rows.extend(_flatten_documentos(item))
        if progress_every and (i + 1) % progress_every == 0:
            print(f"  scanned {i + 1:,} cases", flush=True)

    classes_seen = sorted({r["classe"] for r in cases_rows})
    n_cases = len(cases_rows)
    n_partes = len(partes_rows)
    n_andamentos = len(andamentos_rows)
    n_documentos = len(documentos_rows)

    con = duckdb.connect(str(tmp))
    try:
        con.execute(_SCHEMA_SQL)
        # Insert + clear each table eagerly so peak RAM is at most one
        # table's data + its Arrow conversion, not all five stacked.
        _bulk_insert(con, "cases", cases_rows); cases_rows.clear()
        _bulk_insert(con, "partes", partes_rows); partes_rows.clear()
        _bulk_insert(con, "andamentos", andamentos_rows); andamentos_rows.clear()
        _bulk_insert(con, "documentos", documentos_rows); documentos_rows.clear()
        # PDFs streamed: ~1 GB decompressed text never sits in memory at once.
        n_pdfs = _bulk_insert_iter(con, "pdfs", _iter_pdf_rows(pdf_cache_root))
        wall = time.monotonic() - t0
        con.execute(
            "INSERT INTO manifest VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                datetime.now(),
                classes_seen,
                n_cases,
                n_partes,
                n_andamentos,
                n_documentos,
                n_pdfs,
                wall,
                _git_commit(),
            ],
        )
    finally:
        con.close()

    os.replace(tmp, output_path)
    return BuildSummary(
        n_cases=n_cases,
        n_partes=n_partes,
        n_andamentos=n_andamentos,
        n_documentos=n_documentos,
        n_pdfs=n_pdfs,
        wall_s=time.monotonic() - t0,
        output_path=output_path,
    )
