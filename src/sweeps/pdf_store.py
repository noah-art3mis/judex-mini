"""Append-only log + atomic compacted state for PDF fetch runs.

Sibling of `src/sweeps/process_store.py`, keyed by URL instead of
(classe, processo). Both sit atop `src.sweeps.store.BaseStore` which owns
the atomic log/state contracts.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.sweeps.store import BaseStore, replay_log

LOG_NAME = "pdfs.log.jsonl"
STATE_NAME = "pdfs.state.json"
ERRORS_NAME = "pdfs.errors.jsonl"


@dataclass
class PdfAttemptRecord:
    ts: str
    url: str
    attempt: int
    wall_s: float
    # Status values across download + extract drivers:
    #   download: "ok" | "cached" | "http_error"
    #   extract:  "ok" | "cached" | "no_bytes" | "empty" | "provider_error" | "unknown_type"
    # Legacy `varrer-pdfs` also emitted "extract_error" (fetch+extract fused);
    # that driver was retired in the 2026-04-19 split.
    status: str
    error: Optional[str] = None
    error_type: Optional[str] = None
    http_status: Optional[int] = None
    # Extractor / producer label:
    #   download: "bytes" (always, regardless of outcome)
    #   extract:  "pypdf" | "rtf" | "mistral" | "chandra" | "unstructured"
    extractor: Optional[str] = None
    chars: Optional[int] = None
    processo_id: Optional[int] = None
    classe: Optional[str] = None
    doc_type: Optional[str] = None
    context: dict[str, Any] = field(default_factory=dict)


def _state_key_from_rec(rec: dict[str, Any]) -> str:
    return rec["url"]


def recover_state_from_log(log_path: Path) -> dict[str, dict[str, Any]]:
    """Replay the append-only log. Later records overwrite earlier ones per URL."""
    return replay_log(log_path, _state_key_from_rec)


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


class PdfStore(BaseStore):
    LOG_NAME = LOG_NAME
    STATE_NAME = STATE_NAME
    ERRORS_NAME = ERRORS_NAME

    @classmethod
    def _state_key(cls, rec: dict[str, Any]) -> str:
        return _state_key_from_rec(rec)

    def already_ok(self, url: str) -> bool:
        rec = self._state.get(url)
        return bool(rec and rec.get("status") == "ok")

    def attempt_count(self, url: str) -> int:
        rec = self._state.get(url)
        return int(rec["attempt"]) if rec else 0

    def record(self, rec: PdfAttemptRecord) -> None:
        self._append_and_compact(asdict(rec))
