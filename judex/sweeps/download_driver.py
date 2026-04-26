"""Download driver — the WAF-bound half of the PDF pipeline.

This is the ONLY path that talks to STF after the 2026-04-19 split.
It fetches `PecaTarget.url` via `_http_get_with_retry` and writes the
raw bytes to `data/raw/pecas/<sha1>.<ext>.gz`. Text extraction is an
independent concern, handled by `extract_driver.run_extract_sweep`.

Layout under `out_dir` is shared with the process sweep convention:

    pdfs.state.json       atomic per-URL state (via PecaStore)
    pdfs.log.jsonl        append-only attempt log
    pdfs.errors.jsonl     derived on write_errors_file()
    requests.db           per-GET SQLite archive (WAL mode)
    report.md             human-readable summary

Skip logic per target:

    --retomar + state=ok   → skip (no breaker accounting)
    has_bytes + not forcar → skip, status=cached
    otherwise              → HTTP GET, write bytes, status=ok
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from judex.config import ScraperConfig
from judex.scraping.http_session import _http_get_with_retry, new_session
from judex.scraping.proxy_pool import ProxyPool
from judex.sweeps import shared as _shared
from judex.utils.pricing import estimate_proxy_cost
from judex.sweeps.peca_store import PecaAttemptRecord, PecaStore, load_retry_list
from judex.sweeps.peca_targets import PecaTarget
from judex.utils import peca_cache
from judex.utils.adaptive_throttle import AdaptiveThrottle
from judex.utils.request_log import RequestLog


GetterFn = Callable[[Any, PecaTarget, ScraperConfig], bytes]
"""(session, target, config) -> raw bytes. Raises on HTTP failure;
the driver catches and records status="http_error". Tests inject a
deterministic getter; production leaves it None and gets
`_default_getter`.
"""


@dataclass
class _Counters:
    downloaded: int = 0
    cached_hits: int = 0
    failed: int = 0


def _default_getter(
    session: Any, target: PecaTarget, config: ScraperConfig
) -> bytes:
    r = _http_get_with_retry(session, target.url, config=config, timeout=60)
    return r.content


def run_download_sweep(
    targets: list[PecaTarget],
    *,
    out_dir: Path,
    forcar: bool = False,
    # Per-record fixed throttle defaults to 0 — pacing comes from
    # AdaptiveThrottle (which ratchets up on slow / error responses
    # via record(was_error=True)) and tenacity's 403 backoff. Matches
    # the convention in shared.py and extract_driver.py; the prior
    # 2.0s default was a lone outlier that throttled cached records
    # and squandered the cache-skip fast path.
    throttle_sleep: float = 0.0,
    resume: bool = False,
    retry_from: Optional[Path] = None,
    circuit_window: int = 50,
    circuit_threshold: float = 0.8,
    adaptive_throttle: bool = True,
    throttle_max_delay: float = 60.0,
    progress_every: int = 25,
    session: Optional[requests.Session] = None,
    config: Optional[ScraperConfig] = None,
    install_signal_handlers: bool = True,
    getter: Optional[GetterFn] = None,
    pool: Optional[ProxyPool] = None,
    proxy_rotate_seconds: float = 270.0,
    proxy_cooldown_minutes: float = 4.0,
    cliff_window: int = 50,
) -> tuple[int, int, int]:
    """Run a PDF download sweep. Returns `(downloaded, cached_hits, failed)`."""
    out_dir = Path(out_dir)
    store = PecaStore(out_dir)

    if retry_from is not None:
        keep = set(load_retry_list(retry_from))
        targets = [t for t in targets if t.url in keep]

    if install_signal_handlers:
        _shared._reset_shutdown_for_tests()
        _shared.install_signal_handlers()

    if config is None:
        throttle = (
            AdaptiveThrottle(
                target_concurrency=1.0,
                start_delay=0.0,
                max_delay=throttle_max_delay,
            )
            if adaptive_throttle else None
        )
        request_log = RequestLog(out_dir / "requests.db")
        config = ScraperConfig(throttle=throttle, request_log=request_log)

    pool_active = pool is not None and pool.size() > 0
    initial_proxy = pool.pick() if pool_active else None
    owns_session = session is None
    if session is None:
        session = new_session(proxy=initial_proxy)

    session_holder: dict[str, Any] = {
        "session": session,
        "proxy": initial_proxy,
        "started_at": time.monotonic(),
        "rotations": 0,
    }

    def rotate_session(reason: str) -> None:
        old = session_holder["proxy"]
        assert pool is not None  # pool_active implies pool is not None
        pool.mark_hot(old, minutes=proxy_cooldown_minutes)
        try:
            session_holder["session"].close()
        except Exception:
            pass
        new_proxy = pool.pick()
        if new_proxy is None:
            wait_s = pool.time_until_next_available()
            print(
                f"  [rotate] all proxies hot — waiting {wait_s:.0f}s",
                flush=True,
            )
            time.sleep(wait_s + 1.0)
            new_proxy = pool.pick()
        session_holder["session"] = new_session(proxy=new_proxy)
        session_holder["proxy"] = new_proxy
        session_holder["started_at"] = time.monotonic()
        session_holder["rotations"] += 1
        print(f"  [rotate] reason={reason}", flush=True)

    breaker: Optional[_shared.CircuitBreaker] = (
        _shared.CircuitBreaker(circuit_window, circuit_threshold)
        if circuit_window > 0 else None
    )
    detector = _shared.CliffDetector(window=cliff_window)
    last_regime: dict[str, str] = {"value": "warming"}

    counters = _Counters()
    started = datetime.now(timezone.utc)
    print(
        f"=== pdf download · {len(targets)} targets · out={out_dir} ===",
        flush=True,
    )

    get_fn: GetterFn = getter or _default_getter

    def on_item(i: int, n: int, tgt: PecaTarget) -> str:
        # Bytes-cache fast path — bytes already on disk.
        if not forcar and peca_cache.has_bytes(tgt.url):
            counters.cached_hits += 1
            store.record(_make_record(
                tgt, status="cached", extractor="bytes",
                wall_s=0.0,
                attempt=store.attempt_count(tgt.url) + 1,
            ))
            if config.request_log is not None:
                config.request_log.log(
                    url=tgt.url, from_cache=True,
                    context={
                        "processo_id": tgt.processo_id,
                        "classe": tgt.classe,
                        "doc_type": tgt.doc_type,
                        **tgt.context,
                    },
                )
            return "ok"

        t0 = time.perf_counter()
        status = "ok"
        error: Optional[str] = None
        error_type: Optional[str] = None
        http_status: Optional[int] = None
        body: Optional[bytes] = None
        try:
            body = get_fn(session_holder["session"], tgt, config)
        except Exception as e:
            status = "http_error"
            etype, hstatus, _ = _shared.classify_exception(e)
            error_type = etype
            http_status = hstatus
            error = f"{etype}: {e}"

        wall = time.perf_counter() - t0

        if status == "ok" and body is not None:
            peca_cache.write_bytes(tgt.url, body)
            counters.downloaded += 1
            logging.info(f"[{i}/{n}] {tgt.url}: ok ({len(body)} bytes)")
        else:
            counters.failed += 1
            if error is None:
                error = status
                error_type = error_type or status
            logging.warning(
                f"[{i}/{n}] {tgt.url}: {status}"
                + (f" ({error})" if error else "")
            )

        # Observe first so the regime stamped on this record includes its
        # own contribution to the rolling window — the cliff-trigger record
        # then carries the cliff label, not the prior-window-only label.
        detector.observe(status, wall, http_status=http_status)
        reading = detector.regime()

        store.record(_make_record(
            tgt, status=status, error=error, error_type=error_type,
            http_status=http_status, extractor="bytes",
            chars=len(body) if body is not None else None,
            wall_s=round(wall, 3),
            attempt=store.attempt_count(tgt.url) + 1,
            reading=reading,
        ))

        if reading.label != last_regime["value"]:
            print(
                f"  [regime] {last_regime['value']} → {reading.label}"
                f"  (fail_rate={reading.fail_rate:.2f} p95={reading.p95_wall_s:.1f}s "
                f"by={reading.promoted_by}; see docs/rate-limits.md § Wall taxonomy)",
                flush=True,
            )
            last_regime["value"] = reading.label

        if pool_active:
            elapsed_on_proxy = time.monotonic() - session_holder["started_at"]
            rotate_reason: Optional[str] = None
            if elapsed_on_proxy > proxy_rotate_seconds:
                rotate_reason = f"time>{proxy_rotate_seconds:.0f}s"
            elif reading.label == "approaching_collapse" and elapsed_on_proxy > 30.0:
                rotate_reason = "approaching_collapse"
            if rotate_reason is not None:
                rotate_session(reason=rotate_reason)

        return status

    def on_progress(i: int, n: int) -> None:
        _, rate, eta_s = _shared.elapsed_rate_eta(started, i, n)
        print(
            f"  [progress] ok={counters.downloaded} cached={counters.cached_hits} "
            f"fail={counters.failed} · {rate:.2f} tgt/s · "
            f"eta {eta_s / 60:.1f} min",
            flush=True,
        )

    def is_already_done(tgt: PecaTarget) -> bool:
        return resume and store.already_ok(tgt.url)

    def on_resume_skip(_tgt: PecaTarget) -> None:
        counters.cached_hits += 1

    try:
        tripped = _shared.iterate_with_guards(
            targets,
            on_item=on_item,
            should_resume_skip=is_already_done,
            on_skip=on_resume_skip,
            breaker=breaker,
            error_statuses=("http_error",),
            trip_noun="downloads",
            progress_every=progress_every,
            on_progress=on_progress,
            throttle_sleep=throttle_sleep,
        )
    finally:
        if owns_session or session_holder["rotations"] > 0:
            try:
                session_holder["session"].close()
            except Exception:
                pass

    finished = datetime.now(timezone.utc)
    errors_path = store.write_errors_file()

    # Total bytes downloaded this sweep (status=ok only; cache hits don't
    # count against proxy bandwidth). Derived from the store's snapshot.
    snap = store.snapshot()
    bytes_this_sweep = sum(
        r.get("chars") or 0
        for r in snap.values()
        if r.get("status") == "ok"
    )
    cost = estimate_proxy_cost(
        bytes_downloaded=bytes_this_sweep, used_proxy=pool_active,
    )

    report_path = _render_download_report(
        out_dir=out_dir, store=store, request_log=config.request_log,
        started=started, finished=finished, cost=cost,
    )

    print(
        f"\nsummary: downloaded={counters.downloaded} cached={counters.cached_hits} "
        f"failed={counters.failed}"
        + (f"  rotations={session_holder['rotations']}" if pool_active else "")
        + ("  (circuit tripped)" if tripped else ""),
        flush=True,
    )
    print(f"  {cost.summary_line()}")
    print(f"  state:  {store.state_path}")
    print(f"  log:    {store.log_path}")
    print(f"  errors: {errors_path}")
    print(f"  report: {report_path}")
    return counters.downloaded, counters.cached_hits, counters.failed


def _make_record(
    tgt: PecaTarget,
    *,
    status: str,
    attempt: int,
    wall_s: float,
    error: Optional[str] = None,
    error_type: Optional[str] = None,
    http_status: Optional[int] = None,
    extractor: Optional[str] = None,
    chars: Optional[int] = None,
    reading: Optional[_shared.RegimeReading] = None,
) -> PecaAttemptRecord:
    return PecaAttemptRecord(
        ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        url=tgt.url,
        attempt=attempt,
        wall_s=wall_s,
        status=status,
        error=error,
        error_type=error_type,
        http_status=http_status,
        extractor=extractor,
        chars=chars,
        processo_id=tgt.processo_id,
        classe=tgt.classe,
        doc_type=tgt.doc_type,
        context=tgt.context,
        **_shared.regime_kwargs(reading),
    )


def _render_download_report(
    *,
    out_dir: Path,
    store: PecaStore,
    request_log: Optional[RequestLog],
    started: datetime,
    finished: datetime,
    cost: Optional[Any] = None,
) -> Path:
    snap = store.snapshot()
    status_counts: Counter = Counter(
        r.get("status", "unknown") for r in snap.values()
    )
    by_doc_type: Counter = Counter(
        r.get("doc_type") or "-" for r in snap.values()
    )

    lines = [
        f"# PDF download sweep — {out_dir.name}",
        "",
        f"- started:  {started.isoformat(timespec='seconds')}",
        f"- finished: {finished.isoformat(timespec='seconds')}",
        f"- elapsed:  {(finished - started).total_seconds():.1f}s",
        f"- targets:  {len(snap)}",
    ]
    if cost is not None:
        lines.append(f"- {cost.summary_line()}")
    lines += [
        "",
        "## Status",
        "",
        "| status | n |",
        "|--------|--:|",
    ]
    for s, n in sorted(status_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {s} | {n} |")
    lines += ["", "## Doc type", "", "| doc_type | n |", "|----------|--:|"]
    for d, n in sorted(by_doc_type.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {d} | {n} |")

    if request_log is not None:
        stats = request_log.per_host_stats()
        lines += ["", "## HTTP summary (per host)", ""]
        if stats:
            lines.append(
                "| host | reqs | cache | 200 | 403 | 5xx | p50 ms | p90 ms | max ms |"
            )
            lines.append(
                "|------|-----:|-----:|----:|----:|----:|-------:|-------:|-------:|"
            )
            for s in stats:
                lines.append(
                    f"| `{s['host']}` | {s['n']} | {s['cache_hits']} | "
                    f"{s['n_200']} | {s['n_403']} | {s['n_5xx']} | "
                    f"{s['p50_ms']} | {s['p90_ms']} | {s['max_ms']} |"
                )
        else:
            lines.append("_No requests logged._")

    path = out_dir / "report.md"
    path.write_text("\n".join(lines) + "\n")
    return path
