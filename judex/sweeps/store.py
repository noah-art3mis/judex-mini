"""Generic append-log + atomic compacted-state store.

Shared skeleton behind `judex/sweeps/process_store.py` (keyed by
classe/processo) and `judex/sweeps/peca_store.py` (keyed by URL). Both
subclasses supply:

- class-level filename constants (LOG_NAME, STATE_NAME, ERRORS_NAME)
- a `_state_key(rec_dict)` classmethod that derives the state dict key
  from a serialised record

Durability + recovery contract:

- The append-only log (`<out>/<LOG_NAME>`) is the canonical durable
  record. Every `record()` flushes + fsyncs one JSON line.
- The compacted state file (`<out>/<STATE_NAME>`) is a *snapshot* of
  the in-memory state, atomically rewritten on a hybrid threshold (every
  ~10 seconds OR every ~500 records, whichever fires first) and on
  explicit `compact()` calls.
- On `__init__`, state is always reconstructed by replaying the log
  (state.json is treated as a write-only snapshot for external readers
  like `judex probe --watch`, never trusted on read). A fresh state.json
  is written at the end of `__init__`.
- A kill at any point loses at most pending log records that hadn't
  been fsynced (bounded to one record); state.json is rewritten
  atomically via temp-file + `os.replace` so external readers always see
  either the prior or the new snapshot, never partial.
- `write_errors_file()` emits an atomic snapshot of non-ok rows.

This shape replaces an earlier per-record state rewrite that scaled
O(records × state_size) and capped corpus-wide unsharded passes at
~0.13 rec/s on a 53 MB state. Threshold-based compaction makes
state-file write cost amortise to constant per record.
"""

from __future__ import annotations

import json
import os
import time
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

    DEFAULT_COMPACT_INTERVAL_SECONDS: float = 10.0
    DEFAULT_COMPACT_INTERVAL_RECORDS: int = 500

    def __init__(
        self,
        out_dir: Path,
        *,
        compact_interval_seconds: float | None = None,
        compact_interval_records: int | None = None,
    ) -> None:
        assert self.LOG_NAME and self.STATE_NAME and self.ERRORS_NAME, (
            "Subclass must define LOG_NAME/STATE_NAME/ERRORS_NAME"
        )
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.out_dir / self.LOG_NAME
        self.state_path = self.out_dir / self.STATE_NAME
        self.errors_path = self.out_dir / self.ERRORS_NAME

        self._compact_seconds: float = (
            compact_interval_seconds
            if compact_interval_seconds is not None
            else self.DEFAULT_COMPACT_INTERVAL_SECONDS
        )
        self._compact_records: int = (
            compact_interval_records
            if compact_interval_records is not None
            else self.DEFAULT_COMPACT_INTERVAL_RECORDS
        )
        self._records_since_compact: int = 0

        # Log is canonical: always replay to reconstruct in-memory state.
        # state.json is treated as a write-only snapshot for external readers.
        self._state = replay_log(self.log_path, self._state_key)

        # Write a fresh snapshot so external readers (probe --watch) see a
        # consistent file from process startup.
        self._write_state_atomically()
        self._last_compact_ts: float = time.monotonic()

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

    def _record(self, rec_dict: dict[str, Any]) -> None:
        """Append to the log (fsynced), update in-memory state, maybe-compact.

        State.json is rewritten when either threshold is exceeded; otherwise
        it stays at the last compacted snapshot. External readers see an
        atomic snapshot, never partial.
        """
        line = json.dumps(rec_dict, ensure_ascii=False)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._state[self._state_key(rec_dict)] = rec_dict
        self._records_since_compact += 1
        if self._should_compact():
            self.compact()

    def compact(self) -> None:
        """Atomically rewrite state.json with the current in-memory state.

        Resets the threshold counters. Safe to call at any time; idempotent
        if no records have been written since the last compact. Callers
        should invoke at process-exit / SIGTERM and at the end of a batch
        to leave a fresh snapshot on disk.
        """
        self._write_state_atomically()
        self._records_since_compact = 0
        self._last_compact_ts = time.monotonic()

    def _should_compact(self) -> bool:
        if self._records_since_compact >= self._compact_records:
            return True
        if (time.monotonic() - self._last_compact_ts) >= self._compact_seconds:
            return True
        return False

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
