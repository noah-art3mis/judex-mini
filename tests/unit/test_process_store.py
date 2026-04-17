"""Tests for src.process_store — append log + atomic compacted state.

Design covered:
- record() appends to log and updates state; state survives a fresh
  open of the same directory
- state writes are atomic (no partial files on crash)
- already_ok() reflects the latest recorded status per (classe, processo)
- errors() and write_errors_file() list only non-ok keys
- recover_state_from_log rebuilds state when state.json is missing
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.process_store import (
    AttemptRecord,
    SweepStore,
    load_retry_list,
    recover_state_from_log,
)


def _rec(
    classe: str, processo: int, status: str, attempt: int = 1, **extra
) -> AttemptRecord:
    return AttemptRecord(
        ts="2026-04-16T23:00:00+00:00",
        classe=classe,
        processo=processo,
        attempt=attempt,
        wall_s=0.5,
        status=status,
        error=extra.get("error"),
        retries=extra.get("retries", {}),
        diff_count=extra.get("diff_count", 0),
        anomaly_count=extra.get("anomaly_count", 0),
    )


def test_record_appends_to_log_and_updates_state(tmp_path: Path):
    store = SweepStore(tmp_path)
    store.record(_rec("ADI", 1, "ok"))
    store.record(_rec("ADI", 2, "fail", error="no incidente"))

    log_lines = (tmp_path / "sweep.log.jsonl").read_text().splitlines()
    assert len(log_lines) == 2
    first = json.loads(log_lines[0])
    assert first["classe"] == "ADI" and first["processo"] == 1 and first["status"] == "ok"

    state = json.loads((tmp_path / "sweep.state.json").read_text())
    assert set(state.keys()) == {"ADI_1", "ADI_2"}
    assert state["ADI_1"]["status"] == "ok"
    assert state["ADI_2"]["status"] == "fail"


def test_state_persists_across_store_reopen(tmp_path: Path):
    s1 = SweepStore(tmp_path)
    s1.record(_rec("ADI", 1, "ok"))
    s1.record(_rec("ADI", 2, "fail"))

    s2 = SweepStore(tmp_path)
    assert s2.already_ok("ADI", 1) is True
    assert s2.already_ok("ADI", 2) is False
    assert s2.already_ok("ADI", 99) is False


def test_latest_attempt_wins_on_retry(tmp_path: Path):
    store = SweepStore(tmp_path)
    store.record(_rec("ADI", 1, "fail", attempt=1, error="net"))
    store.record(_rec("ADI", 1, "ok", attempt=2))

    log_lines = (tmp_path / "sweep.log.jsonl").read_text().splitlines()
    assert len(log_lines) == 2

    state = json.loads((tmp_path / "sweep.state.json").read_text())
    assert state["ADI_1"]["status"] == "ok"
    assert state["ADI_1"]["attempt"] == 2


def test_errors_file_only_lists_non_ok(tmp_path: Path):
    store = SweepStore(tmp_path)
    store.record(_rec("ADI", 1, "ok"))
    store.record(_rec("ADI", 2, "fail", error="no incidente"))
    store.record(_rec("ADI", 3, "error", error="TimeoutError: ..."))

    err_path = store.write_errors_file()
    lines = err_path.read_text().splitlines()
    errors = [json.loads(line) for line in lines]

    keys = {(e["classe"], e["processo"]) for e in errors}
    assert keys == {("ADI", 2), ("ADI", 3)}


def test_errors_file_refreshed_after_successful_retry(tmp_path: Path):
    store = SweepStore(tmp_path)
    store.record(_rec("ADI", 1, "fail", attempt=1, error="net"))
    first_err = store.write_errors_file().read_text().splitlines()
    assert len(first_err) == 1

    store.record(_rec("ADI", 1, "ok", attempt=2))
    second_err = store.write_errors_file().read_text()
    assert second_err == ""


def test_load_retry_list_reads_errors_jsonl(tmp_path: Path):
    path = tmp_path / "sweep.errors.jsonl"
    path.write_text(
        '{"classe": "ADI", "processo": 2, "status": "fail"}\n'
        '{"classe": "ADI", "processo": 3, "status": "error"}\n'
    )
    got = load_retry_list(path)
    assert got == [("ADI", 2), ("ADI", 3)]


def test_recover_state_from_log_when_state_missing(tmp_path: Path):
    # Simulate: state.json crashed mid-write and was never created, log intact.
    log = tmp_path / "sweep.log.jsonl"
    log.write_text(
        '{"ts":"t","classe":"ADI","processo":1,"attempt":1,"wall_s":0.5,"status":"fail","error":"x","retries":{},"diff_count":0,"anomaly_count":0}\n'
        '{"ts":"t","classe":"ADI","processo":1,"attempt":2,"wall_s":0.5,"status":"ok","error":null,"retries":{},"diff_count":0,"anomaly_count":0}\n'
        '{"ts":"t","classe":"ADI","processo":2,"attempt":1,"wall_s":0.5,"status":"fail","error":"y","retries":{},"diff_count":0,"anomaly_count":0}\n'
    )
    recovered = recover_state_from_log(log)
    assert recovered["ADI_1"]["status"] == "ok"
    assert recovered["ADI_1"]["attempt"] == 2
    assert recovered["ADI_2"]["status"] == "fail"


def test_store_opens_cleanly_with_only_log_file(tmp_path: Path):
    # Same scenario: no state.json, log has entries. Opening the store
    # must rebuild the state from the log instead of starting empty.
    (tmp_path / "sweep.log.jsonl").write_text(
        '{"ts":"t","classe":"ADI","processo":1,"attempt":1,"wall_s":0.5,"status":"ok","error":null,"retries":{},"diff_count":0,"anomaly_count":0}\n'
    )
    store = SweepStore(tmp_path)
    assert store.already_ok("ADI", 1) is True


def test_atomic_state_write_leaves_no_tmp_after_success(tmp_path: Path):
    store = SweepStore(tmp_path)
    store.record(_rec("ADI", 1, "ok"))
    # No leftover .tmp files on a clean write.
    tmp_leftovers = list(tmp_path.glob("*.tmp"))
    assert tmp_leftovers == []


def test_log_is_appended_not_rewritten(tmp_path: Path):
    store = SweepStore(tmp_path)
    store.record(_rec("ADI", 1, "ok"))

    # Simulate a crash: reopen and record more. Log must retain prior line.
    store2 = SweepStore(tmp_path)
    store2.record(_rec("ADI", 2, "fail"))

    lines = (tmp_path / "sweep.log.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["processo"] == 1
    assert json.loads(lines[1])["processo"] == 2
