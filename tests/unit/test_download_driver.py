"""run_download_sweep — end-to-end with mocked byte getter.

Exercises:
- successful download path (bytes written, state=ok recorded)
- has_bytes cache-hit (no getter call, state=cached)
- --forcar bypasses cache and re-downloads
- HTTP error path (exception → classify → state=http_error)
- --retomar semantics (already-ok URLs skipped on second run)
- --retentar-de semantics (re-run filtered to URLs in errors.jsonl)
- circuit breaker trips on cascading http_errors
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.sweeps import shared as _shared
from src.sweeps.download_driver import run_download_sweep
from src.sweeps.peca_store import PecaStore
from src.sweeps.peca_targets import PecaTarget
from src.utils import peca_cache


@pytest.fixture(autouse=True)
def _isolated_pdf_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.utils.peca_cache.CACHE_ROOT", tmp_path / "peca_cache",
    )


@pytest.fixture(autouse=True)
def _reset_shutdown() -> None:
    _shared._reset_shutdown_for_tests()


def _target(url: str, **kw) -> PecaTarget:
    return PecaTarget(url=url, **kw)


def _kwargs(out_dir: Path, **overrides) -> dict:
    defaults = dict(
        out_dir=out_dir,
        throttle_sleep=0,
        circuit_window=0,
        session=object(),
        install_signal_handlers=False,
    )
    defaults.update(overrides)
    return defaults


def test_successful_download_writes_bytes_and_records_ok(tmp_path: Path) -> None:
    def getter(session, target, config):
        return b"%PDF-1.4\nhello\n%%EOF"

    downloaded, cached, failed = run_download_sweep(
        [_target("https://x.test/a.pdf", processo_id=1, classe="HC")],
        **_kwargs(tmp_path / "sweep", getter=getter),
    )

    assert (downloaded, cached, failed) == (1, 0, 0)
    assert peca_cache.read_bytes("https://x.test/a.pdf") == b"%PDF-1.4\nhello\n%%EOF"

    store = PecaStore(tmp_path / "sweep")
    snap = store.snapshot()["https://x.test/a.pdf"]
    assert snap["status"] == "ok"
    assert snap["processo_id"] == 1
    assert snap["classe"] == "HC"


def test_has_bytes_cache_hit_bypasses_getter(tmp_path: Path) -> None:
    """If bytes already on disk, skip the network entirely — record status=cached."""
    peca_cache.write_bytes("https://x.test/a.pdf", b"%PDF-1.4 prior")

    calls: list[str] = []

    def getter(session, target, config):
        calls.append(target.url)
        raise AssertionError("getter must not be called when bytes are cached")

    downloaded, cached, failed = run_download_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(tmp_path / "sweep", getter=getter),
    )

    assert calls == []
    assert (downloaded, cached, failed) == (0, 1, 0)
    snap = PecaStore(tmp_path / "sweep").snapshot()["https://x.test/a.pdf"]
    assert snap["status"] == "cached"


def test_forcar_bypasses_cache_and_overwrites(tmp_path: Path) -> None:
    """--forcar re-downloads even if bytes are cached, and the new
    bytes replace the old ones on disk.
    """
    peca_cache.write_bytes("https://x.test/a.pdf", b"OLD")

    def getter(session, target, config):
        return b"NEW"

    downloaded, cached, failed = run_download_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(tmp_path / "sweep", getter=getter, forcar=True),
    )

    assert (downloaded, cached, failed) == (1, 0, 0)
    assert peca_cache.read_bytes("https://x.test/a.pdf") == b"NEW"


def test_http_error_classified_and_recorded(tmp_path: Path) -> None:
    def getter(session, target, config):
        raise RuntimeError("network nope")

    _, _, failed = run_download_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(tmp_path / "sweep", getter=getter),
    )

    assert failed == 1
    snap = PecaStore(tmp_path / "sweep").snapshot()["https://x.test/a.pdf"]
    assert snap["status"] == "http_error"
    assert snap["error_type"] == "RuntimeError"
    assert "nope" in snap["error"]


def test_retomar_skips_already_ok(tmp_path: Path) -> None:
    """Second run with resume=True never calls the getter for URLs
    already in state=ok. Bytes cache is irrelevant here — state wins.
    """
    def getter(session, target, config):
        return b"pdf bytes"

    sweep_dir = tmp_path / "sweep"
    run_download_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(sweep_dir, getter=getter),
    )

    calls: list[str] = []
    def tripwire(session, target, config):
        calls.append(target.url)
        return b"should not be called"

    run_download_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(sweep_dir, getter=tripwire, resume=True),
    )
    assert calls == []


def test_retry_from_filters_to_errors_only(tmp_path: Path) -> None:
    """--retentar-de only re-downloads URLs that appear in the prior
    run's errors.jsonl; successful URLs are skipped even if they're in
    the target list.
    """
    def first_getter(session, target, config):
        if target.url.endswith("a.pdf"):
            return b"ok"
        raise RuntimeError("boom")

    sweep_dir = tmp_path / "sweep"
    run_download_sweep(
        [_target("https://x.test/a.pdf"), _target("https://x.test/b.pdf")],
        **_kwargs(sweep_dir, getter=first_getter),
    )
    errors_path = sweep_dir / "pdfs.errors.jsonl"
    assert errors_path.exists()

    seen: list[str] = []
    def retry_getter(session, target, config):
        seen.append(target.url)
        return b"retry"

    run_download_sweep(
        [_target("https://x.test/a.pdf"), _target("https://x.test/b.pdf")],
        **_kwargs(sweep_dir, getter=retry_getter, retry_from=errors_path),
    )
    assert seen == ["https://x.test/b.pdf"]


def test_circuit_breaker_trips_before_full_list(tmp_path: Path) -> None:
    """Cascading errors trip the breaker after `window` samples above
    threshold. Stops before exhausting the target list.
    """
    def always_error(session, target, config):
        raise RuntimeError("boom")

    targets = [_target(f"https://x.test/{i}.pdf") for i in range(10)]
    _, _, failed = run_download_sweep(
        targets,
        **_kwargs(
            tmp_path / "sweep",
            getter=always_error,
            circuit_window=5,
            circuit_threshold=0.5,
        ),
    )
    assert failed >= 5
    assert failed < 10
