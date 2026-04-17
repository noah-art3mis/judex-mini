"""Append-only log + atomic compacted state for PDF fetch runs.

Sibling of `src/process_store.py`. Keyed by URL (one row per PDF),
same atomic-write contracts:

- Every `record()` appends to `pdfs.log.jsonl` (flushed + fsynced) then
  atomically rewrites `pdfs.state.json` via a temp file + `os.replace`.
- Opening a directory that has a log but no state file rebuilds state
  from the log (torn-write recovery).
- `write_errors_file()` emits `pdfs.errors.jsonl` atomically, listing
  only rows whose latest attempt was non-ok.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

LOG_NAME = "pdfs.log.jsonl"
STATE_NAME = "pdfs.state.json"
ERRORS_NAME = "pdfs.errors.jsonl"


@dataclass
class PdfAttemptRecord:
    ts: str
    url: str
    attempt: int
    wall_s: float
    status: str  # "ok" | "empty" | "http_error" | "extract_error" | "unknown_type"
    error: Optional[str] = None
    error_type: Optional[str] = None
    http_status: Optional[int] = None
    extractor: Optional[str] = None  # "pypdf" | "rtf" | "unstructured_api" | "cache"
    chars: Optional[int] = None
    processo_id: Optional[int] = None
    classe: Optional[str] = None
    doc_type: Optional[str] = None
    context: dict[str, Any] = field(default_factory=dict)


def recover_state_from_log(log_path: Path) -> dict[str, dict[str, Any]]:
    """Replay the append-only log to reconstruct the compacted state.

    Later records overwrite earlier ones for the same URL.
    """
    state: dict[str, dict[str, Any]] = {}
    if not log_path.exists():
        return state
    with log_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            state[rec["url"]] = rec
    return state


def load_retry_list(errors_path: Path) -> list[str]:
    """Read `pdfs.errors.jsonl` → list of URLs to retry."""
    out: list[str] = []
    with errors_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line)["url"])
    return out


class PdfStore:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.out_dir / LOG_NAME
        self.state_path = self.out_dir / STATE_NAME
        self.errors_path = self.out_dir / ERRORS_NAME

        if self.state_path.exists():
            self._state = json.loads(self.state_path.read_text())
        elif self.log_path.exists():
            self._state = recover_state_from_log(self.log_path)
            self._write_state_atomically()
        else:
            self._state = {}

    # ----- Reads -----

    def already_ok(self, url: str) -> bool:
        rec = self._state.get(url)
        return bool(rec and rec.get("status") == "ok")

    def attempt_count(self, url: str) -> int:
        rec = self._state.get(url)
        return int(rec["attempt"]) if rec else 0

    def errors(self) -> list[dict[str, Any]]:
        return [rec for rec in self._state.values() if rec.get("status") != "ok"]

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return dict(self._state)

    # ----- Writes -----

    def record(self, rec: PdfAttemptRecord) -> None:
        """Append to log, then atomically rewrite state."""
        line = json.dumps(asdict(rec), ensure_ascii=False)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._state[rec.url] = asdict(rec)
        self._write_state_atomically()

    def write_errors_file(self) -> Path:
        errs = self.errors()
        tmp = self.errors_path.with_suffix(self.errors_path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for rec in errs:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.errors_path)
        return self.errors_path

    # ----- Internals -----

    def _write_state_atomically(self) -> None:
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=0)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.state_path)
