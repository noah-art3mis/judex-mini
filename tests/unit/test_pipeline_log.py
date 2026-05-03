"""Tests for the v1.5 unified-pipeline deepenings:

* :mod:`judex.pipeline.log` — append-only log + errors-file derivation
  + log-replay recovery.
* Range-mode and replay-mode target builders in
  :mod:`judex.pipeline.runner`.
* Sidecar-match skip in :func:`judex.pipeline.handlers.handle_extract_text`.
* analisar-regimes auto-detection of ``executar.log.jsonl``.

These tests don't touch STF — they exercise pure-data contracts so a
hard-killed run can come back via log replay, ``--retentar-de`` only
re-attempts retryable failures, and ``--forcar`` bypasses the cache
match.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from judex.pipeline.log import (
    ERRORS_NAME,
    LOG_NAME,
    PipelineLog,
    TaskLogRecord,
    classify_unified_error,
    derive_errors_file,
    make_log_record,
    read_errors_file,
    recover_state_from_log,
)
from judex.pipeline.models import Task
from judex.pipeline.runner import (
    targets_from_errors_jsonl,
    targets_from_range,
)
from judex.pipeline.state import PipelineState


# ---------------------------------------------------------------------------
# Append-only log writer + log-replay recovery
# ---------------------------------------------------------------------------


def _meta_task(case: tuple[str, int] = ("HC", 100)) -> Task:
    return Task(kind="fetch_meta", pool="portal", case_key=case, payload={})


def _bytes_task(url: str, case: tuple[str, int] = ("HC", 100)) -> Task:
    return Task(
        kind="fetch_bytes", pool="sistemas",
        case_key=case, payload={"url": url, "doc_type": "VOTO"},
    )


def _text_task(url: str, case: tuple[str, int] = ("HC", 100)) -> Task:
    return Task(
        kind="extract_text", pool="ocr",
        case_key=case, payload={"url": url, "doc_type": "VOTO"},
    )


def test_log_append_round_trip(tmp_path: Path) -> None:
    """One row written → one row readable. fsync per row means the file
    survives a forced read between writes."""
    log = PipelineLog(tmp_path / LOG_NAME)
    rec = make_log_record(
        task=_meta_task(), status="ok", wall_s=1.5,
    )
    log.append(rec)

    lines = (tmp_path / LOG_NAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["kind"] == "fetch_meta"
    assert parsed["classe"] == "HC"
    assert parsed["processo"] == 100
    assert parsed["status"] == "ok"
    assert parsed["wall_s"] == 1.5
    assert parsed["pool"] == "portal"


def test_log_carries_regime_fields(tmp_path: Path) -> None:
    """Regime stamping flows through end-to-end: the log row preserves
    every regime_* field so analisar-regimes consumes the row without
    translation."""
    log = PipelineLog(tmp_path / LOG_NAME)
    log.append(make_log_record(
        task=_bytes_task("https://stf/x.pdf"),
        status="http_error", wall_s=20.0,
        error="WAF 403",
        regime="approaching_collapse",
        regime_fail_rate=0.25,
        regime_p95_wall_s=35.0,
        regime_promoted_by="axis_a",
    ))
    parsed = json.loads((tmp_path / LOG_NAME).read_text().strip())
    assert parsed["regime"] == "approaching_collapse"
    assert parsed["regime_fail_rate"] == 0.25
    assert parsed["regime_promoted_by"] == "axis_a"


def test_recover_state_from_log_rebuilds_dag(tmp_path: Path) -> None:
    """Hard-kill simulation: log has rows that the snapshot doesn't.
    recover_state_from_log replays the log into a fresh PipelineState
    so the next run resumes from the log-true position, not the stale
    snapshot."""
    log = PipelineLog(tmp_path / LOG_NAME)
    log.append(make_log_record(task=_meta_task(("HC", 1)), status="ok", wall_s=1.0))
    log.append(make_log_record(
        task=_bytes_task("https://stf/a.pdf", ("HC", 1)),
        status="ok", wall_s=2.0,
    ))
    log.append(make_log_record(
        task=_text_task("https://stf/a.pdf", ("HC", 1)),
        status="ok", wall_s=0.3, extractor="pypdf",
    ))
    log.append(make_log_record(
        task=_meta_task(("HC", 2)),
        status="http_error", wall_s=15.0, error="WAF 403",
    ))

    state = recover_state_from_log(tmp_path / LOG_NAME)
    assert state.meta_status(("HC", 1)) == "ok"
    assert state.bytes_status(("HC", 1), url="https://stf/a.pdf") == "ok"
    assert state.text_status(("HC", 1), url="https://stf/a.pdf") == "ok"
    assert state.text_extractor(("HC", 1), url="https://stf/a.pdf") == "pypdf"
    assert state.meta_status(("HC", 2)) == "http_error"


def test_log_record_carries_chars_and_recovers_into_state(tmp_path: Path) -> None:
    """``chars`` is the per-task-line OCR-output-size signal. It must
    survive the round-trip: ``make_log_record`` accepts it,
    ``to_json`` writes it, ``recover_state_from_log`` reads it back
    into ``state.text_chars``. Without this, hard-kill resume drops
    the chars column for any extract_text row replayed from the log,
    which silently breaks the next session's tail-line UI for cached
    rows."""
    log = PipelineLog(tmp_path / LOG_NAME)
    log.append(make_log_record(
        task=_meta_task(("HC", 1)), status="ok", wall_s=1.0,
    ))
    log.append(make_log_record(
        task=_bytes_task("https://stf/a.pdf", ("HC", 1)),
        status="ok", wall_s=2.0,
    ))
    log.append(make_log_record(
        task=_text_task("https://stf/a.pdf", ("HC", 1)),
        status="ok", wall_s=0.3, extractor="pypdf", chars=18234,
    ))

    parsed = [
        json.loads(line)
        for line in (tmp_path / LOG_NAME).read_text().splitlines()
    ]
    assert parsed[2]["chars"] == 18234

    state = recover_state_from_log(tmp_path / LOG_NAME)
    assert state.text_chars(("HC", 1), url="https://stf/a.pdf") == 18234


def test_recover_skips_truncated_tail_line(tmp_path: Path) -> None:
    """A truncated final line (process killed mid-write) doesn't crash
    recovery — the prior rows are still durable."""
    path = tmp_path / LOG_NAME
    path.write_text(
        json.dumps({
            "ts": "2026-01-01T00:00:00Z", "kind": "fetch_meta",
            "classe": "HC", "processo": 1, "status": "ok", "wall_s": 1.0,
        }) + "\n"
        + '{"kind": "fetch_meta", "classe": "HC", "processo":'  # truncated
    )
    state = recover_state_from_log(path)
    assert state.meta_status(("HC", 1)) == "ok"


# ---------------------------------------------------------------------------
# Errors-file derivation
# ---------------------------------------------------------------------------


def test_derive_errors_file_writes_only_non_ok(tmp_path: Path) -> None:
    """One row per non-ok target. ok rows are not present (they're not
    errors). Atomic file: never partial."""
    state = PipelineState(path=tmp_path / "executar.state.json", cases={}, started_at="x")
    state.record_meta(("HC", 1), status="ok")
    state.record_meta(("HC", 2), status="http_error", error="WAF 403")
    state.record_bytes(("HC", 1), url="https://stf/a.pdf", status="ok", doc_type="VOTO")
    state.record_bytes(
        ("HC", 1), url="https://stf/b.pdf", status="http_error",
        error="timeout", doc_type="DESPACHO",
    )
    state.record_text(
        ("HC", 1), url="https://stf/a.pdf", status="provider_error",
        extractor="pypdf", error="bad PDF",
    )

    out = derive_errors_file(tmp_path, state, [("HC", 1), ("HC", 2)])
    assert out == tmp_path / ERRORS_NAME
    rows = read_errors_file(out)

    by_kind = {(r["kind"], r["processo"]): r for r in rows}
    assert ("fetch_meta", 2) in by_kind
    # bytes-side error shouldn't include text descendants — tested below
    assert ("fetch_bytes", 1) in by_kind
    # ok rows omitted
    assert ("fetch_meta", 1) not in by_kind
    assert by_kind[("fetch_bytes", 1)]["url"] == "https://stf/b.pdf"
    assert by_kind[("fetch_bytes", 1)]["doc_type"] == "DESPACHO"


def test_derive_errors_file_excludes_skipped_cached(tmp_path: Path) -> None:
    """``skipped_cached`` is a terminal-ok outcome, NOT a failure: the
    sidecar-skip path on extract_text records this status when the
    cached text already matches the requested provider, so re-OCR
    was deliberately skipped. Including it in errors.jsonl would
    re-seed the same already-completed work on the next
    --retentar-de pass — exactly what sidecar-skip exists to avoid.

    Pinned by a real bug surfaced during end-to-end smoke testing of
    the v1.5 deepenings: a 5-case re-run produced 9 spurious
    skipped_cached rows in executar.errors.jsonl.
    """
    state = PipelineState(path=tmp_path / "executar.state.json", cases={}, started_at="x")
    state.record_meta(("HC", 1), status="ok")
    state.record_bytes(("HC", 1), url="https://stf/x.pdf", status="ok", doc_type="VOTO")
    state.record_text(
        ("HC", 1), url="https://stf/x.pdf", status="skipped_cached",
        extractor="pypdf",
    )
    out = derive_errors_file(tmp_path, state, [("HC", 1)])
    rows = read_errors_file(out)
    assert rows == [], (
        f"skipped_cached should not appear in errors.jsonl, got: {rows}"
    )


def test_derive_errors_file_skips_text_when_bytes_failed(tmp_path: Path) -> None:
    """If bytes failed, text below it can never have been ok — the bytes
    row alone captures the failure root. Don't emit a redundant text row."""
    state = PipelineState(path=tmp_path / "executar.state.json", cases={}, started_at="x")
    state.record_meta(("HC", 1), status="ok")
    state.record_bytes(
        ("HC", 1), url="https://stf/x.pdf", status="http_error", error="x",
    )
    # No text row at all: the bytes failure means no text was ever attempted.
    out = derive_errors_file(tmp_path, state, [("HC", 1)])
    rows = read_errors_file(out)
    assert len(rows) == 1
    assert rows[0]["kind"] == "fetch_bytes"


# ---------------------------------------------------------------------------
# Unified-vocabulary error classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status,expected", [
    ("ok", "ok"),
    ("skipped_cached", "ok"),
    ("http_error", "transient"),
    ("provider_error", "transient"),
    ("no_bytes", "cross_stage"),
    ("unallocated_pid", "terminal"),
    ("empty", "terminal"),
])
def test_classify_unified_error_table(status, expected):
    """Every TaskStatus the unified pipeline emits maps to a defined
    triage outcome — pinning the table prevents a future deepening
    from quietly changing the retry policy."""
    assert classify_unified_error({"status": status}) == expected


# ---------------------------------------------------------------------------
# Range / replay target builders
# ---------------------------------------------------------------------------


def test_targets_from_range_inclusive_uppercase():
    targets = targets_from_range("hc", 100, 102)
    assert targets == [("HC", 100), ("HC", 101), ("HC", 102)]


def test_targets_from_errors_jsonl_only_transient(tmp_path: Path):
    """--retentar-de seeds only retryable failures. Terminal rows
    (unallocated_pid, empty) are dropped — they can't recover."""
    errors = tmp_path / ERRORS_NAME
    errors.write_text(
        json.dumps({"kind": "fetch_meta", "classe": "HC", "processo": 1,
                    "status": "http_error"}) + "\n"
        + json.dumps({"kind": "fetch_meta", "classe": "HC", "processo": 2,
                      "status": "unallocated_pid"}) + "\n"
        + json.dumps({"kind": "fetch_bytes", "classe": "HC", "processo": 3,
                      "status": "http_error"}) + "\n"
        + json.dumps({"kind": "extract_text", "classe": "HC", "processo": 4,
                      "status": "no_bytes"}) + "\n"
        + json.dumps({"kind": "extract_text", "classe": "HC", "processo": 1,
                      "status": "provider_error"}) + "\n",
    )
    targets = targets_from_errors_jsonl(errors)
    # HC-1 appears once (dedup across kinds), HC-3 transient, HC-2 dropped
    # (terminal), HC-4 dropped (cross-stage).
    assert sorted(targets) == [("HC", 1), ("HC", 3)]


# ---------------------------------------------------------------------------
# Sidecar-match skip on extract_text
# ---------------------------------------------------------------------------


def test_handle_extract_text_skips_when_sidecar_matches(tmp_path: Path, monkeypatch):
    """Sidecar already records the same provider → skip OCR, status =
    skipped_cached. Saves the OCR cost on resume across pipelines."""
    from judex.pipeline import handlers as handlers_mod
    from judex.utils import peca_cache

    # Point peca_cache at a tmpdir so we don't touch the real cache.
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path / "texto")
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path / "pecas")
    (tmp_path / "texto").mkdir()
    (tmp_path / "pecas").mkdir()

    url = "https://stf/x.pdf"
    # Pre-seed: cached text + matching sidecar.
    peca_cache.write(url, "cached text body", extractor="pypdf")

    state = PipelineState(path=tmp_path / "s.json", cases={}, started_at="x")
    state.record_meta(("HC", 1), status="ok")
    handlers = handlers_mod.make_handlers(state, provedor="pypdf", forcar=False)

    successors = handlers["extract_text"](_text_task(url, ("HC", 1)))
    assert successors == []
    assert state.text_status(("HC", 1), url=url) == "skipped_cached"
    assert state.text_extractor(("HC", 1), url=url) == "pypdf"


def test_handle_extract_text_forcar_bypasses_sidecar(tmp_path: Path, monkeypatch):
    """--forcar disables the skip even when sidecar matches — the OCR
    runs again. We don't dispatch real OCR here; instead we let the
    handler proceed past the skip check and then fail at read_bytes
    (no bytes seeded), proving the skip branch was bypassed."""
    from judex.pipeline import handlers as handlers_mod
    from judex.utils import peca_cache

    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path / "texto")
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path / "pecas")
    (tmp_path / "texto").mkdir()
    (tmp_path / "pecas").mkdir()

    url = "https://stf/x.pdf"
    peca_cache.write(url, "cached text", extractor="pypdf")
    # No bytes in cache → handler will hit no_bytes, but only because
    # forcar=True bypassed the would-be skipped_cached short-circuit.

    state = PipelineState(path=tmp_path / "s.json", cases={}, started_at="x")
    state.record_meta(("HC", 1), status="ok")
    handlers = handlers_mod.make_handlers(state, provedor="pypdf", forcar=True)

    handlers["extract_text"](_text_task(url, ("HC", 1)))
    assert state.text_status(("HC", 1), url=url) == "no_bytes"


# ---------------------------------------------------------------------------
# analisar-regimes adapter
# ---------------------------------------------------------------------------


def test_analyze_regimes_detects_executar_log(tmp_path: Path):
    """analisar-regimes auto-finds executar.log.jsonl when no legacy
    log is present."""
    from scripts.analyze_regimes import detect_log_kind, iter_regime_events

    log = tmp_path / "executar.log.jsonl"
    log.write_text(
        json.dumps({
            "ts": "2026-01-01T00:00:00Z", "kind": "fetch_meta",
            "classe": "HC", "processo": 100, "status": "ok", "wall_s": 1.0,
            "regime": "healthy", "regime_fail_rate": 0.05,
            "regime_p95_wall_s": 8.0, "regime_promoted_by": "axis_a",
        }) + "\n"
    )
    kind, path = detect_log_kind(tmp_path)
    assert kind == "executar"
    assert path == log

    events = list(iter_regime_events(log))
    assert len(events) == 1
    assert events[0].regime == "healthy"
    assert events[0].key == "HC_100"
