"""Full-rebuild warehouse builder.

Walks `data/source/processos/**/*.json` + `data/derived/pecas-texto/*.txt.gz`
and emits a single `.duckdb` file with flat analytical tables. No
incremental logic — the whole thing rebuilds every run, which keeps the
code trivial (no UPSERT, no orphaned-row cleanup, no change-tracking
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
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import duckdb
import pyarrow as pa

from judex.scraping.extraction._shared import to_iso


def _resolve_text(
    url: Optional[str], inline_text: Optional[str], pecas_texto_root: Optional[Path]
) -> Optional[str]:
    """Resolve extracted text, preferring the peca_cache file as the canonical source (v8).

    Pre-v8 JSONs carry the text inline on each Documento; v8 JSONs
    carry None and rely on the sha1-keyed cache under `pecas_texto_root`.
    This helper bridges both — cache first (authoritative under v8),
    inline as fallback for unmigrated JSONs. Either way the warehouse
    column stays populated across corpus snapshots. `pecas_texto_root`
    threads through from `build()` so tests can point at a tmp dir.
    """
    if url and pecas_texto_root is not None:
        sha1 = hashlib.sha1(url.encode()).hexdigest()
        txt_gz = pecas_texto_root / f"{sha1}.txt.gz"
        if txt_gz.exists():
            return gzip.decompress(txt_gz.read_bytes()).decode("utf-8")
    return inline_text


def _resolve_extractor(
    url: Optional[str], inline_extractor: Optional[str], pecas_texto_root: Optional[Path]
) -> Optional[str]:
    if url and pecas_texto_root is not None:
        sha1 = hashlib.sha1(url.encode()).hexdigest()
        extractor_path = pecas_texto_root / f"{sha1}.extractor"
        if extractor_path.exists():
            return extractor_path.read_text(encoding="utf-8").strip() or None
    return inline_extractor


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

CREATE TABLE pautas (
    classe        VARCHAR NOT NULL,
    processo_id   INTEGER NOT NULL,
    seq           INTEGER NOT NULL,
    data          VARCHAR,
    data_iso      DATE,
    nome          VARCHAR,
    complemento   VARCHAR,
    julgador      VARCHAR,
    PRIMARY KEY (classe, processo_id, seq)
);

CREATE TABLE publicacoes_dje (
    classe            VARCHAR NOT NULL,
    processo_id       INTEGER NOT NULL,
    seq               INTEGER NOT NULL,   -- position in case.publicacoes_dje[]
    numero            INTEGER,            -- DJ number ("DJ Nr. 204")
    data              VARCHAR,            -- raw (pass-through from JSON; already ISO in v7+)
    data_iso          DATE,
    secao             VARCHAR,
    subsecao          VARCHAR,
    titulo            VARCHAR,
    detail_url        VARCHAR,
    incidente_linked  INTEGER,            -- 3rd abreDetalheDiarioProcesso() arg
    dje_classe        VARCHAR,            -- classe as recorded on the DJe (temporal snapshot)
    procedencia       VARCHAR,
    relator           VARCHAR,
    partes            VARCHAR[],
    materia           VARCHAR[],
    n_decisoes        INTEGER NOT NULL,   -- denormalized from decisoes_dje; cheap for filtering
    PRIMARY KEY (classe, processo_id, seq)
);

CREATE TABLE decisoes_dje (
    classe          VARCHAR NOT NULL,
    processo_id     INTEGER NOT NULL,
    dje_seq         INTEGER NOT NULL,     -- FK → publicacoes_dje(seq)
    dec_seq         INTEGER NOT NULL,     -- position in decisoes[] within the publicacao
    kind            VARCHAR NOT NULL,     -- 'decisao' | 'ementa'
    texto           VARCHAR,              -- HTML-extracted fast-path paragraph
    rtf_tipo        VARCHAR,
    rtf_url         VARCHAR,
    rtf_url_sha1    VARCHAR,
    rtf_text        VARCHAR,              -- cache-resolved (NULL when cache miss)
    rtf_extractor   VARCHAR,              -- cache-resolved
    PRIMARY KEY (classe, processo_id, dje_seq, dec_seq)
);

CREATE TABLE pdfs (
    sha1          VARCHAR PRIMARY KEY,
    n_chars       INTEGER NOT NULL,
    has_elements  BOOLEAN NOT NULL,
    text          VARCHAR NOT NULL,
    cache_path    VARCHAR NOT NULL
);

-- Cross-run per-URL registry: latest status, attempt count, dismissal
-- flag, suspicious-short heuristic. Sourced from walking every
-- ``executar.state.json`` (and legacy ``pdfs.state.json``) under
-- ``runs/active/`` plus the dismissal + extractor sidecars under
-- ``data/derived/pecas-texto/``. The peça's doc_type is joined in
-- from the warehouse's andamentos / documentos tables. Operators
-- query this to answer "what's the latest state of URL X across all
-- runs and time?" without grepping run dirs.
-- See .scratch/peca-registry/PRD.md.
CREATE TABLE peca_issues (
    url                  VARCHAR PRIMARY KEY,
    sha1                 VARCHAR NOT NULL,
    classe               VARCHAR,
    processo_id          INTEGER,
    doc_type             VARCHAR,
    latest_status        VARCHAR,
    latest_extractor     VARCHAR,
    n_chars              INTEGER,
    is_suspicious_short  BOOLEAN,
    n_attempts_seen      INTEGER NOT NULL,
    first_seen_at        VARCHAR,
    last_seen_at         VARCHAR,
    last_run_dir         VARCHAR,
    dismissed_at         VARCHAR,
    dismissed_reason     VARCHAR
);

-- processo_ids that STF's portal never bound to an incidente.
-- Sourced from `data/derived/nao-alocados/<classe>.candidates.tsv`
-- (pre-aggregated) OR by walking ``runs/active/`` + ``runs/archive/``
-- state.json files inline at warehouse-build time. See ADR-0002.
CREATE TABLE unallocated_pids (
    classe          VARCHAR NOT NULL,
    processo_id     INTEGER NOT NULL,
    n_observations  INTEGER NOT NULL,
    confirmed       BOOLEAN NOT NULL,
    PRIMARY KEY (classe, processo_id)
);

-- Cross-run case-id-keyed registry of case-meta failures
-- (sibling of peca_issues, but for the fetch_meta task type).
-- Captures cases where the portal-side scrape failed — distinct
-- from unallocated_pid (which is terminal-by-STF, "case-id was
-- never bound"). Populated by walking executar.state.json files
-- under runs/. See CONTEXT.md § "Cross-run registry".
CREATE TABLE case_issues (
    classe              VARCHAR NOT NULL,
    processo_id         INTEGER NOT NULL,
    latest_meta_status  VARCHAR,
    latest_error        VARCHAR,
    n_attempts_seen     INTEGER NOT NULL,
    first_seen_at       VARCHAR,
    last_seen_at        VARCHAR,
    last_run_dir        VARCHAR,
    PRIMARY KEY (classe, processo_id)
);

-- Snapshot of sha1s present in data/raw/pecas/ (bytes cache) at
-- warehouse-build time. Source for the missing_bytes /
-- orphan_cache_files views. See CONTEXT.md § "Disk-coverage gap".
CREATE TABLE disk_bytes (
    sha1 VARCHAR PRIMARY KEY
);

-- Snapshot of sha1s present in data/derived/pecas-texto/ (text
-- cache) at warehouse-build time. Source for the missing_text /
-- orphan_cache_files views.
CREATE TABLE disk_txt (
    sha1 VARCHAR PRIMARY KEY
);

CREATE TABLE manifest (
    built_at      TIMESTAMP NOT NULL,
    classes       VARCHAR[],
    n_cases       INTEGER,
    n_partes      INTEGER,
    n_andamentos  INTEGER,
    n_documentos  INTEGER,
    n_pautas          INTEGER,
    n_publicacoes_dje INTEGER,
    n_decisoes_dje    INTEGER,
    n_pdfs            INTEGER,
    n_unallocated     INTEGER,
    build_wall_s      DOUBLE,
    judex_commit      VARCHAR
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
CREATE INDEX pautas_data_idx          ON pautas (data_iso);
CREATE INDEX pautas_nome_idx          ON pautas (nome);
CREATE INDEX pubdje_data_idx          ON publicacoes_dje (data_iso);
CREATE INDEX pubdje_secao_idx         ON publicacoes_dje (secao, subsecao);
CREATE INDEX pubdje_linked_idx        ON publicacoes_dje (incidente_linked);
CREATE INDEX decdje_kind_idx          ON decisoes_dje (kind);
CREATE INDEX decdje_rtf_sha1_idx      ON decisoes_dje (rtf_url_sha1);

-- Substantive-peça filter: unions andamentos-side peças + session-virtual
-- documentos, tier-labels them (A = full argumentation, B = length-gated
-- mixed). Tier-C boilerplate tipos (CERTIDÃO*, TERMO DE *, etc.) are
-- excluded by the WHERE clause — their content is either procedural
-- template text or data already structured in `cases` / `andamentos`.
-- See `docs/peca-tipo-classification.md` for the tier definitions.
CREATE VIEW pdfs_substantive AS
SELECT
    a.classe,
    a.processo_id,
    a.seq AS seq,
    a.link_tipo AS doc_type,
    a.link_url AS url,
    a.link_url_sha1 AS sha1,
    'andamento' AS source,
    CASE
        WHEN a.link_tipo IN ('DECISÃO MONOCRÁTICA', 'INTEIRO TEOR DO ACÓRDÃO') THEN 'A'
        WHEN a.link_tipo = 'MANIFESTAÇÃO DA PGR' THEN 'A'
        WHEN a.link_tipo = 'DESPACHO' THEN 'B'
    END AS tier,
    p.text,
    p.n_chars
FROM andamentos a
LEFT JOIN pdfs p ON a.link_url_sha1 = p.sha1
WHERE a.link_url IS NOT NULL
  AND (
        a.link_tipo IN ('DECISÃO MONOCRÁTICA', 'INTEIRO TEOR DO ACÓRDÃO')
     OR (a.link_tipo = 'MANIFESTAÇÃO DA PGR' AND (p.n_chars IS NULL OR p.n_chars > 1000))
     OR (a.link_tipo = 'DESPACHO'            AND (p.n_chars IS NULL OR p.n_chars > 1500))
  )

UNION ALL

SELECT
    d.classe,
    d.processo_id,
    d.doc_seq AS seq,
    d.doc_type,
    d.url,
    d.url_sha1 AS sha1,
    'sessao_virtual' AS source,
    'A' AS tier,
    d.text,
    CAST(LENGTH(d.text) AS INTEGER) AS n_chars
FROM documentos d
WHERE d.url IS NOT NULL
  AND d.doc_type IN ('Voto', 'Relatório', 'Voto Vogal', 'Voto Vista');

-- Substantive URLs whose .pdf.gz isn't on disk (after warehouse rebuild
-- snapshots the bytes-cache state into disk_bytes). Surfaces the
-- "byte-coverage gap" — see CONTEXT.md § "Disk-coverage gap".
CREATE VIEW missing_bytes AS
SELECT s.classe, s.processo_id, s.url, s.sha1, s.doc_type, s.tier
  FROM pdfs_substantive s
  LEFT JOIN disk_bytes db ON db.sha1 = s.sha1
 WHERE db.sha1 IS NULL;

-- Substantive URLs whose .txt.gz isn't on disk. Distinct from
-- missing_bytes: a URL may have bytes-only (pre-extraction era) or
-- be missing both.
CREATE VIEW missing_text AS
SELECT s.classe, s.processo_id, s.url, s.sha1, s.doc_type, s.tier
  FROM pdfs_substantive s
  LEFT JOIN disk_txt dt ON dt.sha1 = s.sha1
 WHERE dt.sha1 IS NULL;

-- Cache files on disk whose sha1 isn't referenced by any URL in
-- pdfs_substantive — pre-split-era legacy extractions or URLs that
-- have since been narrowed out of the substantive set. See
-- CONTEXT.md § "Orphan cache file".
CREATE VIEW orphan_cache_files AS
SELECT db.sha1, 'bytes_only' AS kind
  FROM disk_bytes db
  LEFT JOIN pdfs_substantive s ON s.sha1 = db.sha1
 WHERE s.sha1 IS NULL
UNION ALL
SELECT dt.sha1, 'text_only' AS kind
  FROM disk_txt dt
  LEFT JOIN pdfs_substantive s ON s.sha1 = dt.sha1
 WHERE s.sha1 IS NULL;
"""


@dataclass
class BuildSummary:
    n_cases: int
    n_partes: int
    n_andamentos: int
    n_documentos: int
    n_pautas: int
    n_publicacoes_dje: int
    n_decisoes_dje: int
    n_pdfs: int
    n_unallocated: int
    wall_s: float
    output_path: Path
    population_rates: dict[str, float]
    validation_warnings: list[str]


class BuildValidationError(RuntimeError):
    """Raised when `build(strict=True)` hits a population-rate threshold miss.

    Caught by the CLI so `judex warehouse --strict` exits non-zero
    on regressions. Ad-hoc `build(strict=False)` calls log the same
    information to stdout but do not raise — the warehouse file is still
    produced so manual inspection is possible.
    """


# Minimum expected population rate per case-level field, derived from the
# 2026-04-21 sample of a healthy v8+DJe corpus. These are intentionally
# conservative floors (not means) — a build dropping below these values
# is evidence of a scraper regression, not a genuine corpus shift.
#
# Contract: (field_name, minimum_population_rate_across_cases, description).
# The field_name keys match what `_compute_population_rates` emits.
MIN_POPULATION_RATES: dict[str, tuple[float, str]] = {
    # Structural invariants — every STF case has at least one parte and one
    # andamento. A drop below 99% means cases are being written malformed.
    "partes":           (0.99, "cases with ≥1 parte"),
    "andamentos":       (0.99, "cases with ≥1 andamento"),
    # Distributional — ~25–29% observed on arm B / arm C; floor 15% is
    # wide enough to tolerate class-mix shifts (e.g. builds scoped to a
    # class with fewer pautas) without firing spuriously.
    "pautas":           (0.15, "cases with ≥1 pauta"),
    "sessao_virtual":   (0.15, "cases with ≥1 sessao_virtual entry"),
    # DJe — this is the canary for the JS-rendering regression. A healthy
    # corpus has ≥5% of cases with DJe; the 2026-04-21 discovery showed
    # 0% corpus-wide when STF migrated the listing endpoint. 5% is a
    # loose floor; real healthy rates should be 20–40%.
    "publicacoes_dje":  (0.05, "cases with ≥1 DJe publication"),
}


# How many cases buffer in memory before flushing to DuckDB. Smaller →
# lower peak RAM, more Arrow-conversion overhead per insert. Tests
# monkeypatch this down to 3 to exercise chunk-boundary code paths.
#
# Sized for WSL2's 3.8 GB physical-RAM ceiling. The dominant per-chunk
# heap consumer is `buffers.andamentos`: every andamento whose
# `link.url` has a cached `.txt.gz` carries the decompressed text
# (avg ~9 KB) inline as `link_text`, and `_bulk_insert` materializes a
# second Arrow copy during the flush. Empirically:
#   N=5000 → ~900 MB peak (andamentos buffer + Arrow), OOM-killed on
#            full HC corpus once `.txt.gz` cache passed ~100k files.
#   N=1500 → ~270 MB peak, comfortable margin under WSL2 ceiling.
# Re-anchor downward if the per-row text payload grows further (e.g.
# if `documentos.text` starts pulling cached PDFs at the same rate as
# `andamentos.link_text`).
#
# The redundancy of `andamentos.link_text` vs `pdfs.text` (the same
# content lands in both tables; queries should join via
# `pdfs_substantive`) is a schema bug noted 2026-04-30 — fixing it
# would let this constant climb back to 5000+. Out of scope for the
# OOM hotfix.
_CHUNK_SIZE: int = 1_500


@dataclass
class BufferSet:
    cases: list[dict] = field(default_factory=list)
    partes: list[dict] = field(default_factory=list)
    andamentos: list[dict] = field(default_factory=list)
    documentos: list[dict] = field(default_factory=list)
    pautas: list[dict] = field(default_factory=list)
    publicacoes_dje: list[dict] = field(default_factory=list)
    decisoes_dje: list[dict] = field(default_factory=list)

    def flush(self, con: duckdb.DuckDBPyConnection) -> None:
        for f in fields(self):
            rows = getattr(self, f.name)
            if rows:
                _bulk_insert(con, f.name, rows)
                rows.clear()


def _compute_population_rates(
    n_cases: int,
    *,
    cases_with_partes: int,
    cases_with_andamentos: int,
    cases_with_pautas: int,
    cases_with_publicacoes_dje: int,
    sessao_virtual_populated: int,
) -> dict[str, float]:
    """Population rate = (cases with ≥1 child row) / n_cases, per field.

    Takes pre-computed populated-case counts rather than raw row lists,
    so `build()` can track them incrementally during a streamed scan
    without ever holding the full row corpus in memory.

    Returns 0.0 for every field when n_cases is 0 rather than dividing.
    """
    if n_cases <= 0:
        return {k: 0.0 for k in MIN_POPULATION_RATES}
    return {
        "partes":          cases_with_partes          / n_cases,
        "andamentos":      cases_with_andamentos      / n_cases,
        "pautas":          cases_with_pautas          / n_cases,
        "publicacoes_dje": cases_with_publicacoes_dje / n_cases,
        "sessao_virtual":  sessao_virtual_populated   / n_cases,
    }


def _validate_population_rates(
    rates: dict[str, float],
) -> tuple[list[str], list[str]]:
    """Compare each rate to its threshold. Returns (warnings, info_lines).

    Each info line is a "FIELD: X.Y% (threshold ≥ Z%) OK|WARN" row so
    the full build stats print as a human-readable table. Warnings are
    the subset of info lines that fail their threshold — what `strict`
    mode would raise on.
    """
    warnings: list[str] = []
    info: list[str] = []
    for field, (min_rate, desc) in MIN_POPULATION_RATES.items():
        actual = rates.get(field, 0.0)
        ok = actual >= min_rate
        flag = "OK  " if ok else "WARN"
        line = (
            f"  {desc:42s}: {actual*100:5.1f}% "
            f"(threshold ≥ {min_rate*100:4.1f}%) [{flag}]"
        )
        info.append(line)
        if not ok:
            warnings.append(
                f"{field}: population rate {actual*100:.2f}% "
                f"below threshold {min_rate*100:.1f}%"
            )
    return warnings, info


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


def _flatten_andamentos(item: dict, pecas_texto_root: Optional[Path] = None) -> list[dict]:
    """Flatten andamentos into warehouse rows.

    v5+: `link = {tipo, url, text, extractor}` or None.
    v6: the `data` field carries ISO 8601 directly; pre-v6 files carry
    DD/MM with a sibling `data_iso`. We read from either.
    """
    out = []
    for seq, a in enumerate(item.get("andamentos") or []):
        link = a.get("link") if isinstance(a.get("link"), dict) else {}
        url = link.get("url")
        # v8: text/extractor live canonically in peca_cache; fall back
        # to the inline value for pre-v8 JSONs so a mid-migration corpus
        # stays uniform.
        text = _resolve_text(url, link.get("text"), pecas_texto_root)
        extractor = _resolve_extractor(url, link.get("extractor"), pecas_texto_root)
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


def _flatten_publicacoes_dje(item: dict) -> list[dict]:
    """One row per PublicacaoDJe entry (listing + detail fields).

    Lists (partes, materia) go in as VARCHAR[] — DuckDB supports
    array columns natively and analytical queries over short lists
    like these don't warrant a separate junction table. `n_decisoes`
    is denormalized (computed here from `decisoes`) so callers can
    filter publicações without a COUNT() subquery.
    """
    out: list[dict] = []
    for seq, p in enumerate(item.get("publicacoes_dje") or []):
        if not isinstance(p, dict):
            continue
        raw_data = p.get("data")
        iso = (
            raw_data if raw_data and len(raw_data) == 10 and raw_data[4] == "-"
            else None
        )
        out.append({
            "classe":           item["classe"],
            "processo_id":      item["processo_id"],
            "seq":              seq,
            "numero":           p.get("numero"),
            "data":             raw_data,
            "data_iso":         iso,
            "secao":            p.get("secao"),
            "subsecao":         p.get("subsecao"),
            "titulo":           p.get("titulo"),
            "detail_url":       p.get("detail_url"),
            "incidente_linked": p.get("incidente_linked"),
            "dje_classe":       p.get("classe"),
            "procedencia":      p.get("procedencia"),
            "relator":          p.get("relator"),
            "partes":           list(p.get("partes") or []),
            "materia":          list(p.get("materia") or []),
            "n_decisoes":       len(p.get("decisoes") or []),
        })
    return out


def _flatten_decisoes_dje(
    item: dict, pecas_texto_root: Optional[Path] = None
) -> list[dict]:
    """One row per DecisaoDJe block. rtf_text + rtf_extractor resolved via cache."""
    out: list[dict] = []
    for dje_seq, p in enumerate(item.get("publicacoes_dje") or []):
        if not isinstance(p, dict):
            continue
        for dec_seq, dec in enumerate(p.get("decisoes") or []):
            if not isinstance(dec, dict):
                continue
            rtf = dec.get("rtf") or {}
            rtf_url = rtf.get("url") if isinstance(rtf, dict) else None
            rtf_text = _resolve_text(rtf_url, rtf.get("text") if isinstance(rtf, dict) else None, pecas_texto_root)
            rtf_extractor = _resolve_extractor(
                rtf_url,
                rtf.get("extractor") if isinstance(rtf, dict) else None,
                pecas_texto_root,
            )
            out.append({
                "classe":         item["classe"],
                "processo_id":    item["processo_id"],
                "dje_seq":        dje_seq,
                "dec_seq":        dec_seq,
                "kind":           dec.get("kind"),
                "texto":          dec.get("texto"),
                "rtf_tipo":       rtf.get("tipo") if isinstance(rtf, dict) else None,
                "rtf_url":        rtf_url,
                "rtf_url_sha1":   hashlib.sha1(rtf_url.encode()).hexdigest() if rtf_url else None,
                "rtf_text":       rtf_text,
                "rtf_extractor":  rtf_extractor,
            })
    return out


def _flatten_pautas(item: dict) -> list[dict]:
    """Flatten the v6 `pautas` top-level list into warehouse rows.

    The `Pauta` TypedDict mirrors `Andamento` minus the `link` field
    (pauta rows don't carry PDF anchors). The `data` field is ISO 8601
    in v6; we carry both `data` (VARCHAR) and `data_iso` (DATE) to
    stay consistent with the andamentos table. Pre-v6 case JSONs lack
    the `pautas` key entirely — `.get(..., []) or []` short-circuits
    to zero rows without special-casing.
    """
    out = []
    for seq, p in enumerate(item.get("pautas") or []):
        raw_data = p.get("data")
        iso = (
            raw_data
            if raw_data and len(raw_data) == 10 and raw_data[4] == "-"
            else None
        )
        out.append({
            "classe":      item["classe"],
            "processo_id": item["processo_id"],
            "seq":         seq,
            "data":        raw_data,
            "data_iso":    iso,
            "nome":        p.get("nome"),
            "complemento": p.get("complemento"),
            "julgador":    p.get("julgador"),
        })
    return out


def _flatten_documentos(item: dict, pecas_texto_root: Optional[Path] = None) -> list[dict]:
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
            # v8: cache-first resolve; inline only for pre-v8 fallback.
            text = _resolve_text(url, row.get("text"), pecas_texto_root)
            extractor = _resolve_extractor(url, row.get("extractor"), pecas_texto_root)
            out.append({
                "classe":      item["classe"],
                "processo_id": item["processo_id"],
                "session_idx": session_idx,
                "doc_seq":     doc_seq,
                "doc_type":    row.get("tipo"),
                "text":        text,
                "url":         url,
                "url_sha1":    hashlib.sha1(url.encode()).hexdigest() if url else None,
                "extractor":   extractor,
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


def _iter_pdf_rows(
    pecas_texto_root: Path,
    sha1_filter: Optional[set[str]] = None,
) -> Iterable[dict]:
    # Generator (not materialised list) — PDF text decompresses to ~1 GB
    # at production scale; holding it all in memory pushes peak RSS over
    # WSL2's available limit.
    #
    # sha1_filter: when provided, only yield PDFs whose sha1 is in the set.
    # Used by scoped builds (--classe or --year) to avoid pulling the
    # global cache into a narrow warehouse. None → include every PDF.
    if not pecas_texto_root.exists():
        return
    for txt_gz in pecas_texto_root.glob("*.txt.gz"):
        sha1 = txt_gz.name.removesuffix(".txt.gz")
        if sha1_filter is not None and sha1 not in sha1_filter:
            continue
        text = gzip.decompress(txt_gz.read_bytes()).decode("utf-8", errors="replace")
        has_elements = (pecas_texto_root / f"{sha1}.elements.json.gz").exists()
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


def _load_unallocated_pids(
    root: Path, classe: str, *, min_observations: int = 2,
) -> list[dict]:
    """Read `<classe>.candidates.tsv` into rows for the unallocated_pids table.

    Tolerant of both the legacy 3-column header (`processo_id, n_observations,
    n_empty_body`) and the new 2-column header (`processo_id, n_observations`):
    the loader keys off column names, not positions. `confirmed` is derived
    here so SQL queries don't have to know the threshold.
    """
    tsv = root / f"{classe}.candidates.tsv"
    if not tsv.exists():
        return []
    rows: list[dict] = []
    with tsv.open() as f:
        header = f.readline().rstrip("\n").split("\t")
        try:
            pid_col = header.index("processo_id")
            obs_col = header.index("n_observations")
        except ValueError:
            return []
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) <= max(pid_col, obs_col):
                continue
            try:
                pid = int(parts[pid_col])
                n_obs = int(parts[obs_col])
            except ValueError:
                continue
            rows.append({
                "classe": classe,
                "processo_id": pid,
                "n_observations": n_obs,
                "confirmed": n_obs >= min_observations,
            })
    return rows


def _collect_unallocated_from_state_files(
    runs_root: Path, *, min_observations: int = 2,
) -> list[dict]:
    """Walk every ``executar.state.json`` under ``runs_root`` and count
    per-(classe, processo_id) ``unallocated_pid`` observations.

    Returns rows ready for ``unallocated_pids`` insert. Sibling of the
    TSV-based path (``_load_unallocated_pids``) — invoked when the TSV
    is absent or the operator wants live aggregation across the current
    runs/ tree. ``confirmed`` is derived from ``min_observations``,
    same threshold as the TSV path.
    """
    if not runs_root.exists():
        return []
    import json
    counts: dict[tuple[str, int], int] = {}
    for state_path in runs_root.glob("**/executar.state.json"):
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cases = data.get("cases") or {}
        for case_key, rec in cases.items():
            classe, _, pid_str = case_key.partition("-")
            try:
                pid = int(pid_str)
            except ValueError:
                continue
            meta = rec.get("fetch_meta")
            if not isinstance(meta, dict):
                continue
            if meta.get("status") != "unallocated_pid":
                continue
            counts[(classe, pid)] = counts.get((classe, pid), 0) + 1
    return [
        {
            "classe": classe,
            "processo_id": pid,
            "n_observations": n,
            "confirmed": n >= min_observations,
        }
        for (classe, pid), n in sorted(counts.items())
    ]


def _populate_disk_snapshots(
    con,
    *,
    bytes_root: Path,
    text_root: Path,
) -> tuple[int, int]:
    """Populate ``disk_bytes`` + ``disk_txt`` with sha1s present on disk.

    These tables back the ``missing_bytes`` / ``missing_text`` /
    ``orphan_cache_files`` views. Snapshotted at warehouse-build time;
    refreshing requires a warehouse rebuild (acceptable since rebuilds
    are ~5 min and the bytes-cache state only changes when a sweep
    runs).
    """
    import os
    bytes_sha1s = (
        n[:-7] for n in os.listdir(bytes_root) if n.endswith(".pdf.gz")
    ) if bytes_root.exists() else iter(())
    text_sha1s = (
        n[:-7] for n in os.listdir(text_root) if n.endswith(".txt.gz")
    ) if text_root.exists() else iter(())

    bytes_payload = [(s,) for s in bytes_sha1s]
    text_payload = [(s,) for s in text_sha1s]
    if bytes_payload:
        con.executemany("INSERT INTO disk_bytes VALUES (?)", bytes_payload)
    if text_payload:
        con.executemany("INSERT INTO disk_txt VALUES (?)", text_payload)
    return len(bytes_payload), len(text_payload)


def build(
    *,
    cases_root: Path,
    pecas_texto_root: Path,
    output_path: Path,
    classes: Optional[Iterable[str]] = None,
    id_range: Optional[tuple[int, int]] = None,
    progress_every: int = 10_000,
    strict: bool = False,
    unallocated_pids_root: Optional[Path] = None,
    runs_root: Optional[Path] = None,
    bytes_root: Optional[Path] = None,
) -> BuildSummary:
    """Build the warehouse. When ``strict=True``, a population-rate
    threshold miss (see ``MIN_POPULATION_RATES``) raises
    ``BuildValidationError`` *after* the rates are printed, so operators
    see the full stats before the non-zero exit. Ad-hoc invocations
    default ``strict=False`` — warnings surface on stdout but the
    warehouse still ships so manual inspection is possible.
    """
    t0 = time.monotonic()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_name(output_path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()

    # Per-case buffers, bounded to _CHUNK_SIZE cases. Everything flushes
    # into DuckDB on each boundary — peak RAM scales with the chunk, not
    # the corpus. Before this refactor (2026-04-24) the full corpus sat
    # in memory at once, which OOM-killed on WSL2 at ~80k HC cases.
    buffers = BufferSet()

    n_cases = 0
    counts: dict[str, int] = {
        f.name: 0 for f in fields(BufferSet) if f.name != "cases"
    }
    # Populated-case sets: (classe, processo_id) keys per field that
    # participates in population-rate validation. Bounded at O(n_cases).
    populated: dict[str, set[tuple[str, int]]] = {
        "partes": set(), "andamentos": set(),
        "pautas": set(), "publicacoes_dje": set(),
    }
    # sessao_virtual isn't its own table (entries land in `documentos`
    # with kind='sessao'), so count cases whose JSON had a non-empty
    # sessao_virtual list directly during the scan.
    sessao_virtual_populated = 0
    classes_seen: set[str] = set()
    # Scoped builds (classe or id_range filter) need the set of
    # documentos url_sha1s so the PDF insert filters to just those
    # referenced by this warehouse. Unscoped builds load the full PDF
    # cache — sha1_filter stays None.
    sha1_filter: Optional[set[str]] = (
        set() if (classes is not None or id_range is not None) else None
    )

    con = duckdb.connect(str(tmp))
    try:
        # Cap DuckDB's buffer pool so it spills to disk on memory
        # pressure instead of competing with the Python heap for
        # WSL2's 3.8 GB RAM (DuckDB defaults to 80% of physical RAM →
        # ~3 GB on this box, which leaves nothing for the per-chunk
        # Arrow conversions and gets the build OOM-killed at the
        # pdfs-load tail). 800 MB is empirical; raise if the build
        # gets I/O-bound.
        con.execute("SET memory_limit='800MB'")
        con.execute("SET threads=2")
        con.execute(_SCHEMA_SQL)

        # Materialise the case-file list once so progress prints can show a
        # denominator + ETA. ~30 MB peak for the 100k-case HC corpus — trivial
        # against the 800 MB DuckDB cap, and pays for itself in operator
        # legibility (no more "scanned 10,000 cases out of how many?").
        case_files = list(_iter_case_files(cases_root, classes, id_range))
        total_cases = len(case_files)
        print(f"  found {total_cases:,} case files to scan", flush=True)

        for i, path in enumerate(case_files):
            item = _load_case(path)
            if item is None or "classe" not in item or "processo_id" not in item:
                continue

            case_row = _flatten_case(item, path)
            key = (case_row["classe"], case_row["processo_id"])
            buffers.cases.append(case_row)
            n_cases += 1
            classes_seen.add(case_row["classe"])

            partes = _flatten_partes(item)
            if partes:
                populated["partes"].add(key)
            counts["partes"] += len(partes)
            buffers.partes.extend(partes)

            andamentos = _flatten_andamentos(item, pecas_texto_root)
            if andamentos:
                populated["andamentos"].add(key)
            counts["andamentos"] += len(andamentos)
            buffers.andamentos.extend(andamentos)

            documentos = _flatten_documentos(item, pecas_texto_root)
            counts["documentos"] += len(documentos)
            buffers.documentos.extend(documentos)
            if sha1_filter is not None:
                sha1_filter.update(
                    d["url_sha1"] for d in documentos if d.get("url_sha1")
                )

            pautas = _flatten_pautas(item)
            if pautas:
                populated["pautas"].add(key)
            counts["pautas"] += len(pautas)
            buffers.pautas.extend(pautas)

            publicacoes_dje = _flatten_publicacoes_dje(item)
            if publicacoes_dje:
                populated["publicacoes_dje"].add(key)
            counts["publicacoes_dje"] += len(publicacoes_dje)
            buffers.publicacoes_dje.extend(publicacoes_dje)

            decisoes_dje = _flatten_decisoes_dje(item, pecas_texto_root)
            counts["decisoes_dje"] += len(decisoes_dje)
            buffers.decisoes_dje.extend(decisoes_dje)

            if item.get("sessao_virtual"):
                sessao_virtual_populated += 1

            if progress_every and (i + 1) % progress_every == 0:
                elapsed = time.monotonic() - t0
                rate = (i + 1) / elapsed if elapsed > 0 else 0.0
                eta_s = (total_cases - (i + 1)) / rate if rate > 0 else 0.0
                print(
                    f"  scanned {i + 1:,} / {total_cases:,} cases "
                    f"· {rate:.0f} cases/s · eta {eta_s / 60:.1f} min",
                    flush=True,
                )
            if n_cases % _CHUNK_SIZE == 0:
                buffers.flush(con)

        buffers.flush(con)  # tail chunk

        # Population-rate validation: catches silent field-wide regressions
        # (e.g. STF's 2026-04-21 DJe-listing JS-migration took our DJe capture
        # rate from 20%+ to 0% corpus-wide; a threshold check here would have
        # caught it immediately instead of three days later).
        population_rates = _compute_population_rates(
            n_cases=n_cases,
            cases_with_partes=len(populated["partes"]),
            cases_with_andamentos=len(populated["andamentos"]),
            cases_with_pautas=len(populated["pautas"]),
            cases_with_publicacoes_dje=len(populated["publicacoes_dje"]),
            sessao_virtual_populated=sessao_virtual_populated,
        )
        validation_warnings, validation_lines = _validate_population_rates(
            population_rates
        )
        print(f"\nbuild stats ({n_cases:,} cases):", flush=True)
        for line in validation_lines:
            print(line, flush=True)
        if validation_warnings:
            print(
                f"  ⚠ {len(validation_warnings)} threshold miss(es) — see above",
                flush=True,
            )

        # PDFs streamed: ~1 GB decompressed text never sits in memory at once.
        print(f"  loading pdfs from {pecas_texto_root}…", flush=True)
        n_pdfs = _bulk_insert_iter(
            con, "pdfs", _iter_pdf_rows(pecas_texto_root, sha1_filter)
        )
        print(f"  loaded {n_pdfs:,} pdfs", flush=True)

        # Unallocated processo_ids — sourced from the cross-sweep registry.
        # See ADR-0002. Tests omit the root and get an empty table.
        # Dual-source: pre-aggregated TSV (legacy) PLUS inline state.json
        # walk (so the warehouse stays current even when nobody ran the
        # aggregator script). State walk wins on collisions (same pid,
        # higher observation count — it sees more runs than any single
        # TSV checkpoint).
        print("  loading unallocated_pids registry…", flush=True)
        unallocated_by_key: dict[tuple[str, int], dict] = {}
        if unallocated_pids_root is not None:
            for classe in sorted(classes_seen):
                for row in _load_unallocated_pids(unallocated_pids_root, classe):
                    unallocated_by_key[(row["classe"], row["processo_id"])] = row
        if runs_root is not None:
            for row in _collect_unallocated_from_state_files(runs_root):
                key = (row["classe"], row["processo_id"])
                existing = unallocated_by_key.get(key)
                if existing is None or row["n_observations"] > existing["n_observations"]:
                    unallocated_by_key[key] = row
        unallocated_rows = list(unallocated_by_key.values())
        n_unallocated = _bulk_insert_iter(con, "unallocated_pids", iter(unallocated_rows))
        print(f"  loaded {n_unallocated:,} unallocated_pids", flush=True)

        # Disk-snapshot tables — back the missing_bytes / missing_text /
        # orphan_cache_files views. Snapshotted now; views compute live
        # against this snapshot. ``bytes_root=None`` skips the bytes
        # snapshot (tests + cold checkouts); text always comes from the
        # ``pecas_texto_root`` we were called with.
        if bytes_root is not None:
            print("  computing disk snapshots (bytes + text)…", flush=True)
            n_disk_bytes, n_disk_txt = _populate_disk_snapshots(
                con, bytes_root=bytes_root, text_root=pecas_texto_root,
            )
            print(
                f"  disk snapshots: {n_disk_bytes:,} bytes / "
                f"{n_disk_txt:,} text",
                flush=True,
            )

        # peca_issues: cross-run per-URL registry (PRD: peca-registry).
        # Wrapped: a bug here must not break the rest of the build.
        # Existing tables ship even if this pass fails. ``runs_root=None``
        # skips the pass — used by tests + cold checkouts where there's
        # no runs/ directory to walk.
        if runs_root is not None:
            try:
                print("  building peca_issues registry…", flush=True)
                from judex.warehouse.peca_issues import build_peca_issues
                n_peca_issues = build_peca_issues(
                    con,
                    runs_root=runs_root,
                    pecas_texto_root=pecas_texto_root,
                )
                print(f"  peca_issues: {n_peca_issues:,} rows", flush=True)
                print("  building case_issues registry…", flush=True)
                from judex.warehouse.case_issues import build_case_issues
                n_case_issues = build_case_issues(con, runs_root=runs_root)
                print(f"  case_issues: {n_case_issues:,} rows", flush=True)
            except Exception as e:  # noqa: BLE001
                print(
                    f"  ⚠ peca_issues / case_issues build failed "
                    f"({type(e).__name__}: {e}) — tables left empty; "
                    f"warehouse otherwise OK",
                    flush=True,
                )

        wall = time.monotonic() - t0
        con.execute(
            "INSERT INTO manifest VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                datetime.now(),
                sorted(classes_seen),
                n_cases,
                counts["partes"],
                counts["andamentos"],
                counts["documentos"],
                counts["pautas"],
                counts["publicacoes_dje"],
                counts["decisoes_dje"],
                n_pdfs,
                n_unallocated,
                wall,
                _git_commit(),
            ],
        )
    finally:
        con.close()

    os.replace(tmp, output_path)
    # Under strict mode, raise *after* the warehouse file ships + stats
    # print, so operators see what failed before the non-zero exit. The
    # warehouse is still produced — callers who want to inspect the bad
    # build can query it; they just don't get a clean CI signal.
    if strict and validation_warnings:
        raise BuildValidationError(
            "population-rate thresholds missed: "
            + "; ".join(validation_warnings)
        )
    return BuildSummary(
        n_cases=n_cases,
        n_partes=counts["partes"],
        n_andamentos=counts["andamentos"],
        n_documentos=counts["documentos"],
        n_pautas=counts["pautas"],
        n_publicacoes_dje=counts["publicacoes_dje"],
        n_decisoes_dje=counts["decisoes_dje"],
        n_pdfs=n_pdfs,
        n_unallocated=n_unallocated,
        wall_s=time.monotonic() - t0,
        output_path=output_path,
        population_rates=population_rates,
        validation_warnings=validation_warnings,
    )
