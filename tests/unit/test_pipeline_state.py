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
    state = PipelineState.open(saida=tmp_path)
    state.record_meta(("HC", 1), status="ok")
    state.snapshot()
    path = tmp_path / "executar.state.json"

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
    saida = tmp_path / "nested" / "deep"
    state = PipelineState.open(saida=saida)
    state.record_meta(("HC", 1), status="ok")
    state.snapshot()
    assert (saida / "executar.state.json").exists()


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


# ---------------------------------------------------------------------------
# ADR-0006 — Journal-mode contracts (snapshot + log reconciliation).
#
# These pin the four invariants the journal Module is built to enforce:
#
# 1. ``test_open_recovers_post_snapshot_log_rows``: the headline
#    SIGKILL-correctness fix — work that was logged but not snapshotted
#    survives a hard kill. The pre-ADR-0006 contract lost up to one
#    snapshot interval (5 s) of work because ``load`` only read the
#    snapshot. ``open`` reads snapshot **and** replays log rows whose
#    ``ts > snapshot_at``.
# 2. ``test_open_replay_is_idempotent``: replay deserialises log rows
#    directly into ``CaseRecord`` slots (the E1 bypass-mutators
#    decision), so ``retry_count`` reflects history rather than being
#    re-incremented by the auto-increment in ``record_*``. Without
#    this, replaying a log with two attempts would yield retry_count=4
#    on reload, spuriously firing the cap=2 gate.
# 3. ``test_open_quarantines_stale_log``: the run-id staleness defence
#    (D7). A log from a prior aborted run, co-resident with a fresh
#    snapshot, must not be silently replayed onto unrelated state.
# 4. ``test_retry_count_survives_log_replay_without_double_counting``:
#    the cross-boundary semantics for the cap=2 retry gate inherited
#    from ADR-0005. retry_count from log replay matches what the live
#    handlers wrote; resuming and re-running doesn't multiply it.
# ---------------------------------------------------------------------------


def _append_log_row(saida: Path, row: dict) -> None:
    """Append one JSON-line to ``saida/executar.log.jsonl``.

    Used by tests that simulate "scheduler wrote a log row that the
    snapshot didn't capture" without going through the live scheduler.
    The journal's load path doesn't care who wrote the row — it
    re-applies anything past ``snapshot_at`` whose ``run_id`` matches.
    """
    import json as _json

    log_path = saida / "executar.log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(_json.dumps(row, ensure_ascii=False) + "\n")


def test_open_recovers_post_snapshot_log_rows(tmp_path: Path) -> None:
    """SIGKILL between snapshots: log replay restores in-flight work.

    Sequence: record HC-1, snapshot (HC-1 is durable in snapshot).
    Then a log row for HC-2 arrives without a follow-up snapshot —
    simulating a SIGKILL after the row fsynced but before the next
    5 s snapshot. ``open`` must reconstruct both cases from the
    snapshot + log together.
    """
    state = PipelineState.open(saida=tmp_path)
    state.record_meta(("HC", 1), status="ok")
    state.snapshot()
    snapshot_at = state.snapshot_at  # ts of the snapshot just written
    run_id = state.run_id

    # Append a log row strictly after snapshot_at — represents a
    # handler that completed and fsynced its row before SIGKILL.
    _append_log_row(
        tmp_path,
        {
            "ts": "2099-01-01T00:00:00+00:00",  # well past snapshot_at
            "run_id": run_id,
            "kind": "fetch_meta",
            "classe": "HC",
            "processo": 2,
            "status": "ok",
            "error": None,
            "retry_count": 0,
        },
    )

    # Drop in-memory state, reload from disk.
    state.close()
    reloaded = PipelineState.open(saida=tmp_path)
    assert reloaded.meta_status(("HC", 1)) == "ok", "snapshot path lost HC-1"
    assert reloaded.meta_status(("HC", 2)) == "ok", "log replay didn't restore HC-2"
    # snapshot_at survives so a subsequent snapshot still anchors replay correctly.
    assert reloaded.run_id == run_id


def test_open_replay_is_idempotent(tmp_path: Path) -> None:
    """Replay of an existing log row must not double-increment retry_count.

    The pre-ADR-0006 ``recover_state_from_log`` called the live
    ``record_*`` mutators on every log row, which auto-incremented
    retry_count — so replaying a log of 2 attempts would yield
    retry_count=4 instead of 1. The journal's E1 decision bypasses
    the mutators and applies log rows directly.
    """
    state = PipelineState.open(saida=tmp_path)
    state.record_meta(("HC", 1), status="http_error")  # attempt 1: retry=0
    state.record_meta(("HC", 1), status="http_error")  # attempt 2: retry=1
    assert state.meta_retry_count(("HC", 1)) == 1
    run_id = state.run_id
    # Snapshot anchors the run_id on disk so the second open() inherits
    # it (and the injected rows below pass the staleness check).
    state.snapshot()
    state.close()

    # Inject log rows representing the live mutator's writes for a
    # *different* case (HC-2) — the test is whether replay applies
    # them with retry_count=1 (the value in the row), not retry_count=2
    # (replay would compute that if it called the mutators per-row).
    # Using HC-2 instead of HC-1 sidesteps the snapshot's HC-1 record.
    for retry in (0, 1):
        _append_log_row(
            tmp_path,
            {
                "ts": f"2099-01-0{retry + 1}T00:00:00+00:00",
                "run_id": run_id,
                "kind": "fetch_meta",
                "classe": "HC",
                "processo": 2,  # fresh case to avoid colliding with the in-memory record
                "status": "http_error",
                "error": "WAF 403",
                "retry_count": retry,
            },
        )

    reloaded = PipelineState.open(saida=tmp_path)
    # Both records replayed; retry_count is what the live mutator
    # computed (1 for the second attempt), not 3 (replay-incremented).
    assert reloaded.meta_retry_count(("HC", 2)) == 1


def test_open_quarantines_stale_log(tmp_path: Path) -> None:
    """A log row whose run_id doesn't match the snapshot raises StaleLogError.

    Failure mode: an aborted prior run wrote ``executar.state.json`` and
    ``executar.log.jsonl``; a fresh ``open()`` allocates a new run_id
    and writes a new snapshot, but the prior log lingers on disk. The
    prior run's rows must not be silently replayed onto the new run's
    state — they belong to a different scrape.
    """
    from judex.pipeline.state import StaleLogError

    state = PipelineState.open(saida=tmp_path)
    state.record_meta(("HC", 1), status="ok")
    state.snapshot()
    legitimate_run_id = state.run_id

    # Inject a row from a different run (simulated as a row left behind
    # from a prior aborted run that shared the same saida directory).
    _append_log_row(
        tmp_path,
        {
            "ts": "2099-01-01T00:00:00+00:00",
            "run_id": "stale-run-id-from-aborted-prior-run",
            "kind": "fetch_meta",
            "classe": "HC",
            "processo": 999,
            "status": "ok",
            "error": None,
            "retry_count": 0,
        },
    )
    state.close()

    with pytest.raises(StaleLogError, match="run_id"):
        PipelineState.open(saida=tmp_path)
    assert legitimate_run_id  # quench unused-var warnings; pinned for test clarity


def test_retry_count_survives_log_replay_without_double_counting(
    tmp_path: Path,
) -> None:
    """Cap=2 gate (ADR-0005) holds across the load boundary.

    Scenario: handler attempts a task twice, both fail, retry_count
    reaches 1. The log carries both rows. After ``open()`` replays the
    log, the in-memory retry_count is 1 — *not* 2 (one per replayed
    row, the buggy mutator-replay path) and *not* 3 (one per row plus
    one for the in-memory state being non-None on second apply).

    A subsequent live ``record_meta`` increments to 2 = RETRY_CAP, at
    which point the scheduler's seed builder should stop re-seeding
    this task.
    """
    state = PipelineState.open(saida=tmp_path)
    run_id = state.run_id
    # Snapshot anchors run_id (and snapshot_at = before injected rows'
    # ts) so the reload below replays the injected rows.
    state.snapshot()
    state.close()

    # Inject two log rows representing two prior attempts.
    for retry in (0, 1):
        _append_log_row(
            tmp_path,
            {
                "ts": f"2099-01-0{retry + 1}T00:00:00+00:00",
                "run_id": run_id,
                "kind": "fetch_meta",
                "classe": "HC",
                "processo": 1,
                "status": "http_error",
                "error": "WAF 403",
                "retry_count": retry,
            },
        )

    reloaded = PipelineState.open(saida=tmp_path)
    assert reloaded.meta_retry_count(("HC", 1)) == 1, "replay corrupted retry_count"

    # Live mutator on top of replayed state increments by one — the
    # third attempt brings retry_count to 2 (= RETRY_CAP), which is
    # what gates re-seeding in scheduler.seeds_from_targets.
    reloaded.record_meta(("HC", 1), status="http_error")
    assert reloaded.meta_retry_count(("HC", 1)) == 2
