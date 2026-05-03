"""Contracts for ``judex.pipeline.state.PipelineState``.

These tests pin restart semantics. They are not ceremonial — each one
catches a specific bug class that would silently corrupt a
fire-and-forget run:

* ``test_round_trip``: state survives process restart with no diff.
* ``test_resume_skips_ok``: resume re-enqueues only non-ok work, so a
  24-hour run that crashes at hour 23 doesn't re-do hour 1's work.
* ``test_atomic_snapshot``: a partial-write crash leaves either the
  old file intact or the new file complete; never a half-written
  corruption that the next ``--retomar`` reads as authoritative.
* ``test_record_overwrites``: re-recording a task replaces (not
  appends) so retry semantics work after transient failures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from judex.pipeline import PipelineState


def test_load_missing_file_returns_empty_state(tmp_path: Path) -> None:
    state = PipelineState.load(tmp_path / "executar.state.json")
    assert state.case_count() == 0


def test_record_and_query_fetch_meta(tmp_path: Path) -> None:
    state = PipelineState.load(tmp_path / "s.json")
    state.record_meta(("HC", 1), status="ok")
    assert state.meta_status(("HC", 1)) == "ok"
    assert state.case_count() == 1


def test_record_and_query_fetch_bytes(tmp_path: Path) -> None:
    state = PipelineState.load(tmp_path / "s.json")
    state.record_bytes(("HC", 1), url="https://stf/peca-1", status="ok")
    assert state.bytes_status(("HC", 1), url="https://stf/peca-1") == "ok"


def test_record_and_query_extract_text(tmp_path: Path) -> None:
    state = PipelineState.load(tmp_path / "s.json")
    state.record_text(("HC", 1), url="https://stf/peca-1", status="ok", extractor="pypdf")
    assert state.text_status(("HC", 1), url="https://stf/peca-1") == "ok"
    assert state.text_extractor(("HC", 1), url="https://stf/peca-1") == "pypdf"


def test_record_text_stores_chars(tmp_path: Path) -> None:
    """``chars`` lets the per-task tail line surface OCR output size
    (``pypdf · 18,234ch``) without re-reading the cached text from disk.
    Optional: only the ok / empty paths fill it in; failures leave None."""
    state = PipelineState.load(tmp_path / "s.json")

    state.record_text(
        ("HC", 1), url="u-ok", status="ok", extractor="pypdf", chars=18234,
    )
    state.record_text(
        ("HC", 1), url="u-empty", status="empty", extractor="pypdf", chars=0,
    )
    state.record_text(
        ("HC", 1), url="u-fail", status="provider_error", extractor="pypdf",
    )

    assert state.text_chars(("HC", 1), url="u-ok") == 18234
    assert state.text_chars(("HC", 1), url="u-empty") == 0
    assert state.text_chars(("HC", 1), url="u-fail") is None
    assert state.text_chars(("HC", 1), url="u-missing") is None


def test_aggregate_status_counts_walks_in_memory_state(tmp_path: Path) -> None:
    """The mono ``_periodic_progress`` reads the in-memory state
    directly to render the multi-stage progress line. Counter shape
    must match the sharded aggregator (which walks cold state files)
    so both topologies feed the same shared renderer."""
    state = PipelineState.load(tmp_path / "s.json")

    state.record_meta(("HC", 1), status="ok")
    state.record_meta(("HC", 2), status="unallocated_pid")
    state.record_bytes(("HC", 1), url="u1", status="ok")
    state.record_bytes(("HC", 1), url="u2", status="empty")
    state.record_text(("HC", 1), url="u1", status="ok", extractor="pypdf", chars=200)
    state.record_text(
        ("HC", 1), url="u2", status="provider_error", extractor="pypdf",
    )

    agg = state.aggregate_status_counts()

    assert dict(agg["processos"]) == {"ok": 1, "unallocated_pid": 1}
    assert dict(agg["pecas"]) == {"ok": 1, "empty": 1}
    assert dict(agg["text"]) == {"ok": 1, "provider_error": 1}


def test_aggregate_status_counts_returns_pecas_total_when_all_records_have_n_pecas(
    tmp_path: Path,
) -> None:
    """``pecas_total`` answers the operator's question 'how many peca
    fetches are we expected to do?' — the denominator the aggregate
    progress line needs to render a meaningful percentage post-meta-
    completion. Sums ``n_pecas`` across all meta=ok records (only ok
    cases emit pecas successors)."""
    state = PipelineState.load(tmp_path / "s.json")

    state.record_meta(("HC", 1), status="ok", n_pecas=3)
    state.record_meta(("HC", 2), status="ok", n_pecas=5)
    # unallocated_pid records emit zero successors; their n_pecas is
    # naturally None / irrelevant, must NOT poison the total.
    state.record_meta(("HC", 3), status="unallocated_pid")

    agg = state.aggregate_status_counts()

    assert agg["pecas_total"] == 8


def test_aggregate_status_counts_returns_none_pecas_total_for_legacy_state(
    tmp_path: Path,
) -> None:
    """Legacy state files (written before n_pecas existed) have
    meta=ok records without the field. The aggregator returns None
    rather than an undercount — the renderer then drops the pecas
    ratio rather than show a wrong number. Surfaces only on resume
    of an in-progress run that started under old code."""
    state = PipelineState.load(tmp_path / "s.json")

    state.record_meta(("HC", 1), status="ok", n_pecas=3)
    # Simulate a legacy record by hand-writing into _cases without
    # n_pecas.
    state._ensure_case(("HC", 2)).meta = {
        "status": "ok", "ts": "2026-05-03T00:00:00Z",
        "error": None, "retry_count": 0,
        # n_pecas missing
    }

    agg = state.aggregate_status_counts()

    assert agg["pecas_total"] is None


def test_aggregate_status_counts_text_total_equals_pecas_ok(tmp_path: Path) -> None:
    """text_total = pecas["ok"] at any moment, since every successful
    pecas download emits exactly one extract_text successor. Checked
    explicitly here so the renderer can rely on the invariant."""
    state = PipelineState.load(tmp_path / "s.json")

    state.record_meta(("HC", 1), status="ok", n_pecas=3)
    state.record_bytes(("HC", 1), url="u1", status="ok")
    state.record_bytes(("HC", 1), url="u2", status="ok")
    state.record_bytes(("HC", 1), url="u3", status="empty")
    # Two text tasks have run so far; one is still queued.
    state.record_text(("HC", 1), url="u1", status="ok", extractor="pypdf", chars=500)

    agg = state.aggregate_status_counts()

    assert agg["text_total"] == 2  # pecas["ok"]
    assert sum(agg["text"].values()) == 1  # one text outcome recorded


def test_round_trip(tmp_path: Path) -> None:
    """Snapshot, reload, observe identical contents."""
    path = tmp_path / "s.json"
    state = PipelineState.load(path)
    state.record_meta(("HC", 1), status="ok")
    state.record_bytes(("HC", 1), url="u1", status="ok")
    state.record_text(("HC", 1), url="u1", status="ok", extractor="pypdf")
    state.record_meta(("HC", 2), status="unallocated_pid")
    state.snapshot()

    reloaded = PipelineState.load(path)
    assert reloaded.meta_status(("HC", 1)) == "ok"
    assert reloaded.bytes_status(("HC", 1), url="u1") == "ok"
    assert reloaded.text_status(("HC", 1), url="u1") == "ok"
    assert reloaded.text_extractor(("HC", 1), url="u1") == "pypdf"
    assert reloaded.meta_status(("HC", 2)) == "unallocated_pid"


def test_record_overwrites_prior_status(tmp_path: Path) -> None:
    """A retry should replace the old status, not append a history."""
    state = PipelineState.load(tmp_path / "s.json")
    state.record_bytes(("HC", 1), url="u1", status="http_error", error="WAF 403")
    state.record_bytes(("HC", 1), url="u1", status="ok")
    assert state.bytes_status(("HC", 1), url="u1") == "ok"


def test_resume_skips_ok_meta(tmp_path: Path) -> None:
    state = PipelineState.load(tmp_path / "s.json")
    state.record_meta(("HC", 1), status="ok")
    state.record_meta(("HC", 2), status="http_error", error="WAF 403")
    assert state.is_meta_complete(("HC", 1)) is True
    assert state.is_meta_complete(("HC", 2)) is False


def test_resume_skips_ok_bytes_per_url(tmp_path: Path) -> None:
    state = PipelineState.load(tmp_path / "s.json")
    state.record_bytes(("HC", 1), url="u-ok", status="ok")
    state.record_bytes(("HC", 1), url="u-fail", status="http_error")
    assert state.is_bytes_complete(("HC", 1), url="u-ok") is True
    assert state.is_bytes_complete(("HC", 1), url="u-fail") is False


def test_resume_text_only_complete_when_extractor_matches(tmp_path: Path) -> None:
    """Switching providers (pypdf -> chandra) means the text needs
    re-extracting even if the prior status was ``ok``. ``--forcar``
    is the operator-side knob; here we just expose the truth.
    """
    state = PipelineState.load(tmp_path / "s.json")
    state.record_text(("HC", 1), url="u1", status="ok", extractor="pypdf")
    assert state.is_text_complete(("HC", 1), url="u1", required_extractor="pypdf") is True
    assert state.is_text_complete(("HC", 1), url="u1", required_extractor="chandra") is False


def test_atomic_snapshot_no_partial_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a crash between tempfile-write and rename. The on-disk
    file must be either the prior good copy or absent — never a
    half-written JSON that ``json.loads`` chokes on.
    """
    path = tmp_path / "s.json"
    state = PipelineState.load(path)
    state.record_meta(("HC", 1), status="ok")
    state.snapshot()

    # Capture the good copy.
    good = path.read_bytes()

    # Now mutate and force a crash mid-snapshot, after the tempfile is
    # written but before os.replace runs.
    state.record_meta(("HC", 2), status="ok")

    import os
    real_replace = os.replace

    def crash_replace(*args, **kwargs):  # noqa: ANN001
        raise RuntimeError("simulated crash mid-rename")

    monkeypatch.setattr(os, "replace", crash_replace)
    with pytest.raises(RuntimeError, match="simulated crash"):
        state.snapshot()
    monkeypatch.setattr(os, "replace", real_replace)

    # On-disk file is still the prior good copy. No partial JSON.
    assert path.read_bytes() == good
    # And it's still parseable.
    json.loads(path.read_text())


def test_snapshot_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deep" / "s.json"
    state = PipelineState.load(path)
    state.record_meta(("HC", 1), status="ok")
    state.snapshot()
    assert path.exists()


def test_known_urls_for_case_round_trip(tmp_path: Path) -> None:
    """``known_bytes_urls`` returns the URL set the state has seen for
    a case. Used by the scheduler to skip URLs that already finished.
    """
    state = PipelineState.load(tmp_path / "s.json")
    state.record_bytes(("HC", 1), url="u1", status="ok")
    state.record_bytes(("HC", 1), url="u2", status="http_error")
    state.record_bytes(("HC", 2), url="u3", status="ok")

    assert state.known_bytes_urls(("HC", 1)) == {"u1", "u2"}
    assert state.known_bytes_urls(("HC", 2)) == {"u3"}
    assert state.known_bytes_urls(("HC", 999)) == set()
