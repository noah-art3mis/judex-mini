"""Build the cross-run ``case_issues`` warehouse table.

Sibling of ``peca_issues`` but case-id-keyed instead of URL-keyed.
Captures cases where the *portal-side* fetch_meta task failed —
SSL storms on a contiguous case-id range, persistent HTTP errors
on case-meta, etc. Distinct from ``unallocated_pids`` (which is
terminal-by-STF: "case-id was never bound to a processo").

Aggregates ``fetch_meta`` observations across every state.json file
under a runs root. One row per (classe, processo_id). Rows with
``latest_meta_status='ok'`` are excluded — the registry exists to
surface *problems*, not noise.

See CONTEXT.md § "Cross-run registry".
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


_STATE_FILENAMES: tuple[str, ...] = (
    "executar.state.json",
)


@dataclass(frozen=True)
class _MetaObservation:
    """One fetch_meta data point pulled from a single state.json file."""

    classe: str
    processo_id: int
    status: str
    error: Optional[str]
    ts: str
    run_dir_name: str


@dataclass
class _CaseRow:
    """One aggregated row per (classe, processo_id)."""

    classe: str
    processo_id: int
    latest_meta_status: Optional[str] = None
    latest_error: Optional[str] = None
    n_attempts_seen: int = 0
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    last_run_dir: Optional[str] = None
    _all_ts: list[str] = field(default_factory=list)


def _iter_state_files(runs_root: Path) -> Iterable[Path]:
    for name in _STATE_FILENAMES:
        yield from runs_root.glob(f"**/{name}")


def _iter_observations(state_path: Path) -> Iterable[_MetaObservation]:
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
        yield _MetaObservation(
            classe=classe,
            processo_id=processo_id,
            status=status,
            error=meta.get("error"),
            ts=meta.get("ts") or "",
            run_dir_name=run_dir_name,
        )


def _aggregate(
    observations: Iterable[_MetaObservation],
) -> dict[tuple[str, int], _CaseRow]:
    by_key: dict[tuple[str, int], _CaseRow] = {}
    for obs in observations:
        key = (obs.classe, obs.processo_id)
        row = by_key.get(key)
        if row is None:
            row = _CaseRow(classe=obs.classe, processo_id=obs.processo_id)
            by_key[key] = row
        row.n_attempts_seen += 1
        row._all_ts.append(obs.ts)
        if row.last_seen_at is None or obs.ts > row.last_seen_at:
            row.last_seen_at = obs.ts
            row.latest_meta_status = obs.status
            row.latest_error = obs.error
            row.last_run_dir = obs.run_dir_name

    for row in by_key.values():
        ts_values = [t for t in row._all_ts if t]
        row.first_seen_at = min(ts_values) if ts_values else None
    return by_key


_PROBLEMATIC_STATUSES: frozenset[str] = frozenset({
    "http_error", "provider_error", "empty",
    # unallocated_pid is its own table — exclude to avoid duplication.
})


def _bulk_insert(rows: dict[tuple[str, int], _CaseRow], con) -> int:
    """Filter to problematic rows and INSERT. Returns row count inserted."""
    payload = [
        (
            row.classe,
            row.processo_id,
            row.latest_meta_status,
            row.latest_error,
            row.n_attempts_seen,
            row.first_seen_at,
            row.last_seen_at,
            row.last_run_dir,
        )
        for row in rows.values()
        if row.latest_meta_status in _PROBLEMATIC_STATUSES
    ]
    if not payload:
        return 0
    con.executemany(
        "INSERT INTO case_issues VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        payload,
    )
    return len(payload)


def build_case_issues(con, *, runs_root: Path) -> int:
    """Populate the ``case_issues`` table from state.json walks.

    Returns the number of rows inserted. Idempotent against a fresh
    empty table (builder creates it from ``_SCHEMA_SQL`` before calling
    this). Bugs here must not break the rest of the warehouse build —
    caller wraps in try/except.
    """
    if not runs_root.exists():
        return 0
    observations: list[_MetaObservation] = []
    for state_file in _iter_state_files(runs_root):
        observations.extend(_iter_observations(state_file))

    rows = _aggregate(observations)
    return _bulk_insert(rows, con)
