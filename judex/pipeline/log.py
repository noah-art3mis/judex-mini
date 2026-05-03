"""Append-only log + errors derivation for the unified pipeline.

The unified pipeline ships a single compacted state file
(``executar.state.json``) for fast resume. That snapshot is the *fast*
path; the canonical durable record is the append-only log here:
``executar.log.jsonl``. One JSON line per task outcome, fsynced before
return.

Why both. The legacy three-command chain shipped both for the same
reason: a hard kill (SIGKILL, OOM, VM suspend) that lands between two
periodic snapshot writes will lose the in-memory deltas — the snapshot
on disk is stale by up to ``snapshot_interval_seconds``. The log is
durable per record. ``PipelineState.open()`` reconciles snapshot+log
on every fresh start (read snapshot → replay every log row whose
``ts > snapshot_at``), so a survivor of a kill comes back exactly
where it left off regardless of when the last snapshot ran (ADR-0006).

Why log AND state, not log alone. Reading a 100k-row JSONL on every
process start would dominate cold-start cost on a year-corpus run.
``executar.state.json`` exists so ``probe`` can read the full state in
one stat+read, and so ``open()``'s replay only walks the suffix of
the log written after the snapshot was taken — bounded work.

Also derives ``executar.errors.jsonl`` — one row per non-ok target
across all three task kinds, in the same shape as
``judex.sweeps.peca_store``'s errors file so
``judex.sweeps.error_triage.classify_error`` works without translation.
This is what powers ``--retentar-de`` retry of just the failed targets.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from judex.pipeline.models import Task, TaskKind, TaskStatus
from judex.pipeline.state import PipelineState
from judex.utils.atomic_write import atomic_write_text


LOG_NAME = "executar.log.jsonl"
ERRORS_NAME = "executar.errors.jsonl"


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


@dataclass
class TaskLogRecord:
    """One row of ``executar.log.jsonl``.

    Field shape mirrors :class:`judex.sweeps.peca_store.PecaAttemptRecord`
    where it overlaps so :func:`judex.sweeps.error_triage.classify_error`
    works without translation. Pipeline-specific extras live alongside.

    ``run_id`` is the journal's staleness defence (ADR-0006 § D7) — every
    row carries the run_id of the live ``PipelineState`` that produced
    it. ``PipelineState.open()``'s replay path raises ``StaleLogError``
    if a row's run_id doesn't match the snapshot's, preventing a prior
    aborted run's rows from silently polluting a fresh resume.

    ``retry_count`` carries the value the live ``record_*`` mutator
    computed at write time so replay (ADR-0006 § D4) can preserve it
    rather than re-incrementing through the mutator on each replayed
    row.
    """

    ts: str
    run_id: str
    kind: TaskKind
    classe: str
    processo: int
    status: TaskStatus
    wall_s: float
    url: Optional[str] = None
    doc_type: Optional[str] = None
    extractor: Optional[str] = None
    # Output size of an extract_text task — surfaced on the per-task tail
    # line (`pypdf 18234ch`) so the operator sees OCR output volume in
    # real time without reading cached files. None on non-extract_text
    # rows and on extract_text failures (no_bytes, provider_error).
    chars: Optional[int] = None
    error: Optional[str] = None
    http_status: Optional[int] = None
    pool: Optional[str] = None
    retry_count: int = 0
    # CliffDetector reading at write-time. None on cache-fast-path rows
    # (no HTTP, no measurement). When present, mirrors the legacy
    # ``regime_kwargs`` shape so analisar-regimes consumes the row
    # without translation.
    regime: Optional[str] = None
    regime_fail_rate: Optional[float] = None
    regime_p95_wall_s: Optional[float] = None
    regime_promoted_by: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "run_id": self.run_id,
            "kind": self.kind,
            "classe": self.classe,
            "processo": self.processo,
            "status": self.status,
            "wall_s": self.wall_s,
            "url": self.url,
            "doc_type": self.doc_type,
            "extractor": self.extractor,
            "chars": self.chars,
            "error": self.error,
            "http_status": self.http_status,
            "pool": self.pool,
            "retry_count": self.retry_count,
            "regime": self.regime,
            "regime_fail_rate": self.regime_fail_rate,
            "regime_p95_wall_s": self.regime_p95_wall_s,
            "regime_promoted_by": self.regime_promoted_by,
        }


class PipelineLog:
    """Append-only writer for ``executar.log.jsonl``.

    One line per task outcome, fsynced before return. The fsync cost
    (~1ms per record on a typical SSD) is what makes the log durable
    against process kills, OOM, and VM suspend.

    Not thread-safe by design — the scheduler is single-event-loop and
    appends from one coroutine at a time (the `_run_one` body, after
    the handler returns). If a future deepening fans out
    log-emission across threads, wrap append() in a threading.Lock.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: TaskLogRecord) -> None:
        line = json.dumps(record.to_json(), ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())


# ``recover_state_from_log`` was retired by ADR-0006: ``PipelineState.open()``
# now reconciles snapshot + log natively (read snapshot → replay every
# log row whose ``ts > snapshot_at``), so the SIGKILL-recovery path is
# automatic and the standalone replay function is redundant. Callers
# that previously did the "log fresher than snapshot" mtime check now
# just call ``PipelineState.open(saida=saida)`` — the journal handles it.
#
# Replay also bypasses the live ``record_*`` mutators (ADR-0006 § D4 /
# E1) so retry_count is preserved from the row rather than re-incremented
# per replayed row — a correctness bug the old recovery function carried.
#
# Note: dev added ``chars`` to the per-row schema after this commit's
# parent. ``_apply_log_row`` in ``state.py`` should preserve it on
# replay; the dev-side ``record_text`` and ``record_bytes`` mutators
# accept ``chars`` as a kwarg.


# Statuses that mean "this target is in the desired terminal state" — not
# errors, even though they're not literally "ok". ``skipped_cached`` is
# the sidecar-skip outcome on extract_text: cached text already matches
# the requested provider, so re-OCR was deliberately skipped. Including
# either in ``executar.errors.jsonl`` would re-seed completed work on
# the next ``--retentar-de`` pass.
_TERMINAL_OK_STATUSES: frozenset[str] = frozenset({"ok", "skipped_cached"})


def _iter_state_errors(state: PipelineState, targets: list[tuple[str, int]]):
    """Yield ``TaskLogRecord``-shaped dicts for every non-ok target.

    Walks the three stages per case, in DAG order. Each yielded dict is
    the projection of the in-memory state record onto the log/errors
    schema — same fields, same names — so the caller can write JSONL
    directly.
    """
    for case_key in targets:
        classe, processo = case_key
        meta_status = state.meta_status(case_key)
        if meta_status is not None and meta_status not in _TERMINAL_OK_STATUSES:
            yield {
                "kind": "fetch_meta",
                "classe": classe,
                "processo": processo,
                "status": meta_status,
                "url": None,
                "doc_type": None,
                "extractor": None,
                "error": _meta_error(state, case_key),
            }
        for url in sorted(state.known_bytes_urls(case_key)):
            bytes_status = state.bytes_status(case_key, url=url)
            doc_type = state.bytes_doc_type(case_key, url=url)
            if bytes_status is not None and bytes_status not in _TERMINAL_OK_STATUSES:
                yield {
                    "kind": "fetch_bytes",
                    "classe": classe,
                    "processo": processo,
                    "status": bytes_status,
                    "url": url,
                    "doc_type": doc_type,
                    "extractor": None,
                    "error": _bytes_error(state, case_key, url=url),
                }
                continue
            text_status = state.text_status(case_key, url=url)
            if text_status is not None and text_status not in _TERMINAL_OK_STATUSES:
                yield {
                    "kind": "extract_text",
                    "classe": classe,
                    "processo": processo,
                    "status": text_status,
                    "url": url,
                    "doc_type": doc_type,
                    "extractor": state.text_extractor(case_key, url=url),
                    "error": _text_error(state, case_key, url=url),
                }


def _meta_error(state: PipelineState, case_key: tuple[str, int]) -> Optional[str]:
    rec = state._cases.get(f"{case_key[0]}-{case_key[1]}")  # noqa: SLF001
    if rec is None or rec.meta is None:
        return None
    return rec.meta.get("error")


def _bytes_error(
    state: PipelineState, case_key: tuple[str, int], *, url: str,
) -> Optional[str]:
    rec = state._cases.get(f"{case_key[0]}-{case_key[1]}")  # noqa: SLF001
    if rec is None:
        return None
    entry = rec.bytes.get(url)
    return entry.get("error") if entry else None


def _text_error(
    state: PipelineState, case_key: tuple[str, int], *, url: str,
) -> Optional[str]:
    rec = state._cases.get(f"{case_key[0]}-{case_key[1]}")  # noqa: SLF001
    if rec is None:
        return None
    entry = rec.text.get(url)
    return entry.get("error") if entry else None


def derive_errors_file(
    saida: Path | str,
    state: PipelineState,
    targets: list[tuple[str, int]],
) -> Path:
    """Write ``executar.errors.jsonl`` from the final in-memory state.

    One line per non-ok ``(case_key, kind, [url])``. Atomically written
    via ``atomic_write_text`` so external readers (``--retentar-de``,
    a follow-up ``judex executar --retentar-de``) never see a partial
    file. Returns the errors file path.
    """
    saida = Path(saida)
    out = saida / ERRORS_NAME
    rows = list(_iter_state_errors(state, targets))
    text = "".join(json.dumps(rec, ensure_ascii=False) + "\n" for rec in rows)
    atomic_write_text(out, text, fsync=True)
    return out


def classify_unified_error(row: dict[str, Any]) -> str:
    """Classify one ``executar.errors.jsonl`` row → ``transient`` /
    ``terminal`` / ``cross_stage`` / ``ok``.

    Operates on the unified pipeline's ``TaskStatus`` vocabulary.
    Sibling of :func:`judex.sweeps.error_triage.classify_error` (which
    knows the legacy stage-specific status names: ``fail`` /
    ``empty_response`` / ``non_document_response`` / etc). Both
    classifiers exist because the two code paths emit different status
    strings; collapsing them by translating in one direction would
    break the other side's tests.

    The decision table mirrors :func:`_is_retryable_status` in the
    scheduler — same policy, surfaced here for ``--retentar-de``.
    """
    status = row.get("status")
    if status in ("ok", "skipped_cached"):
        return "ok"
    if status == "no_bytes":
        return "cross_stage"
    if status in ("http_error", "provider_error"):
        return "transient"
    # ``unallocated_pid`` and ``empty`` are terminal: the case genuinely
    # doesn't exist (404-equivalent) or the document genuinely contains
    # no text (real empty PDF, or unsupported magic bytes). Re-running
    # would just re-discover the same outcome.
    return "terminal"


def read_errors_file(path: Path | str) -> list[dict[str, Any]]:
    """Read every row from an ``executar.errors.jsonl`` into a list of dicts.

    Counterpart to :func:`derive_errors_file` for ``--retentar-de``
    consumers. Malformed lines (truncated tail) are silently skipped.
    """
    out: list[dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def make_log_record(
    *,
    task: Task,
    run_id: str,
    status: TaskStatus,
    wall_s: float,
    retry_count: int = 0,
    error: Optional[str] = None,
    extractor: Optional[str] = None,
    chars: Optional[int] = None,
    http_status: Optional[int] = None,
    regime: Optional[str] = None,
    regime_fail_rate: Optional[float] = None,
    regime_p95_wall_s: Optional[float] = None,
    regime_promoted_by: Optional[str] = None,
) -> TaskLogRecord:
    """Build a :class:`TaskLogRecord` from a task + outcome.

    Helper around :class:`TaskLogRecord` that pulls ``classe``,
    ``processo``, ``url``, ``doc_type``, and ``pool`` straight off the
    task — keeping the scheduler call-site short.

    ``run_id`` is the journal's staleness defence (ADR-0006 § D7) —
    the scheduler reads it off ``state.run_id`` and threads it through
    every log row it writes. ``retry_count`` carries the value the
    live ``record_*`` mutator computed at write time so replay
    preserves it (ADR-0006 § D4 / E1).
    """
    classe, processo = task.case_key
    return TaskLogRecord(
        ts=_now_iso(),
        run_id=run_id,
        kind=task.kind,
        classe=classe,
        processo=processo,
        status=status,
        wall_s=wall_s,
        url=task.payload.get("url"),
        doc_type=task.payload.get("doc_type"),
        extractor=extractor,
        chars=chars,
        error=error,
        http_status=http_status,
        pool=task.pool,
        retry_count=retry_count,
        regime=regime,
        regime_fail_rate=regime_fail_rate,
        regime_p95_wall_s=regime_p95_wall_s,
        regime_promoted_by=regime_promoted_by,
    )
