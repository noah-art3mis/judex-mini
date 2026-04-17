"""Append-only log + atomic compacted state for validation sweeps.

Layout under a run directory:

    <out_dir>/
        sweep.log.jsonl     # append-only, one JSON line per attempt
        sweep.state.json    # atomic rewrite, one entry per (classe, processo)
        sweep.errors.jsonl  # derived from state, only non-ok entries

Guarantees:

- Every `record()` call appends a line to the log *and* rewrites state
  atomically via a temp file + `os.replace`. A kill -9 between the two
  loses at most the state update; the log is intact and replaying it
  reproduces the exact state (`recover_state_from_log`).
- `SweepStore(...)` on an existing directory picks up prior state. If
  `sweep.state.json` is absent but `sweep.log.jsonl` exists, state is
  recovered from the log so a torn write during a sweep is recoverable.
- Log lines are flushed + fsynced on every write. At the cost of one
  fsync per process (a few ms), the log survives power loss.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

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


def _key(classe: str, processo: int) -> str:
    return f"{classe}_{processo}"


def recover_state_from_log(log_path: Path) -> dict[str, dict[str, Any]]:
    """Replay the append-only log to reconstruct the compacted state.

    Later records overwrite earlier ones for the same (classe, processo),
    matching the record() contract where the latest attempt wins.
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
            state[_key(rec["classe"], rec["processo"])] = rec
    return state


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


class SweepStore:
    """Append-only log + compacted state for one sweep run.

    Constructor is cheap: loads state if present, recovers from log if
    only the log exists, otherwise starts empty. Subsequent record()
    calls are synchronous to disk.
    """

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
            # Persist the recovered state so subsequent opens are fast.
            self._write_state_atomically()
        else:
            self._state = {}

    # ----- Reads -----

    def already_ok(self, classe: str, processo: int) -> bool:
        rec = self._state.get(_key(classe, processo))
        return bool(rec and rec.get("status") == "ok")

    def attempt_count(self, classe: str, processo: int) -> int:
        rec = self._state.get(_key(classe, processo))
        return int(rec["attempt"]) if rec else 0

    def errors(self) -> list[dict[str, Any]]:
        return [rec for rec in self._state.values() if rec.get("status") != "ok"]

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return dict(self._state)

    # ----- Writes -----

    def record(self, rec: AttemptRecord) -> None:
        """Append to log, then atomically rewrite state."""
        line = json.dumps(asdict(rec), ensure_ascii=False)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

        self._state[_key(rec.classe, rec.processo)] = asdict(rec)
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
