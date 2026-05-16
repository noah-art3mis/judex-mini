"""Tests for ``judex.warehouse.case_issues.build_case_issues``.

Sibling of ``test_peca_issues_builder`` — but for the case-id-keyed
``case_issues`` table, populated from ``fetch_meta`` rows in
``executar.state.json`` files.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest


def _write_state(path: Path, cases: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "started_at": "2026-05-12T20:00:00Z",
        "snapshot_at": "2026-05-12T20:00:01Z",
        "cases": cases,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def warehouse_con():
    """Empty in-memory DuckDB with just the case_issues table."""
    con = duckdb.connect(":memory:")
    con.execute("""
        CREATE TABLE case_issues (
            classe              VARCHAR NOT NULL,
            processo_id         INTEGER NOT NULL,
            latest_meta_status  VARCHAR,
            latest_error        VARCHAR,
            n_attempts_seen     INTEGER NOT NULL,
            first_seen_at       VARCHAR,
            last_seen_at        VARCHAR,
            last_run_dir        VARCHAR,
            PRIMARY KEY (classe, processo_id)
        )
    """)
    return con


def test_build_case_issues_empty_runs_root(tmp_path: Path, warehouse_con) -> None:
    """No state.json files → 0 rows, no error."""
    from judex.warehouse.case_issues import build_case_issues
    n = build_case_issues(warehouse_con, runs_root=tmp_path / "runs")
    assert n == 0


def test_build_case_issues_captures_fetch_meta_http_error(
    tmp_path: Path, warehouse_con,
) -> None:
    """A case whose fetch_meta failed with http_error must land in
    case_issues with the latest error message preserved."""
    from judex.warehouse.case_issues import build_case_issues

    runs = tmp_path / "runs"
    _write_state(runs / "hc-storm-run" / "executar.state.json", {
        "HC-206779": {
            "fetch_meta": {
                "status": "http_error",
                "ts": "2026-05-12T13:00:00Z",
                "error": "SSLError: HTTPSConnectionPool(...) Max retries exceeded",
                "retry_count": 0,
            },
        },
    })
    n = build_case_issues(warehouse_con, runs_root=runs)
    assert n == 1

    row = warehouse_con.execute(
        "SELECT classe, processo_id, latest_meta_status, latest_error, "
        "n_attempts_seen, last_run_dir FROM case_issues"
    ).fetchone()
    assert row[0] == "HC"
    assert row[1] == 206779
    assert row[2] == "http_error"
    assert "SSLError" in (row[3] or "")
    assert row[4] == 1
    assert row[5] == "hc-storm-run"


def test_build_case_issues_excludes_ok_and_unallocated(
    tmp_path: Path, warehouse_con,
) -> None:
    """case_issues registry exists to surface problems. Cases with
    ``status='ok'`` are noise; ``unallocated_pid`` belongs in its own
    dedicated table — both must be filtered out."""
    from judex.warehouse.case_issues import build_case_issues

    runs = tmp_path / "runs"
    _write_state(runs / "mixed-run" / "executar.state.json", {
        "HC-1": {"fetch_meta": {"status": "ok", "ts": "2026-05-12T13:00Z",
                                "error": None, "retry_count": 0}},
        "HC-2": {"fetch_meta": {"status": "unallocated_pid",
                                "ts": "2026-05-12T13:01Z",
                                "error": None, "retry_count": 0}},
        "HC-3": {"fetch_meta": {"status": "http_error",
                                "ts": "2026-05-12T13:02Z",
                                "error": "503 Service Unavailable",
                                "retry_count": 1}},
    })
    n = build_case_issues(warehouse_con, runs_root=runs)
    assert n == 1
    row = warehouse_con.execute(
        "SELECT processo_id, latest_meta_status FROM case_issues"
    ).fetchone()
    assert row[0] == 3
    assert row[1] == "http_error"


def test_build_case_issues_last_write_wins_across_runs(
    tmp_path: Path, warehouse_con,
) -> None:
    """Two runs observing the same case — latest ts wins for status."""
    from judex.warehouse.case_issues import build_case_issues

    runs = tmp_path / "runs"
    _write_state(runs / "first" / "executar.state.json", {
        "HC-5": {"fetch_meta": {"status": "http_error",
                                "ts": "2026-05-10T10:00:00Z",
                                "error": "WAF 403", "retry_count": 0}},
    })
    _write_state(runs / "second" / "executar.state.json", {
        "HC-5": {"fetch_meta": {"status": "provider_error",
                                "ts": "2026-05-12T15:00:00Z",
                                "error": "json decode", "retry_count": 1}},
    })
    n = build_case_issues(warehouse_con, runs_root=runs)
    assert n == 1
    row = warehouse_con.execute(
        "SELECT latest_meta_status, latest_error, n_attempts_seen, "
        "first_seen_at, last_seen_at, last_run_dir FROM case_issues"
    ).fetchone()
    assert row[0] == "provider_error"  # later ts wins
    assert row[1] == "json decode"
    assert row[2] == 2                   # both observations counted
    assert row[3] == "2026-05-10T10:00:00Z"
    assert row[4] == "2026-05-12T15:00:00Z"
    assert row[5] == "second"
