"""Generic append-log + atomic compacted-state store.

Shared skeleton behind `src/sweeps/process_store.py` (keyed by classe/processo)
and `src/sweeps/peca_store.py` (keyed by URL). Both subclasses supply:

- class-level filename constants (LOG_NAME, STATE_NAME, ERRORS_NAME)
- a `_state_key(rec_dict)` classmethod that derives the state dict key
  from a serialised record

Atomic-write contracts (same as the per-domain docstrings):

- `record()` appends a line to the log, flushes + fsyncs, then rewrites
  state atomically via temp-file + `os.replace`. A kill between the two
  loses at most the state update; the log replays cleanly.
- Opening on an existing directory picks up state if present, otherwise
  replays the log. Both writes survive torn state.
- `write_errors_file()` emits an atomic snapshot of non-ok rows.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from judex.utils.atomic_write import atomic_write_text


def replay_log(log_path: Path, key_fn: Callable[[dict], str]) -> dict[str, dict[str, Any]]:
    """Replay an append-only JSONL log into a compacted state dict.

    Later records overwrite earlier ones for the same key. Missing log
    returns an empty dict.
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
            state[key_fn(rec)] = rec
    return state


def read_url_list(jsonl_path: Path, field: str) -> list[dict[str, Any]]:
    """Read a JSONL file into a list of decoded dicts. Each subclass's
    `load_retry_list` picks the fields it cares about.
    """
    out: list[dict[str, Any]] = []
    with jsonl_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if field and field not in rec:
                continue
            out.append(rec)
    return out


class BaseStore:
    """Template for append-log + atomic-state stores.

    Subclasses must set LOG_NAME / STATE_NAME / ERRORS_NAME and override
    `_state_key(rec_dict)` to derive the per-record key from a serialised
    (dict) record.
    """

    LOG_NAME: str = ""
    STATE_NAME: str = ""
    ERRORS_NAME: str = ""

    def __init__(self, out_dir: Path) -> None:
        assert self.LOG_NAME and self.STATE_NAME and self.ERRORS_NAME, (
            "Subclass must define LOG_NAME/STATE_NAME/ERRORS_NAME"
        )
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.out_dir / self.LOG_NAME
        self.state_path = self.out_dir / self.STATE_NAME
        self.errors_path = self.out_dir / self.ERRORS_NAME

        if self.state_path.exists():
            self._state = json.loads(self.state_path.read_text())
        elif self.log_path.exists():
            self._state = replay_log(self.log_path, self._state_key)
            self._write_state_atomically()
        else:
            self._state = {}

    # Subclasses override.
    @classmethod
    def _state_key(cls, rec: dict[str, Any]) -> str:
        raise NotImplementedError

    # ----- Reads shared across subclasses -----

    def errors(self) -> list[dict[str, Any]]:
        return [rec for rec in self._state.values() if rec.get("status") != "ok"]

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return dict(self._state)

    # ----- Writes -----

    def _append_and_compact(self, rec_dict: dict[str, Any]) -> None:
        """Append to log (fsynced), then atomically rewrite state."""
        line = json.dumps(rec_dict, ensure_ascii=False)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._state[self._state_key(rec_dict)] = rec_dict
        self._write_state_atomically()

    def write_errors_file(self) -> Path:
        errs = self.errors()
        text = "".join(json.dumps(rec, ensure_ascii=False) + "\n" for rec in errs)
        atomic_write_text(self.errors_path, text, fsync=True)
        return self.errors_path

    def _write_state_atomically(self) -> None:
        atomic_write_text(
            self.state_path,
            json.dumps(self._state, ensure_ascii=False, indent=0),
            fsync=True,
        )
