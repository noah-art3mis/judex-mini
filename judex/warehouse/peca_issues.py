"""Build the cross-run ``peca_issues`` warehouse table (streaming).

Walks every ``executar.state.json`` (and legacy ``pdfs.state.json``)
under a runs root, aggregates per-URL state across runs (latest
status, attempt count, first/last seen), enriches with filesystem
sidecars (extractor, dismissal) and warehouse joins (doc_type from
andamentos/documentos, n_chars from pdfs).

Memory-bounded refactor of the previous Python-dict aggregator: every
intermediate set lives in DuckDB temp tables, never in Python at the
full-corpus scale. Peak Python memory is one batch (~10k rows)
instead of 100-300k ``_PecaRow`` dataclasses plus accompanying
sidecar / doc-type / n_chars dicts. Saves ~150-250 MB on a
corpus-scale build, removing one of the OOM-killer cliffs on WSL2's
3.84 GB cap. The ``is_suspicious_short`` heuristic stays in Python
(``judex.analysis.peca_quality``) and is registered as a DuckDB UDF —
single source of truth, no SQL re-encoding of the doc-type set or
threshold.

PRD: ``.scratch/peca-registry/PRD.md`` sub-issue 01. Behaviour pinned
by ``tests/unit/test_peca_issues_builder.py``.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from judex.analysis.peca_quality import is_suspicious_short


_BATCH = 10_000
_STATE_FILENAMES: tuple[str, ...] = (
    "executar.state.json",
    "pdfs.state.json",     # legacy three-command chain
)


def _sha1(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _iter_state_files(runs_root: Path) -> Iterable[Path]:
    for name in _STATE_FILENAMES:
        yield from runs_root.glob(f"**/{name}")


def _iter_obs_rows(
    state_path: Path,
) -> Iterator[tuple]:
    """Yield observation tuples for the staging INSERT.

    Shape: ``(url, sha1, classe, processo_id, status, ts, run_dir_name)``.
    Malformed state files are skipped silently — the rest of the build
    must converge even if one run dir's state.json is half-written.
    """
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    cases = data.get("cases") or {}
    run_dir_name = state_path.parent.name
    for case_key, rec in cases.items():
        classe, _, pid_str = case_key.partition("-")
        try:
            processo_id = int(pid_str)
        except ValueError:
            continue
        # bytes + extract_text both have URL-keyed entries; meta is
        # case-keyed (no URL) and not relevant for the URL-level table.
        for stage in ("fetch_bytes", "extract_text"):
            entries = rec.get(stage) or {}
            for url, entry in entries.items():
                if not isinstance(entry, dict):
                    continue
                status = entry.get("status")
                if not status:
                    continue
                yield (
                    url, _sha1(url), classe, processo_id,
                    status, entry.get("ts") or "", run_dir_name,
                )


def _batched(it: Iterable, size: int) -> Iterator[list]:
    batch: list = []
    for item in it:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _stream_observations(con, runs_root: Path) -> None:
    """Stream URL observations into a DuckDB temp staging table."""
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _peca_obs (
            url VARCHAR, sha1 VARCHAR, classe VARCHAR,
            processo_id INTEGER, status VARCHAR, ts VARCHAR,
            run_dir_name VARCHAR
        )
    """)
    obs_stream = (
        obs
        for state_file in _iter_state_files(runs_root)
        for obs in _iter_obs_rows(state_file)
    )
    for batch in _batched(obs_stream, _BATCH):
        con.executemany(
            "INSERT INTO _peca_obs VALUES (?, ?, ?, ?, ?, ?, ?)",
            batch,
        )


def _stream_sidecars(con, pecas_texto_root: Path) -> None:
    """Stream extractor + dismissal sidecars into temp staging tables.
    Tables are always created (possibly empty) so the join SQL doesn't
    need to branch on existence."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE _peca_extractors "
        "(sha1 VARCHAR, extractor VARCHAR)"
    )
    con.execute(
        "CREATE OR REPLACE TEMP TABLE _peca_dismissals "
        "(sha1 VARCHAR, dismissed_at VARCHAR, reason VARCHAR)"
    )
    if not pecas_texto_root.exists():
        return

    def _iter_extractors() -> Iterator[tuple]:
        for ext_path in pecas_texto_root.glob("*.extractor"):
            try:
                value = ext_path.read_bytes().decode("utf-8").strip() or None
            except OSError:
                continue
            yield (ext_path.stem, value)

    for batch in _batched(_iter_extractors(), _BATCH):
        con.executemany(
            "INSERT INTO _peca_extractors VALUES (?, ?)", batch,
        )

    def _iter_dismissals() -> Iterator[tuple]:
        for dis_path in pecas_texto_root.glob("*.dismissed.json"):
            sha = dis_path.name.split(".", 1)[0]
            try:
                d = json.loads(dis_path.read_bytes().decode("utf-8"))
            except (OSError, ValueError):
                continue
            yield (sha, d.get("dismissed_at"), d.get("reason"))

    for batch in _batched(_iter_dismissals(), _BATCH):
        con.executemany(
            "INSERT INTO _peca_dismissals VALUES (?, ?, ?)", batch,
        )


def _stage_warehouse_joins(con) -> None:
    """Materialise optional upstream tables into temp staging tables.

    Preserves the original code's "skip gracefully when upstream
    missing" semantics — if ``andamentos`` doesn't exist (cold checkout
    / partial test fixture), the staging table stays empty rather than
    raising. The doc-type union uses a priority column so the
    aggregation SQL can pick andamentos over documentos via
    ``arg_min(doc_type, priority)`` — matching the original Python
    code's ``setdefault`` semantics.
    """
    con.execute(
        "CREATE OR REPLACE TEMP TABLE _doc_type_map "
        "(url VARCHAR, doc_type VARCHAR, priority INTEGER)"
    )
    try:
        con.execute("""
            INSERT INTO _doc_type_map
            SELECT link_url, link_tipo, 1 FROM andamentos
            WHERE link_url IS NOT NULL
        """)
    except Exception:
        pass
    try:
        con.execute("""
            INSERT INTO _doc_type_map
            SELECT url, doc_type, 2 FROM documentos
            WHERE url IS NOT NULL
        """)
    except Exception:
        pass

    con.execute(
        "CREATE OR REPLACE TEMP TABLE _sha1_chars_map "
        "(sha1 VARCHAR, n_chars INTEGER)"
    )
    try:
        con.execute("INSERT INTO _sha1_chars_map SELECT sha1, n_chars FROM pdfs")
    except Exception:
        pass


def _register_udf(con) -> None:
    """Register :func:`is_suspicious_short` as a DuckDB scalar UDF.

    The Python heuristic stays the single source of truth — both
    Python callers (peca_quality.py importers) and SQL callers (this
    aggregation) hit the same function. Avoids re-encoding the
    ``_SUSPICIOUS_DOC_TYPES`` set / ``SUSPICIOUS_THRESHOLD_CHARS``
    threshold in SQL, which would invite drift of the kind the recent
    ``recovery_policy`` extraction was designed to prevent.

    Type spec uses DuckDB's string-typed form (``"INTEGER"`` /
    ``"VARCHAR"``) for compatibility across the 1.x line — the
    ``duckdb.typing`` namespace isn't present in 1.5.x.
    """
    try:
        con.remove_function("is_suspicious_short_udf")
    except Exception:
        pass  # function not yet registered on this connection
    con.create_function(
        "is_suspicious_short_udf",
        is_suspicious_short,
        ["INTEGER", "VARCHAR"],
        "BOOLEAN",
    )


def build_peca_issues(
    con,
    *,
    runs_root: Path,
    pecas_texto_root: Path,
) -> int:
    """Populate the ``peca_issues`` table from disk + warehouse joins.

    Returns the number of rows inserted. Idempotent against a fresh
    empty table (the warehouse builder creates the table from
    ``_SCHEMA_SQL`` before calling this). Bugs must not break the rest
    of the warehouse build — caller wraps in try/except.
    """
    if not runs_root.exists():
        return 0

    _stream_observations(con, runs_root)
    _stream_sidecars(con, pecas_texto_root)
    _stage_warehouse_joins(con)
    _register_udf(con)

    # Single SQL pass: aggregate observations per URL (last-write-wins
    # on ts via arg_max), LEFT JOIN sidecars + doc_type + n_chars,
    # compute is_suspicious_short via the Python UDF, INSERT.
    #
    # Semantic equivalence with the prior Python aggregator:
    # * arg_max(col, ts) gives the col value from the row with the
    #   highest ts — same as the original ``if obs.ts > row.last_seen_at:
    #   row.col = obs.col`` last-write-wins loop. Ties on ts are broken
    #   arbitrarily by DuckDB; the original broke ties by Python dict
    #   iteration order. Production data always has distinct ISO-8601
    #   timestamps, so ties are theoretical.
    # * MIN(NULLIF(ts, '')) skips empty timestamps when computing
    #   first_seen_at — matches the original ``min(t for t in ts if t)``.
    # * MAX(ts) does NOT NULLIF — keeps empty-string output when every
    #   observation has ts='' (corner case; matches original).
    # * arg_min(doc_type, priority) picks andamentos (priority=1) over
    #   documentos (priority=2) — matches original setdefault order.
    con.execute("""
        INSERT INTO peca_issues
        SELECT
            o.url,
            o.sha1,
            o.classe,
            o.processo_id,
            dt.doc_type,
            o.latest_status,
            e.extractor AS latest_extractor,
            p.n_chars,
            is_suspicious_short_udf(p.n_chars, dt.doc_type)
                AS is_suspicious_short,
            o.n_attempts_seen,
            o.first_seen_at,
            o.last_seen_at,
            o.last_run_dir,
            d.dismissed_at,
            d.reason AS dismissed_reason
        FROM (
            SELECT
                url, sha1,
                arg_max(classe, ts) AS classe,
                arg_max(processo_id, ts) AS processo_id,
                arg_max(status, ts) AS latest_status,
                arg_max(run_dir_name, ts) AS last_run_dir,
                MIN(NULLIF(ts, '')) AS first_seen_at,
                MAX(ts) AS last_seen_at,
                COUNT(*) AS n_attempts_seen
            FROM _peca_obs
            GROUP BY url, sha1
        ) o
        LEFT JOIN _peca_extractors e ON e.sha1 = o.sha1
        LEFT JOIN _peca_dismissals d ON d.sha1 = o.sha1
        LEFT JOIN (
            SELECT url, arg_min(doc_type, priority) AS doc_type
            FROM _doc_type_map
            GROUP BY url
        ) dt ON dt.url = o.url
        LEFT JOIN _sha1_chars_map p ON p.sha1 = o.sha1
    """)

    return con.execute("SELECT COUNT(*) FROM peca_issues").fetchone()[0]
