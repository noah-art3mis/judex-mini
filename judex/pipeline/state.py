"""Persistent state for the unified pipeline.

A single JSON file under the run's ``--saida`` directory captures the
per-case DAG progress. The file is loaded once at process start,
held in memory for the life of the run, and written back as a single
atomic snapshot — never per-record. This is the lesson learned in
``judex/sweeps/peca_store.py`` on 2026-04-30: per-record rewrites of
a 50 MB state file capped throughput at ~0.1 rec/s; periodic
snapshot does not.

Layout:

    {
      "schema_version": 1,
      "started_at": "2026-05-02T22:00:00Z",
      "cases": {
        "HC-252920": {
          "fetch_meta": {"status": "ok", "ts": "...", "error": null},
          "fetch_bytes": {
            "<url>": {"status": "ok", "ts": "...", "error": null}
          },
          "extract_text": {
            "<url>": {"status": "ok", "ts": "...", "extractor": "pypdf"}
          }
        }
      }
    }

The case key is ``f"{classe}-{processo_id}"`` (string-only for JSON
fidelity). Tests pin the contracts; see ``tests/unit/test_pipeline_state.py``.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from judex.pipeline.models import TaskStatus


SCHEMA_VERSION = 1


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _case_key_str(case_key: tuple[str, int]) -> str:
    classe, processo = case_key
    return f"{classe}-{processo}"


@dataclass
class CaseRecord:
    """Per-case DAG progress.

    ``meta`` is one entry per case. ``bytes`` and ``text`` are dicts
    keyed by URL because a single case has many peças, and the
    scheduler needs to know which URLs have been seen.
    """

    meta: Optional[dict] = None
    bytes: dict[str, dict] = field(default_factory=dict)
    text: dict[str, dict] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "fetch_meta": self.meta,
            "fetch_bytes": self.bytes,
            "extract_text": self.text,
        }

    @classmethod
    def from_json(cls, raw: dict) -> CaseRecord:
        return cls(
            meta=raw.get("fetch_meta"),
            bytes=dict(raw.get("fetch_bytes") or {}),
            text=dict(raw.get("extract_text") or {}),
        )


class PipelineState:
    """In-memory state with atomic snapshot to disk.

    Construction is via ``PipelineState.load(path)``. The instance is
    not thread-safe; the scheduler is single-event-loop and updates
    state from one coroutine at a time.
    """

    def __init__(self, path: Path, cases: dict[str, CaseRecord], started_at: str):
        self._path = path
        self._cases = cases
        self._started_at = started_at

    @classmethod
    def load(cls, path: Path | str) -> PipelineState:
        path = Path(path)
        if not path.exists():
            return cls(path=path, cases={}, started_at=_now_iso())

        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"PipelineState schema mismatch at {path}: "
                f"file={raw.get('schema_version')} code={SCHEMA_VERSION}"
            )
        cases = {
            key: CaseRecord.from_json(payload)
            for key, payload in (raw.get("cases") or {}).items()
        }
        return cls(path=path, cases=cases, started_at=raw.get("started_at") or _now_iso())

    # ---- Query API ----

    def case_count(self) -> int:
        return len(self._cases)

    def meta_status(self, case_key: tuple[str, int]) -> Optional[TaskStatus]:
        rec = self._cases.get(_case_key_str(case_key))
        if rec is None or rec.meta is None:
            return None
        return rec.meta.get("status")

    def bytes_status(self, case_key: tuple[str, int], *, url: str) -> Optional[TaskStatus]:
        rec = self._cases.get(_case_key_str(case_key))
        if rec is None:
            return None
        entry = rec.bytes.get(url)
        return entry.get("status") if entry else None

    def text_status(self, case_key: tuple[str, int], *, url: str) -> Optional[TaskStatus]:
        rec = self._cases.get(_case_key_str(case_key))
        if rec is None:
            return None
        entry = rec.text.get(url)
        return entry.get("status") if entry else None

    def text_extractor(self, case_key: tuple[str, int], *, url: str) -> Optional[str]:
        rec = self._cases.get(_case_key_str(case_key))
        if rec is None:
            return None
        entry = rec.text.get(url)
        return entry.get("extractor") if entry else None

    def known_bytes_urls(self, case_key: tuple[str, int]) -> set[str]:
        rec = self._cases.get(_case_key_str(case_key))
        if rec is None:
            return set()
        return set(rec.bytes.keys())

    # ---- Resume predicates ----

    def is_meta_complete(self, case_key: tuple[str, int]) -> bool:
        return self.meta_status(case_key) == "ok"

    def is_bytes_complete(self, case_key: tuple[str, int], *, url: str) -> bool:
        return self.bytes_status(case_key, url=url) == "ok"

    def is_text_complete(
        self,
        case_key: tuple[str, int],
        *,
        url: str,
        required_extractor: Optional[str] = None,
    ) -> bool:
        if self.text_status(case_key, url=url) != "ok":
            return False
        if required_extractor is None:
            return True
        return self.text_extractor(case_key, url=url) == required_extractor

    # ---- Mutation API ----

    def record_meta(
        self,
        case_key: tuple[str, int],
        *,
        status: TaskStatus,
        error: Optional[str] = None,
    ) -> None:
        rec = self._ensure_case(case_key)
        rec.meta = {"status": status, "ts": _now_iso(), "error": error}

    def record_bytes(
        self,
        case_key: tuple[str, int],
        *,
        url: str,
        status: TaskStatus,
        error: Optional[str] = None,
    ) -> None:
        rec = self._ensure_case(case_key)
        rec.bytes[url] = {"status": status, "ts": _now_iso(), "error": error}

    def record_text(
        self,
        case_key: tuple[str, int],
        *,
        url: str,
        status: TaskStatus,
        extractor: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        rec = self._ensure_case(case_key)
        rec.text[url] = {
            "status": status,
            "ts": _now_iso(),
            "extractor": extractor,
            "error": error,
        }

    def _ensure_case(self, case_key: tuple[str, int]) -> CaseRecord:
        key = _case_key_str(case_key)
        if key not in self._cases:
            self._cases[key] = CaseRecord()
        return self._cases[key]

    # ---- Persistence ----

    def snapshot(self) -> None:
        """Atomic snapshot to disk. Either old contents survive or new
        contents land — never a partial write.

        Uses ``tempfile.NamedTemporaryFile`` in the same parent dir as
        the target (so ``os.replace`` is on the same filesystem),
        followed by ``os.replace`` for the cross-platform atomic
        rename. If ``os.replace`` raises, the tempfile is cleaned up
        in the ``finally``; the on-disk target is unchanged.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "schema_version": SCHEMA_VERSION,
            "started_at": self._started_at,
            "snapshot_at": _now_iso(),
            "cases": {key: rec.to_json() for key, rec in self._cases.items()},
        }
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")

        # NamedTemporaryFile with delete=False so we can os.replace it
        # into the target. The fd is closed before the rename.
        fd, tmp_path = tempfile.mkstemp(
            prefix=self._path.name + ".",
            suffix=".tmp",
            dir=self._path.parent,
        )
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(body)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._path)
        finally:
            # If os.replace succeeded, tmp_path is gone; if it failed,
            # remove the orphan tempfile. Either way, never leave it.
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
