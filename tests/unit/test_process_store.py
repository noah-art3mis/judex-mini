"""Tests for src.sweeps.process_store — append log + atomic compacted state.

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

from judex.sweeps.process_store import (
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

    state = store.snapshot()
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

    state = store.snapshot()
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


# ----- filter_skip + body_head land in the on-disk log -----------------------
# Motivation: these two fields are the only way, post-sweep, to tell
# CliffDetector's per-record decision apart from the raw status, and to
# distinguish a real STF "unallocated" response from a hypothetical proxy
# soft-block. Without them the diagnostics are forever.


def test_filter_skip_persists_to_sweep_log(tmp_path: Path):
    store = SweepStore(tmp_path)
    store.record(
        AttemptRecord(
            ts="2026-04-18T00:00:00+00:00",
            classe="HC",
            processo=1,
            attempt=1,
            wall_s=1.8,
            status="fail",
            error="scrape returned None (incidente not resolved)",
            error_type="NoIncidente",
            filter_skip=True,
        )
    )
    line = (tmp_path / "sweep.log.jsonl").read_text().splitlines()[0]
    rec = json.loads(line)
    assert rec["filter_skip"] is True


def test_body_head_persists_on_noincidente_record(tmp_path: Path):
    store = SweepStore(tmp_path)
    store.record(
        AttemptRecord(
            ts="2026-04-18T00:00:00+00:00",
            classe="HC",
            processo=1,
            attempt=1,
            wall_s=1.8,
            status="fail",
            error="scrape returned None (incidente not resolved)",
            error_type="NoIncidente",
            body_head="/processos/listarProcessos.asp?erro=1",
        )
    )
    line = (tmp_path / "sweep.log.jsonl").read_text().splitlines()[0]
    rec = json.loads(line)
    assert rec["body_head"] == "/processos/listarProcessos.asp?erro=1"


def test_filter_skip_and_body_head_default_to_none(tmp_path: Path):
    store = SweepStore(tmp_path)
    store.record(_rec("ADI", 1, "ok"))
    rec = json.loads((tmp_path / "sweep.log.jsonl").read_text().splitlines()[0])
    assert rec["filter_skip"] is None
    assert rec["body_head"] is None


# ----- Threshold-based state.json compaction -----------------------------
# Motivation: state.json is a periodic snapshot for external readers
# (judex probe --watch), not rewritten per record. The log is the durable
# canonical record; state.json is updated when either threshold fires
# (default 10s OR 500 records) or when compact() is called explicitly.


def test_record_does_not_rewrite_state_json_per_record(tmp_path: Path):
    # Both thresholds set very high — no auto-compaction in this test.
    store = SweepStore(
        tmp_path,
        compact_interval_seconds=10**6,
        compact_interval_records=10**6,
    )
    # __init__ wrote a fresh empty snapshot.
    assert json.loads((tmp_path / "sweep.state.json").read_text()) == {}

    store.record(_rec("ADI", 1, "ok"))
    store.record(_rec("ADI", 2, "fail"))

    # Log + in-memory state both reflect the records.
    assert len((tmp_path / "sweep.log.jsonl").read_text().splitlines()) == 2
    assert set(store.snapshot().keys()) == {"ADI_1", "ADI_2"}

    # state.json is still the init-time snapshot.
    on_disk = json.loads((tmp_path / "sweep.state.json").read_text())
    assert on_disk == {}


def test_compact_refreshes_state_json(tmp_path: Path):
    store = SweepStore(
        tmp_path,
        compact_interval_seconds=10**6,
        compact_interval_records=10**6,
    )
    store.record(_rec("ADI", 1, "ok"))
    store.record(_rec("ADI", 2, "fail"))

    store.compact()

    on_disk = json.loads((tmp_path / "sweep.state.json").read_text())
    assert set(on_disk.keys()) == {"ADI_1", "ADI_2"}
    assert on_disk["ADI_1"]["status"] == "ok"
    assert on_disk["ADI_2"]["status"] == "fail"


def test_record_threshold_triggers_compact(tmp_path: Path):
    store = SweepStore(
        tmp_path,
        compact_interval_seconds=10**6,  # never on time
        compact_interval_records=3,      # fire at the third record
    )
    store.record(_rec("ADI", 1, "ok"))
    store.record(_rec("ADI", 2, "ok"))

    # Two records — below the threshold; state.json still empty.
    assert json.loads((tmp_path / "sweep.state.json").read_text()) == {}

    store.record(_rec("ADI", 3, "ok"))  # hits threshold
    on_disk = json.loads((tmp_path / "sweep.state.json").read_text())
    assert set(on_disk.keys()) == {"ADI_1", "ADI_2", "ADI_3"}


def test_recovery_replays_log_when_state_is_stale(tmp_path: Path):
    # Simulate: a record was appended to the log but state.json was never
    # refreshed (kill before compaction threshold). Reopening must replay
    # the log rather than trust the stale snapshot.
    store = SweepStore(
        tmp_path,
        compact_interval_seconds=10**6,
        compact_interval_records=10**6,
    )
    store.record(_rec("ADI", 1, "ok"))
    # No compact(); state.json on disk is the init-time empty snapshot.
    assert json.loads((tmp_path / "sweep.state.json").read_text()) == {}
    del store

    # Reopen: log replay must pick up ADI_1.
    store2 = SweepStore(tmp_path)
    assert store2.already_ok("ADI", 1) is True
    # __init__ also wrote a fresh state.json reflecting the replayed state.
    on_disk = json.loads((tmp_path / "sweep.state.json").read_text())
    assert "ADI_1" in on_disk
