"""run_pdf_sweep — end-to-end with mocked fetcher.

Exercises:
- successful fetch path (text caching, state recording)
- http_error path (exception → classify → record with error_type)
- empty-text path (PyPDF returned None → status="empty")
- disk-cache fast path (pdf_cache hit, no network call)
- --resume semantics (already-ok URLs skipped on second run)
- --retry-from semantics (re-run filtered to URLs in errors.jsonl)
- circuit breaker trips on cascading http_errors
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.sweeps import shared as _shared
from src.sweeps.pdf_driver import run_pdf_sweep
from src.sweeps.pdf_store import PdfStore
from src.sweeps.pdf_targets import PdfTarget


@pytest.fixture(autouse=True)
def _isolated_pdf_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the process-wide PDF cache into per-test tmp_path/pdf_cache."""
    monkeypatch.setattr(
        "src.utils.pdf_cache.CACHE_ROOT", tmp_path / "pdf_cache",
    )


@pytest.fixture(autouse=True)
def _reset_shutdown() -> None:
    _shared._reset_shutdown_for_tests()


def _target(url: str, **kw) -> PdfTarget:
    return PdfTarget(url=url, **kw)


def _sweep_kwargs(out_dir: Path, **overrides) -> dict:
    defaults = dict(
        out_dir=out_dir,
        throttle_sleep=0,
        circuit_window=0,
        session=object(),
        install_signal_handlers=False,
    )
    defaults.update(overrides)
    return defaults


def test_sweep_records_ok_for_successful_fetch(tmp_path: Path) -> None:
    def fetcher(session, target, config):
        return "hello text body", "pypdf", "ok"

    fetched, cached, failed = run_pdf_sweep(
        [_target("https://x.test/a.pdf", processo_id=1, classe="HC")],
        **_sweep_kwargs(tmp_path / "sweep", fetcher=fetcher),
    )
    assert (fetched, failed) == (1, 0)
    store = PdfStore(tmp_path / "sweep")
    assert store.already_ok("https://x.test/a.pdf")
    snap = store.snapshot()["https://x.test/a.pdf"]
    assert snap["extractor"] == "pypdf"
    assert snap["chars"] == len("hello text body")
    assert snap["processo_id"] == 1
    assert snap["classe"] == "HC"


def test_sweep_records_http_error(tmp_path: Path) -> None:
    def fetcher(session, target, config):
        raise RuntimeError("boom")

    _, _, failed = run_pdf_sweep(
        [_target("https://x.test/a.pdf")],
        **_sweep_kwargs(tmp_path / "sweep", fetcher=fetcher),
    )
    assert failed == 1
    snap = PdfStore(tmp_path / "sweep").snapshot()["https://x.test/a.pdf"]
    assert snap["status"] == "http_error"
    assert snap["error_type"] == "RuntimeError"
    assert "boom" in snap["error"]


def test_sweep_records_empty_text(tmp_path: Path) -> None:
    def fetcher(session, target, config):
        return None, "pypdf", "empty"

    _, _, failed = run_pdf_sweep(
        [_target("https://x.test/a.pdf")],
        **_sweep_kwargs(tmp_path / "sweep", fetcher=fetcher),
    )
    assert failed == 1
    snap = PdfStore(tmp_path / "sweep").snapshot()["https://x.test/a.pdf"]
    assert snap["status"] == "empty"
    assert snap["extractor"] == "pypdf"


def test_disk_cache_hit_bypasses_fetcher(tmp_path: Path) -> None:
    calls = []

    def fetcher(session, target, config):
        calls.append(target.url)
        return "fresh text", "pypdf", "ok"

    # First run populates the cache.
    run_pdf_sweep(
        [_target("https://x.test/a.pdf")],
        **_sweep_kwargs(tmp_path / "sweep-one", fetcher=fetcher),
    )
    assert calls == ["https://x.test/a.pdf"]

    # Second run in a fresh out_dir finds the text already in pdf_cache.
    calls.clear()
    fetched, cached, failed = run_pdf_sweep(
        [_target("https://x.test/a.pdf")],
        **_sweep_kwargs(tmp_path / "sweep-two", fetcher=fetcher),
    )
    assert calls == []
    assert (fetched, cached, failed) == (0, 1, 0)
    snap = PdfStore(tmp_path / "sweep-two").snapshot()["https://x.test/a.pdf"]
    assert snap["extractor"] == "cache"
    assert snap["status"] == "ok"


def test_resume_skips_already_ok(tmp_path: Path) -> None:
    def fetcher(session, target, config):
        return "text", "pypdf", "ok"

    # First run records status=ok in the state file.
    run_pdf_sweep(
        [_target("https://x.test/a.pdf")],
        **_sweep_kwargs(tmp_path / "sweep", fetcher=fetcher),
    )

    # Second run with resume=True should never call the fetcher.
    calls = []
    def tripwire(session, target, config):
        calls.append(target.url)
        return "text", "pypdf", "ok"

    run_pdf_sweep(
        [_target("https://x.test/a.pdf")],
        **_sweep_kwargs(tmp_path / "sweep", fetcher=tripwire, resume=True),
    )
    assert calls == []


def test_retry_from_filters_to_errors_only(tmp_path: Path) -> None:
    def first_fetch(session, target, config):
        if target.url.endswith("a.pdf"):
            return "ok text", "pypdf", "ok"
        return None, "pypdf", "empty"

    sweep_dir = tmp_path / "sweep"
    run_pdf_sweep(
        [_target("https://x.test/a.pdf"), _target("https://x.test/b.pdf")],
        **_sweep_kwargs(sweep_dir, fetcher=first_fetch),
    )
    errors_path = sweep_dir / "pdfs.errors.jsonl"
    assert errors_path.exists()

    seen: list[str] = []
    def retry_fetch(session, target, config):
        seen.append(target.url)
        return "new text", "pypdf", "ok"

    run_pdf_sweep(
        [_target("https://x.test/a.pdf"), _target("https://x.test/b.pdf")],
        **_sweep_kwargs(sweep_dir, fetcher=retry_fetch, retry_from=errors_path),
    )
    assert seen == ["https://x.test/b.pdf"]


def test_circuit_breaker_trips_before_full_list(tmp_path: Path) -> None:
    def always_error(session, target, config):
        raise RuntimeError("boom")

    targets = [_target(f"https://x.test/{i}.pdf") for i in range(10)]
    fetched, cached, failed = run_pdf_sweep(
        targets,
        **_sweep_kwargs(
            tmp_path / "sweep",
            fetcher=always_error,
            circuit_window=5,
            circuit_threshold=0.5,
        ),
    )
    # Needs a full window of 5 errors before tripping; stops soon after.
    assert failed >= 5
    assert failed < 10


def test_report_md_written(tmp_path: Path) -> None:
    def fetcher(session, target, config):
        return "text", "pypdf", "ok"

    run_pdf_sweep(
        [_target("https://x.test/a.pdf", doc_type="DECISÃO MONOCRÁTICA")],
        **_sweep_kwargs(tmp_path / "sweep", fetcher=fetcher),
    )
    report = (tmp_path / "sweep" / "report.md").read_text()
    assert "PDF sweep" in report
    assert "DECISÃO MONOCRÁTICA" in report
    assert "pypdf" in report
