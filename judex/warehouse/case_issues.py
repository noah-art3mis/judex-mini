"""Build the cross-run ``case_issues`` warehouse table (streaming).

Sibling of ``peca_issues`` but case-id-keyed instead of URL-keyed.
Captures cases where the *portal-side* fetch_meta task failed —
SSL storms on a contiguous case-id range, persistent HTTP errors
on case-meta, etc. Distinct from ``unallocated_pids`` (which is
terminal-by-STF: "case-id was never bound to a processo").

Memory-bounded refactor: observations stream into a DuckDB temp
table, aggregation runs as one SQL pass with the problematic-status
filter inline. Peak Python memory is one batch (~10k rows) rather
than a full ``dict[(classe, pid), _CaseRow]``. Same OOM-prevention
motivation as the peca_issues refactor.

See CONTEXT.md § "Cross-run registry". Behaviour pinned by
``tests/unit/test_case_issues_builder.py``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator


_BATCH = 10_000
_STATE_FILENAMES: tuple[str, ...] = (
    "executar.state.json",
)

_PROBLEMATIC_STATUSES: tuple[str, ...] = (
    "http_error", "provider_error", "empty",
    # unallocated_pid is its own table — exclude to avoid duplication.
)


def _iter_state_files(runs_root: Path) -> Iterable[Path]:
    for name in _STATE_FILENAMES:
        yield from runs_root.glob(f"**/{name}")


def _iter_obs_rows(state_path: Path) -> Iterator[tuple]:
    """Yield observation tuples ready for the staging INSERT.

    Shape: ``(classe, processo_id, status, error, ts, run_dir_name)``.
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
        meta = rec.get("fetch_meta")
        if not isinstance(meta, dict):
            continue
        status = meta.get("status")
        if not status:
            continue
        yield (
            classe, processo_id, status,
            meta.get("error"), meta.get("ts") or "", run_dir_name,
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
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _meta_obs (
            classe VARCHAR, processo_id INTEGER,
            status VARCHAR, error VARCHAR,
            ts VARCHAR, run_dir_name VARCHAR
        )
    """)
    obs_stream = (
        obs
        for state_file in _iter_state_files(runs_root)
        for obs in _iter_obs_rows(state_file)
    )
    for batch in _batched(obs_stream, _BATCH):
        con.executemany(
            "INSERT INTO _meta_obs VALUES (?, ?, ?, ?, ?, ?)",
            batch,
        )


def build_case_issues(con, *, runs_root: Path) -> int:
    """Populate the ``case_issues`` table from state.json walks.

    Returns the number of rows inserted. Idempotent against a fresh
    empty table (builder creates it from ``_SCHEMA_SQL`` before calling
    this). Bugs here must not break the rest of the warehouse build —
    caller wraps in try/except.
    """
    if not runs_root.exists():
        return 0

    _stream_observations(con, runs_root)

    # Aggregate per (classe, processo_id), filter to problematic
    # latest statuses, INSERT. Same arg_max-based last-write-wins
    # semantics as peca_issues — see that module's comment for the
    # behaviour-equivalence notes.
    problematic_in = ", ".join(f"'{s}'" for s in _PROBLEMATIC_STATUSES)
    con.execute(f"""
        INSERT INTO case_issues
        WITH agg AS (
            SELECT
                classe, processo_id,
                arg_max(status, ts) AS latest_meta_status,
                arg_max(error, ts) AS latest_error,
                COUNT(*) AS n_attempts_seen,
                MIN(NULLIF(ts, '')) AS first_seen_at,
                MAX(ts) AS last_seen_at,
                arg_max(run_dir_name, ts) AS last_run_dir
            FROM _meta_obs
            GROUP BY classe, processo_id
        )
        SELECT
            classe, processo_id, latest_meta_status, latest_error,
            n_attempts_seen, first_seen_at, last_seen_at, last_run_dir
        FROM agg
        WHERE latest_meta_status IN ({problematic_in})
    """)

    return con.execute("SELECT COUNT(*) FROM case_issues").fetchone()[0]
