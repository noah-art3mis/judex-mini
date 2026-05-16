"""End-to-end behavioural test: rows that ``recuperar`` plans to retry
must survive the dispatcher → child-runner round-trip without being
silently filtered out.

The bug this catches: before 2026-05-15, ``recuperar`` and the child
runner's seed-builder used two different classifiers that disagreed on
``(fetch_bytes, empty)``. Recuperar dispatched the row; the child's
``seeds_from_targets`` rejected it; the child exited in <5 s with zero
work; the residual never shrank. The unit test layer pinned each side
in isolation but never composed them, so the disagreement only
surfaced in production.

This test composes the two halves so the next instance of the same
shape — a wire-schema rename, a JSON field reorganisation, a new
status word — fails at unit-test time rather than at sweep time.

Shape:
    state.json with non-ok rows
        → recuperar.classify_residual            (planner classifier)
        → recuperar.plan_recoveries              (dispatcher → wire)
        → executar.errors.jsonl on disk          (materialised content)
        → runner.targets_from_errors_jsonl       (child target builder)
        → scheduler.seeds_from_targets           (child seed-builder)
        → assert the originally-classified URLs appear in the seed list
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from judex.pipeline.runner import targets_from_errors_jsonl
from judex.pipeline.scheduler import seeds_from_targets
from judex.pipeline.state import PipelineState
from judex.sweeps.recuperar import (
    Bucket,
    classify_residual,
    discover_run_dirs,
    execute_recoveries,
    plan_recoveries,
)


STATE_FILENAME = "executar.state.json"


def _write_state(path: Path, cases: dict[str, dict]) -> None:
    """Schema-valid state.json fixture. Mirrors ``test_recuperar.py``'s
    helper — kept local to avoid coupling two test files via a shared
    helper module."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "started_at": "2026-05-15T00:00:00Z",
        "snapshot_at": "2026-05-15T00:00:01Z",
        "cases": cases,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _meta(status: str, retry_count: int = 0) -> dict:
    return {"status": status, "ts": "x", "error": None, "retry_count": retry_count}


def _bytes_entry(status: str, retry_count: int = 0, doc_type: str = "DESPACHO") -> dict:
    return {"status": status, "ts": "x", "error": None,
            "doc_type": doc_type, "retry_count": retry_count}


def _text_entry(status: str, retry_count: int = 0) -> dict:
    return {"status": status, "ts": "x", "error": None,
            "extractor": "pypdf", "retry_count": retry_count}


def _roundtrip(
    run_dir: Path,
    *,
    apply_to_disk: bool = True,
) -> tuple[list[tuple[str, int]], list]:
    """Run the dispatcher → wire → child round-trip and return the
    targets the child would see + the seeds it would build.

    ``apply_to_disk=True`` writes the materialised errors file via
    :func:`execute_recoveries` (skipping the subprocess spawn since
    we want to inspect the wire content, not actually run a child).
    """
    dirs = discover_run_dirs(run_dir)
    buckets = classify_residual(dirs)
    plan = plan_recoveries(buckets, provedor="auto")

    # Materialise the wire content the dispatcher would write, without
    # spawning subprocesses. Mimicking ``execute_recoveries``'s write
    # step keeps the test honest about the wire bytes.
    for spawn in plan:
        if spawn.materialized_content is not None and apply_to_disk:
            spawn.source_errors_file.parent.mkdir(parents=True, exist_ok=True)
            spawn.source_errors_file.write_text(
                spawn.materialized_content, encoding="utf-8"
            )

    # Now act as the child: read the errors file the dispatcher just
    # wrote, derive targets, then build seeds against the same state.
    targets: list[tuple[str, int]] = []
    state = PipelineState.load(run_dir / STATE_FILENAME)
    for spawn in plan:
        if spawn.source_errors_file.name.endswith(".errors.jsonl"):
            targets.extend(targets_from_errors_jsonl(spawn.source_errors_file))

    seeds = seeds_from_targets(targets, state)
    return targets, seeds


def test_fetch_bytes_empty_survives_roundtrip(tmp_path: Path) -> None:
    """The historical drift cell: ``(fetch_bytes, empty)`` rows that
    recuperar classifies as REPLAY must actually be seeded by the
    child's ``seeds_from_targets``. Pre-2026-05-15 this assertion
    failed — the dispatcher created the file but the seed-builder's
    ``_is_retryable_status`` rejected ``empty`` for kind=fetch_bytes.
    """
    _write_state(
        tmp_path / STATE_FILENAME,
        {
            "HC-100": {
                "fetch_meta": _meta("ok"),
                "fetch_bytes": {
                    "https://stf/peca-100.pdf": _bytes_entry("empty"),
                },
            },
        },
    )

    dirs = discover_run_dirs(tmp_path)
    buckets = classify_residual(dirs)
    assert len(buckets[Bucket.REPLAY]) == 1, (
        "Recuperar's classifier should put (fetch_bytes, empty) in REPLAY."
    )

    targets, seeds = _roundtrip(tmp_path)

    assert ("HC", 100) in targets, (
        "The child's target builder dropped the case-key recuperar "
        "wanted retried."
    )
    fetch_bytes_seeded_urls = {
        s.payload.get("url") for s in seeds if s.kind == "fetch_bytes"
    }
    assert "https://stf/peca-100.pdf" in fetch_bytes_seeded_urls, (
        "The child's seed-builder filtered out the URL recuperar "
        "dispatched. This is the exact silent-no-op shape the "
        "recovery_policy extraction was meant to prevent."
    )


def test_http_error_survives_roundtrip(tmp_path: Path) -> None:
    """Symmetric sanity: ``(fetch_bytes, http_error)`` was already
    aligned across both classifiers; round-trip should work. Lets the
    test suite catch regressions where the *opposite* direction of
    drift opens up (e.g. someone narrows the recuperar classifier).
    """
    _write_state(
        tmp_path / STATE_FILENAME,
        {
            "HC-200": {
                "fetch_meta": _meta("ok"),
                "fetch_bytes": {
                    "https://stf/peca-200.pdf": _bytes_entry("http_error"),
                },
            },
        },
    )
    targets, seeds = _roundtrip(tmp_path)
    assert ("HC", 200) in targets
    assert any(
        s.kind == "fetch_bytes"
        and s.payload.get("url") == "https://stf/peca-200.pdf"
        for s in seeds
    )


def test_fetch_meta_http_error_survives_roundtrip(tmp_path: Path) -> None:
    """Meta-stage retry: a case whose ``fetch_meta`` failed with
    ``http_error`` should round-trip as a fetch_meta seed (not a
    fetch_bytes seed — there are no bytes URLs to retry yet)."""
    _write_state(
        tmp_path / STATE_FILENAME,
        {
            "HC-300": {"fetch_meta": _meta("http_error")},
        },
    )
    targets, seeds = _roundtrip(tmp_path)
    assert ("HC", 300) in targets
    assert any(
        s.kind == "fetch_meta" and s.case_key == ("HC", 300)
        for s in seeds
    )


def test_cap_burnt_does_not_round_trip(tmp_path: Path) -> None:
    """Conversely: a transient row at ``retry_count >= RETRY_CAP`` is
    in the CAP_BURNT bucket and is NOT dispatched. If the child's seed
    builder happened to look at the same state (without going through
    ``--retentar-de``), the cap gate would also drop it — so the round
    trip should produce neither a target nor a seed. Pinning the empty
    case prevents a future loosening that would re-include cap-burnt
    URLs in dispatched errors files without resetting their counter.
    """
    from judex.pipeline.recovery_policy import RETRY_CAP

    _write_state(
        tmp_path / STATE_FILENAME,
        {
            "HC-400": {
                "fetch_meta": _meta("ok"),
                "fetch_bytes": {
                    "https://stf/peca-400.pdf": _bytes_entry(
                        "http_error", retry_count=RETRY_CAP,
                    ),
                },
            },
        },
    )
    dirs = discover_run_dirs(tmp_path)
    buckets = classify_residual(dirs)
    assert len(buckets[Bucket.REPLAY]) == 0
    assert len(buckets[Bucket.CAP_BURNT]) == 1
    targets, seeds = _roundtrip(tmp_path)
    assert ("HC", 400) not in targets
    assert all(s.case_key != ("HC", 400) for s in seeds)


def test_unallocated_pid_does_not_round_trip(tmp_path: Path) -> None:
    """Terminal: ``unallocated_pid`` is CONFIRMED_UNALLOCATED, never
    REPLAY. The dispatcher must not write it to the errors file, and
    the child's seed-builder must not seed it even if it somehow did.
    """
    _write_state(
        tmp_path / STATE_FILENAME,
        {
            "HC-500": {"fetch_meta": _meta("unallocated_pid")},
        },
    )
    dirs = discover_run_dirs(tmp_path)
    buckets = classify_residual(dirs)
    assert len(buckets[Bucket.CONFIRMED_UNALLOCATED]) == 1
    assert len(buckets[Bucket.REPLAY]) == 0
    targets, seeds = _roundtrip(tmp_path)
    assert ("HC", 500) not in targets
    assert all(s.case_key != ("HC", 500) for s in seeds)


def test_mixed_residual_partial_roundtrip(tmp_path: Path) -> None:
    """A realistic state with a mix of buckets: REPLAY rows round-trip
    end-to-end, terminal rows don't, cap-burnt rows don't, cross-stage
    rows round-trip via a different dispatch path (REFETCH_UPSTREAM →
    --csv, not --retentar-de — so they won't appear in the
    errors.jsonl path but will appear via the csv path)."""
    from judex.pipeline.recovery_policy import RETRY_CAP

    _write_state(
        tmp_path / STATE_FILENAME,
        {
            "HC-1": {
                "fetch_meta": _meta("ok"),
                "fetch_bytes": {"u1": _bytes_entry("empty")},  # REPLAY
            },
            "HC-2": {
                "fetch_meta": _meta("ok"),
                "fetch_bytes": {
                    "u2": _bytes_entry("http_error", retry_count=RETRY_CAP),
                },  # CAP_BURNT
            },
            "HC-3": {"fetch_meta": _meta("unallocated_pid")},  # CONFIRMED
            "HC-4": {
                "fetch_meta": _meta("ok"),
                "fetch_bytes": {"u4": _bytes_entry("ok")},
                "extract_text": {"u4": _text_entry("provider_error")},  # REPLAY
            },
        },
    )
    targets, seeds = _roundtrip(tmp_path)

    # REPLAY rows present as targets
    assert ("HC", 1) in targets
    assert ("HC", 4) in targets

    # Non-REPLAY rows absent from --retentar-de targets
    assert ("HC", 2) not in targets
    assert ("HC", 3) not in targets

    # Seed shapes match
    fetch_bytes_urls = {
        s.payload.get("url") for s in seeds if s.kind == "fetch_bytes"
    }
    extract_text_urls = {
        s.payload.get("url") for s in seeds if s.kind == "extract_text"
    }
    assert "u1" in fetch_bytes_urls
    assert "u4" in extract_text_urls


def test_execute_recoveries_writes_materialized_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Companion sanity: ``execute_recoveries`` actually writes the
    ``materialized_content`` to disk before spawning. The round-trip
    tests above bypass the spawn; this one verifies the on-disk wire
    contract is honoured by the production code path too.
    """
    _write_state(
        tmp_path / STATE_FILENAME,
        {
            "HC-1": {
                "fetch_meta": _meta("ok"),
                "fetch_bytes": {"u1": _bytes_entry("empty")},
            },
        },
    )
    dirs = discover_run_dirs(tmp_path)
    buckets = classify_residual(dirs)
    plan = plan_recoveries(buckets, provedor="auto")
    assert len(plan) == 1

    # Stub out Popen so we don't actually launch a child.
    class _FakeProc:
        def __init__(self, pid: int = 99999) -> None:
            self.pid = pid

    def _fake_popen(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return _FakeProc()

    monkeypatch.setattr(
        "judex.sweeps.recuperar.subprocess.Popen", _fake_popen,
    )

    pids_path = tmp_path / "recuperar.pids"
    result = execute_recoveries(plan, pids_path)

    # The errors.jsonl now exists on disk and has the row we expect.
    errors_file = plan[0].source_errors_file
    assert errors_file.exists()
    rows = [json.loads(ln) for ln in errors_file.read_text().splitlines() if ln]
    assert len(rows) == 1
    assert rows[0]["kind"] == "fetch_bytes"
    assert rows[0]["status"] == "empty"
    assert rows[0]["classe"] == "HC"
    assert rows[0]["processo"] == 1
    assert result.pids == [99999]
