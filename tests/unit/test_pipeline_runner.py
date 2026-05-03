"""End-to-end runner tests using mocked handlers.

Tests at this layer drive ``run_pipeline()`` rather than
``run_scheduler()``, so they exercise the same code path the Typer
command will hit. They use mocked handlers so they don't touch STF.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from judex.pipeline.models import Task
from judex.pipeline.runner import read_targets_csv, run_pipeline
from judex.pipeline.state import PipelineState


def _mock_handlers_factory(state: PipelineState, **kwargs: object) -> dict[str, object]:
    """Test factory: same shape as make_handlers but synthetic."""
    peças = 2

    def handle_meta(task: Task) -> list[Task]:
        state.record_meta(task.case_key, status="ok")
        return [
            Task(kind="fetch_bytes", pool="sistemas",
                 payload={"url": f"u-{task.case_key[1]}-{i}"},
                 case_key=task.case_key)
            for i in range(peças)
        ]

    def handle_bytes(task: Task) -> list[Task]:
        state.record_bytes(task.case_key, url=task.payload["url"], status="ok")
        return [
            Task(kind="extract_text", pool="ocr",
                 payload={"url": task.payload["url"]},
                 case_key=task.case_key)
        ]

    def handle_text(task: Task) -> list[Task]:
        state.record_text(
            task.case_key, url=task.payload["url"],
            status="ok", extractor=kwargs.get("provedor", "pypdf"),
        )
        return []

    return {
        "fetch_meta": handle_meta,
        "fetch_bytes": handle_bytes,
        "extract_text": handle_text,
    }


def test_run_pipeline_writes_state_and_report(tmp_path: Path) -> None:
    saida = tmp_path / "run"
    targets = [("HC", 1), ("HC", 2)]

    rc = run_pipeline(
        targets=targets,
        saida=saida,
        provedor="pypdf",
        handlers_factory=_mock_handlers_factory,
    )
    assert rc == 0

    # State file landed.
    state_path = saida / "executar.state.json"
    assert state_path.exists()
    state = PipelineState.load(state_path)
    for c in targets:
        assert state.is_meta_complete(c)
        for i in range(2):
            assert state.is_bytes_complete(c, url=f"u-{c[1]}-{i}")
            assert state.is_text_complete(c, url=f"u-{c[1]}-{i}", required_extractor="pypdf")

    # Report file landed and contains expected sections.
    report = (saida / "report.md").read_text()
    assert "# Unified pipeline run" in report
    assert "Per-pool" in report
    assert "Per-stage status" in report
    assert "targets: 2" in report


def test_run_pipeline_resumes_from_existing_state(tmp_path: Path) -> None:
    """A second invocation against an already-complete state file is
    a no-op (no scheduler run, just a fresh report)."""
    saida = tmp_path / "run"
    targets = [("HC", 1)]

    # First run: complete the work.
    run_pipeline(
        targets=targets, saida=saida, provedor="pypdf",
        handlers_factory=_mock_handlers_factory,
    )

    # Tamper: add a sentinel that would be wiped if the runner started
    # fresh. (Marker isn't a real run artefact; just a witness.)
    sentinel = saida / "do_not_touch.txt"
    sentinel.write_text("preserved")

    # Second run: state already shows everything as ok; runner detects
    # zero seeds and returns without entering the asyncio scheduler.
    rc = run_pipeline(
        targets=targets, saida=saida, provedor="pypdf",
        handlers_factory=_mock_handlers_factory,
    )
    assert rc == 0
    assert sentinel.exists()  # untouched

    # Report still gets re-rendered with the latest state.
    report = (saida / "report.md").read_text()
    assert "targets: 1" in report


def test_run_pipeline_partial_resume(tmp_path: Path) -> None:
    """If state shows HC-1 fully done and HC-2 not yet started, the
    runner only seeds HC-2's work."""
    saida = tmp_path / "run"
    state_path = saida / "executar.state.json"
    saida.mkdir()

    # Pre-seed state for HC-1 only.
    state = PipelineState.load(state_path)
    state.record_meta(("HC", 1), status="ok")
    for i in range(2):
        url = f"u-1-{i}"
        state.record_bytes(("HC", 1), url=url, status="ok")
        state.record_text(("HC", 1), url=url, status="ok", extractor="pypdf")
    state.snapshot()

    targets = [("HC", 1), ("HC", 2)]
    rc = run_pipeline(
        targets=targets, saida=saida, provedor="pypdf",
        handlers_factory=_mock_handlers_factory,
    )
    assert rc == 0

    state = PipelineState.load(state_path)
    # HC-1 untouched; HC-2 now complete.
    for c in targets:
        assert state.is_meta_complete(c)
        for i in range(2):
            assert state.is_bytes_complete(c, url=f"u-{c[1]}-{i}")


# ---------------------------------------------------------------------------
# CSV reader
# ---------------------------------------------------------------------------


def test_read_targets_csv_classe_processo(tmp_path: Path) -> None:
    csv = tmp_path / "alvos.csv"
    csv.write_text("classe,processo\nHC,123\nHC,124\nRE,42\n")
    assert read_targets_csv(csv) == [("HC", 123), ("HC", 124), ("RE", 42)]


def test_read_targets_csv_processo_id_alias(tmp_path: Path) -> None:
    csv = tmp_path / "alvos.csv"
    csv.write_text("classe,processo_id\nHC,123\n")
    assert read_targets_csv(csv) == [("HC", 123)]


def test_read_targets_csv_missing_columns(tmp_path: Path) -> None:
    csv = tmp_path / "alvos.csv"
    csv.write_text("foo,bar\nHC,123\n")
    with pytest.raises(ValueError, match="missing 'classe'"):
        read_targets_csv(csv)


def test_read_targets_csv_skips_blank_rows(tmp_path: Path) -> None:
    csv = tmp_path / "alvos.csv"
    csv.write_text("classe,processo\nHC,123\n,\nHC,124\n")
    assert read_targets_csv(csv) == [("HC", 123), ("HC", 124)]
