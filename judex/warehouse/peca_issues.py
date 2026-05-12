"""Build the cross-run ``peca_issues`` warehouse table.

Walks every ``executar.state.json`` (and legacy ``pdfs.state.json``)
under a runs root, aggregates per-URL state across runs (latest
status, attempt count, first/last seen), enriches with filesystem
sidecars (extractor, dismissal) and warehouse joins (doc_type from
andamentos/documentos, n_chars from pdfs).

The result is a single queryable table that answers "what's the
latest state of URL X across all runs and time?" without grepping
run dirs.

PRD: ``.scratch/peca-registry/PRD.md`` sub-issue 01.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from judex.analysis.peca_quality import is_suspicious_short


_STATE_FILENAMES: tuple[str, ...] = (
    "executar.state.json",
    "pdfs.state.json",     # legacy three-command chain
)


def _sha1(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _UrlObservation:
    """One per-URL data point pulled from a single state.json file."""

    url: str
    classe: str
    processo_id: int
    status: str
    ts: str
    run_dir_name: str
    retry_count: int


def _iter_state_files(runs_root: Path) -> Iterable[Path]:
    """Yield every state.json file under ``runs_root`` (any depth)."""
    for name in _STATE_FILENAMES:
        yield from runs_root.glob(f"**/{name}")


def _iter_observations(state_path: Path) -> Iterable[_UrlObservation]:
    """Yield observations for every URL with a recorded status in
    ``state_path``. Malformed files are skipped silently — the rest of
    the build must converge even if one run dir's state.json is
    half-written.
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
                yield _UrlObservation(
                    url=url,
                    classe=classe,
                    processo_id=processo_id,
                    status=status,
                    ts=entry.get("ts") or "",
                    run_dir_name=run_dir_name,
                    retry_count=int(entry.get("retry_count") or 0),
                )


@dataclass
class _PecaRow:
    """One aggregated row per URL — what lands in the peca_issues table."""

    url: str
    sha1: str
    classe: Optional[str] = None
    processo_id: Optional[int] = None
    doc_type: Optional[str] = None
    latest_status: Optional[str] = None
    latest_extractor: Optional[str] = None
    n_chars: Optional[int] = None
    is_suspicious_short: bool = False
    n_attempts_seen: int = 0
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    last_run_dir: Optional[str] = None
    dismissed_at: Optional[str] = None
    dismissed_reason: Optional[str] = None
    _all_ts: list[str] = field(default_factory=list)


def _aggregate(observations: Iterable[_UrlObservation]) -> dict[str, _PecaRow]:
    """Collapse observations to one row per URL, last-write-wins on ts."""
    by_url: dict[str, _PecaRow] = {}
    for obs in observations:
        row = by_url.get(obs.url)
        if row is None:
            row = _PecaRow(url=obs.url, sha1=_sha1(obs.url))
            by_url[obs.url] = row
        row.n_attempts_seen += 1
        row._all_ts.append(obs.ts)
        # last-write-wins on the latest ts; classe/processo_id should be
        # stable per URL so taking the latest's is fine.
        if row.last_seen_at is None or obs.ts > row.last_seen_at:
            row.last_seen_at = obs.ts
            row.latest_status = obs.status
            row.last_run_dir = obs.run_dir_name
            row.classe = obs.classe
            row.processo_id = obs.processo_id

    for row in by_url.values():
        ts_values = [t for t in row._all_ts if t]
        row.first_seen_at = min(ts_values) if ts_values else None
    return by_url


def _enrich_filesystem(
    rows: dict[str, _PecaRow], pecas_texto_root: Path,
) -> None:
    """Populate ``latest_extractor`` and dismissal fields from sidecars
    on disk. One directory scan instead of N stat calls per URL."""
    if not pecas_texto_root.exists():
        return
    extractors_by_sha: dict[str, str] = {}
    for ext_path in pecas_texto_root.glob("*.extractor"):
        try:
            extractors_by_sha[ext_path.stem] = (
                ext_path.read_bytes().decode("utf-8").strip() or None
            )
        except OSError:
            continue

    dismissals_by_sha: dict[str, dict[str, Any]] = {}
    for dis_path in pecas_texto_root.glob("*.dismissed.json"):
        sha = dis_path.name.split(".", 1)[0]
        try:
            dismissals_by_sha[sha] = json.loads(
                dis_path.read_bytes().decode("utf-8")
            )
        except (OSError, ValueError):
            continue

    for row in rows.values():
        row.latest_extractor = extractors_by_sha.get(row.sha1)
        dismissal = dismissals_by_sha.get(row.sha1)
        if dismissal:
            row.dismissed_at = dismissal.get("dismissed_at")
            row.dismissed_reason = dismissal.get("reason")


def _enrich_warehouse_joins(rows: dict[str, _PecaRow], con) -> None:
    """Pull ``doc_type`` (from andamentos / documentos) and ``n_chars``
    (from pdfs) into each row. One bulk SELECT each, in-memory join."""
    url_to_doc_type: dict[str, str] = {}
    try:
        for url, doc_type in con.execute(
            "SELECT link_url, link_tipo FROM andamentos "
            "WHERE link_url IS NOT NULL"
        ).fetchall():
            url_to_doc_type[url] = doc_type
    except Exception:
        pass
    try:
        for url, doc_type in con.execute(
            "SELECT url, doc_type FROM documentos WHERE url IS NOT NULL"
        ).fetchall():
            url_to_doc_type.setdefault(url, doc_type)
    except Exception:
        pass

    sha1_to_chars: dict[str, int] = {}
    try:
        for sha1, n_chars in con.execute(
            "SELECT sha1, n_chars FROM pdfs"
        ).fetchall():
            sha1_to_chars[sha1] = n_chars
    except Exception:
        pass

    for row in rows.values():
        row.doc_type = url_to_doc_type.get(row.url)
        row.n_chars = sha1_to_chars.get(row.sha1)
        row.is_suspicious_short = is_suspicious_short(row.n_chars, row.doc_type)


def _bulk_insert(rows: dict[str, _PecaRow], con) -> None:
    if not rows:
        return
    payload = [
        (
            r.url, r.sha1, r.classe, r.processo_id, r.doc_type,
            r.latest_status, r.latest_extractor, r.n_chars,
            r.is_suspicious_short, r.n_attempts_seen,
            r.first_seen_at, r.last_seen_at, r.last_run_dir,
            r.dismissed_at, r.dismissed_reason,
        )
        for r in rows.values()
    ]
    con.executemany(
        "INSERT INTO peca_issues VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        payload,
    )


def build_peca_issues(
    con,
    *,
    runs_root: Path,
    pecas_texto_root: Path,
) -> int:
    """Populate the ``peca_issues`` table from disk + warehouse joins.

    Returns the number of rows inserted. The function is idempotent
    against a freshly-CREATEd empty table (the warehouse builder
    creates the table from ``_SCHEMA_SQL`` before calling this).

    Bugs in this pass must not break the rest of the warehouse build
    — the caller wraps the call in try/except so an error here logs
    + skips the table rather than aborting the rebuild.
    """
    if not runs_root.exists():
        return 0
    observations: list[_UrlObservation] = []
    for state_file in _iter_state_files(runs_root):
        observations.extend(_iter_observations(state_file))

    rows = _aggregate(observations)
    _enrich_filesystem(rows, pecas_texto_root)
    _enrich_warehouse_joins(rows, con)
    _bulk_insert(rows, con)
    return len(rows)
