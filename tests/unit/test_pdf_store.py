"""Atomic per-URL state + append-only log for PDF fetch runs.

Mirrors the contracts from tests/unit/test_sweep_state.py, but keyed
by URL (one row per PDF URL) instead of (classe, processo).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.pdf_store import (
    PdfAttemptRecord,
    PdfStore,
    load_retry_list,
    recover_state_from_log,
)


def _rec(
    url: str,
    status: str = "ok",
    attempt: int = 1,
    **kwargs,
) -> PdfAttemptRecord:
    defaults = dict(
        ts="2026-04-17T12:00:00",
        url=url,
        attempt=attempt,
        wall_s=0.5,
        status=status,
    )
    defaults.update(kwargs)
    return PdfAttemptRecord(**defaults)


def test_store_is_empty_initially(tmp_path: Path) -> None:
    store = PdfStore(tmp_path)
    assert store.snapshot() == {}
    assert store.already_ok("https://x.test/a.pdf") is False
    assert store.attempt_count("https://x.test/a.pdf") == 0


def test_record_writes_log_and_state(tmp_path: Path) -> None:
    store = PdfStore(tmp_path)
    store.record(_rec("https://x.test/a.pdf", status="ok", chars=1000))
    assert store.already_ok("https://x.test/a.pdf") is True
    assert store.attempt_count("https://x.test/a.pdf") == 1
    assert (tmp_path / "pdfs.log.jsonl").exists()
    assert (tmp_path / "pdfs.state.json").exists()


def test_log_is_append_only(tmp_path: Path) -> None:
    store = PdfStore(tmp_path)
    store.record(_rec("https://x.test/a.pdf", status="http_error", attempt=1))
    store.record(_rec("https://x.test/a.pdf", status="ok", attempt=2))
    lines = (tmp_path / "pdfs.log.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["status"] == "http_error"
    assert json.loads(lines[1])["status"] == "ok"


def test_state_reflects_latest_attempt(tmp_path: Path) -> None:
    store = PdfStore(tmp_path)
    store.record(_rec("https://x.test/a.pdf", status="http_error", attempt=1))
    store.record(_rec("https://x.test/a.pdf", status="ok", attempt=2))
    snap = store.snapshot()
    assert snap["https://x.test/a.pdf"]["status"] == "ok"
    assert snap["https://x.test/a.pdf"]["attempt"] == 2


def test_errors_excludes_ok(tmp_path: Path) -> None:
    store = PdfStore(tmp_path)
    store.record(_rec("https://x.test/a.pdf", status="ok"))
    store.record(_rec("https://x.test/b.pdf", status="empty"))
    store.record(_rec("https://x.test/c.pdf", status="http_error"))
    err_urls = {r["url"] for r in store.errors()}
    assert err_urls == {"https://x.test/b.pdf", "https://x.test/c.pdf"}


def test_recover_state_from_log(tmp_path: Path) -> None:
    log = tmp_path / "pdfs.log.jsonl"
    log.write_text(
        json.dumps(
            {"ts": "t", "url": "https://x.test/a.pdf", "attempt": 1,
             "wall_s": 0.1, "status": "http_error"}) + "\n"
        + json.dumps(
            {"ts": "t", "url": "https://x.test/a.pdf", "attempt": 2,
             "wall_s": 0.1, "status": "ok"}) + "\n"
    )
    state = recover_state_from_log(log)
    assert state["https://x.test/a.pdf"]["status"] == "ok"


def test_store_recovers_state_when_state_file_missing(tmp_path: Path) -> None:
    # Simulate torn write: log exists, state.json does not.
    log = tmp_path / "pdfs.log.jsonl"
    log.write_text(
        json.dumps(
            {"ts": "t", "url": "https://x.test/a.pdf", "attempt": 1,
             "wall_s": 0.1, "status": "ok"}) + "\n"
    )
    assert not (tmp_path / "pdfs.state.json").exists()

    store = PdfStore(tmp_path)
    assert store.already_ok("https://x.test/a.pdf")
    # Opening also rehydrated the state file.
    assert (tmp_path / "pdfs.state.json").exists()


def test_write_errors_file(tmp_path: Path) -> None:
    store = PdfStore(tmp_path)
    store.record(_rec("https://x.test/a.pdf", status="ok"))
    store.record(_rec("https://x.test/b.pdf", status="empty"))
    path = store.write_errors_file()
    assert path == tmp_path / "pdfs.errors.jsonl"
    urls = [json.loads(l)["url"] for l in path.read_text().splitlines()]
    assert urls == ["https://x.test/b.pdf"]


def test_load_retry_list(tmp_path: Path) -> None:
    errs = tmp_path / "pdfs.errors.jsonl"
    errs.write_text(
        json.dumps({"url": "https://x.test/a.pdf", "status": "empty"}) + "\n"
        + json.dumps({"url": "https://x.test/b.pdf", "status": "http_error"}) + "\n"
    )
    assert load_retry_list(errs) == [
        "https://x.test/a.pdf", "https://x.test/b.pdf",
    ]
