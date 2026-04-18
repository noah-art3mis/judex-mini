"""Append-only log + atomic compacted state for validation sweeps.

Layout under a run directory:

    <out_dir>/
        sweep.log.jsonl     # append-only, one JSON line per attempt
        sweep.state.json    # atomic rewrite, one entry per (classe, processo)
        sweep.errors.jsonl  # derived from state, only non-ok entries

Thin wrapper over `src.sweeps.store.BaseStore` — it owns the atomic contracts
and replay; this module only carries the per-domain record shape and
the (classe, processo) → state-key derivation.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.sweeps.store import BaseStore, replay_log

LOG_NAME = "sweep.log.jsonl"
STATE_NAME = "sweep.state.json"
ERRORS_NAME = "sweep.errors.jsonl"


@dataclass
class AttemptRecord:
    ts: str
    classe: str
    processo: int
    attempt: int
    wall_s: float
    status: str  # "ok" | "fail" | "error"
    error: Optional[str]
    error_type: Optional[str] = None  # Exception class name, e.g. "HTTPError"
    http_status: Optional[int] = None  # HTTP status if an HTTP error
    error_url: Optional[str] = None    # URL that failed
    retries: dict[str, int] = field(default_factory=dict)
    diff_count: int = 0
    anomaly_count: int = 0
    regime: Optional[str] = None  # CliffDetector regime at time of record


def _key(classe: str, processo: int) -> str:
    return f"{classe}_{processo}"


def _state_key_from_rec(rec: dict[str, Any]) -> str:
    return _key(rec["classe"], rec["processo"])


def recover_state_from_log(log_path: Path) -> dict[str, dict[str, Any]]:
    """Replay the append-only log to reconstruct the compacted state.

    Later records overwrite earlier ones for the same (classe, processo).
    """
    return replay_log(log_path, _state_key_from_rec)


def load_retry_list(errors_path: Path) -> list[tuple[str, int]]:
    """Read `sweep.errors.jsonl` → list of (classe, processo) to retry."""
    out: list[tuple[str, int]] = []
    with errors_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            out.append((rec["classe"], int(rec["processo"])))
    return out


class SweepStore(BaseStore):
    LOG_NAME = LOG_NAME
    STATE_NAME = STATE_NAME
    ERRORS_NAME = ERRORS_NAME

    @classmethod
    def _state_key(cls, rec: dict[str, Any]) -> str:
        return _state_key_from_rec(rec)

    def already_ok(self, classe: str, processo: int) -> bool:
        rec = self._state.get(_key(classe, processo))
        return bool(rec and rec.get("status") == "ok")

    def attempt_count(self, classe: str, processo: int) -> int:
        rec = self._state.get(_key(classe, processo))
        return int(rec["attempt"]) if rec else 0

    def record(self, rec: AttemptRecord) -> None:
        self._append_and_compact(asdict(rec))
