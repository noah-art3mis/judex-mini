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

from judex.scraping.proxy_pool import ProxyPool
from judex.sweeps import shared as _shared
from judex.sweeps.download_driver import run_download_sweep
from judex.sweeps.peca_store import PecaStore
from judex.sweeps.peca_targets import PecaTarget
from judex.utils import peca_cache


@pytest.fixture(autouse=True)
def _isolated_pdf_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "judex.utils.peca_cache.CACHE_ROOT", tmp_path / "peca_cache",
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


def test_proxy_pool_rotates_session_after_rotate_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a 2-proxy pool and rotate_seconds=270, a getter call that advances
    the clock past 270 s triggers a session swap before the next fetch. The
    retired proxy is put on cooldown; the replacement session is a different
    object from the initial one.
    """
    clock = [1000.0]
    monkeypatch.setattr(
        "judex.sweeps.download_driver.time.monotonic", lambda: clock[0]
    )
    pool = ProxyPool(
        ["http://a.proxy:1", "http://b.proxy:1"], _now=lambda: clock[0]
    )

    sessions_seen: list[int] = []

    def getter(session, target, config):
        sessions_seen.append(id(session))
        clock[0] += 300.0
        return b"x"

    run_download_sweep(
        [_target(f"https://x.test/{i}.pdf") for i in range(3)],
        **_kwargs(
            tmp_path / "sweep",
            getter=getter,
            session=None,
            pool=pool,
            proxy_rotate_seconds=270.0,
            proxy_cooldown_minutes=4.0,
        ),
    )
    assert len(set(sessions_seen)) >= 2


def test_proxy_pool_reactive_rotation_on_approaching_collapse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reactive rotation: once CliffDetector's regime enters
    `approaching_collapse` and the proxy has been in use for >30 s, rotate
    even if --proxy-rotate-seconds hasn't elapsed yet. Simulated by a getter
    that advances the fake clock by 35 s per call (> p95 threshold of 30 s):
    after ~MIN_OBS=20 observations the regime promotes to
    approaching_collapse, and the next post-item rotation check fires.
    """
    clock = [1000.0]
    monkeypatch.setattr(
        "judex.sweeps.download_driver.time.monotonic", lambda: clock[0]
    )
    # on_item measures `wall = time.perf_counter() - t0` and feeds it to
    # CliffDetector. Mock perf_counter to match the fake-monotonic clock
    # so the detector sees p95 > 30 and promotes to approaching_collapse.
    monkeypatch.setattr(
        "judex.sweeps.download_driver.time.perf_counter", lambda: clock[0]
    )
    # Pool-exhaustion branch calls the real time.sleep(); neuter it so
    # the test doesn't hang waiting for a 4-minute cooldown.
    monkeypatch.setattr("judex.sweeps.download_driver.time.sleep", lambda _s: None)
    pool = ProxyPool(
        ["http://a.proxy:1", "http://b.proxy:1", "http://c.proxy:1"],
        _now=lambda: clock[0],
    )

    sessions_seen: list[int] = []

    def getter(session, target, config):
        sessions_seen.append(id(session))
        clock[0] += 35.0  # p95 > 30 ⇒ WAF-shaped slow, promotes regime
        return b"x"

    run_download_sweep(
        [_target(f"https://x.test/{i}.pdf") for i in range(25)],
        **_kwargs(
            tmp_path / "sweep",
            getter=getter,
            session=None,
            pool=pool,
            proxy_rotate_seconds=1_000_000.0,  # effectively disabled
            proxy_cooldown_minutes=4.0,
            cliff_window=50,
        ),
    )
    # Time-based rotation cannot fire (threshold is 1M s). The only way to
    # see >1 session is reactive-rotation on approaching_collapse.
    assert len(set(sessions_seen)) >= 2


def test_no_pool_keeps_single_session(tmp_path: Path) -> None:
    """Without a pool the driver must not rotate — every getter call sees
    the same session object for the life of the sweep.
    """
    sessions_seen: list[int] = []

    def getter(session, target, config):
        sessions_seen.append(id(session))
        return b"x"

    run_download_sweep(
        [_target(f"https://x.test/{i}.pdf") for i in range(3)],
        **_kwargs(tmp_path / "sweep", getter=getter),
    )
    assert len(set(sessions_seen)) == 1


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
