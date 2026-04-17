"""Institutionalised PDF sweep driver.

Layout under `out_dir`:

    pdfs.state.json       atomic per-URL state (via PdfStore)
    pdfs.log.jsonl        append-only attempt log
    pdfs.errors.jsonl     derived on write_errors_file()
    requests.db           per-GET SQLite archive (WAL mode)
    report.md             human-readable summary

Per-URL loop with:
- `AdaptiveThrottle` + `RequestLog` wired through `ScraperConfig`
- existing `.cache/pdf/*.txt.gz` text cache reused via `pdf_cache`
- `_shared.CircuitBreaker` for cascade protection
- `_shared.install_signal_handlers()` for graceful SIGINT/SIGTERM
- `--resume` (via `PdfStore.already_ok`) and `--retry-from` (reads
  prior `pdfs.errors.jsonl` and scopes the run to that URL set)
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from src import _shared
from src.config import ScraperConfig
from src.pdf_store import PdfAttemptRecord, PdfStore, load_retry_list
from src.pdf_targets import PdfTarget
from src.http_session import _http_get_with_retry, new_session
from src.utils import pdf_cache
from src.utils.adaptive_throttle import AdaptiveThrottle
from src.utils.pdf_utils import (
    detect_file_type,
    extract_pdf_text_from_content,
    extract_rtf_text,
)
from src.utils.request_log import RequestLog


FetcherFn = Callable[
    [Any, PdfTarget, ScraperConfig],
    tuple[Optional[str], Optional[str], str],
]
"""(session, target, config) -> (text, extractor_name, status).

status ∈ {"ok", "empty", "unknown_type"}. Raises on HTTP failure;
the driver catches and records status="http_error".
"""


def _default_fetcher(
    session: Any, target: PdfTarget, config: ScraperConfig
) -> tuple[Optional[str], Optional[str], str]:
    r = _http_get_with_retry(session, target.url, config=config, timeout=60)
    ftype = detect_file_type(r)
    if ftype == "pdf":
        text = extract_pdf_text_from_content(r.content)
        return (text, "pypdf", "ok") if text else (None, "pypdf", "empty")
    if ftype == "rtf":
        text = extract_rtf_text(r.content)
        return (text, "rtf", "ok") if text else (None, "rtf", "empty")
    return (None, "unknown", "unknown_type")


def run_pdf_sweep(
    targets: list[PdfTarget],
    *,
    out_dir: Path,
    throttle_sleep: float = 2.0,
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
    fetcher: Optional[FetcherFn] = None,
) -> tuple[int, int, int]:
    """Run a PDF sweep. Returns `(fetched, cached_hits, failed)`.

    `fetcher` lets tests inject a deterministic function; production
    leaves it None and gets `_default_fetcher`.
    """
    out_dir = Path(out_dir)
    store = PdfStore(out_dir)

    if retry_from is not None:
        keep = set(load_retry_list(retry_from))
        targets = [t for t in targets if t.url in keep]

    if install_signal_handlers:
        _shared._reset_shutdown_for_tests()  # clear stale flag between runs
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

    owns_session = session is None
    if session is None:
        session = new_session()

    breaker: Optional[_shared.CircuitBreaker] = (
        _shared.CircuitBreaker(circuit_window, circuit_threshold)
        if circuit_window > 0 else None
    )
    error_statuses = ("http_error", "extract_error")

    fetched = 0
    cached_hits = 0
    failed = 0
    tripped = False

    started = datetime.now(timezone.utc)
    print(f"=== pdf sweep · {len(targets)} targets · out={out_dir} ===", flush=True)

    fetch_fn: FetcherFn = fetcher or _default_fetcher

    try:
        for i, tgt in enumerate(targets, 1):
            if _shared.shutdown_requested():
                print(f"  stopping before target {i}/{len(targets)}", flush=True)
                break

            if resume and store.already_ok(tgt.url):
                cached_hits += 1
                continue

            # Disk-cache fast path — no network, no throttle budget spent.
            existing_text = pdf_cache.read(tgt.url)
            if existing_text is not None:
                cached_hits += 1
                store.record(_make_record(
                    tgt, status="ok", extractor="cache",
                    chars=len(existing_text), wall_s=0.0,
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
                continue

            t0 = time.perf_counter()
            status = "ok"
            error: Optional[str] = None
            error_type: Optional[str] = None
            http_status: Optional[int] = None
            extractor: Optional[str] = None
            chars: Optional[int] = None
            text: Optional[str] = None
            try:
                text, extractor, status = fetch_fn(session, tgt, config)
            except Exception as e:
                status = "http_error"
                etype, hstatus, _ = _shared.classify_exception(e)
                error_type = etype
                http_status = hstatus
                error = f"{etype}: {e}"

            wall = time.perf_counter() - t0

            if status == "ok" and text:
                pdf_cache.write(tgt.url, text)
                chars = len(text)
                fetched += 1
                logging.info(
                    f"[{i}/{len(targets)}] {tgt.url}: ok ({chars} chars)"
                )
            else:
                failed += 1
                if status != "http_error" and error is None:
                    error = status
                    error_type = error_type or status
                logging.warning(
                    f"[{i}/{len(targets)}] {tgt.url}: {status}"
                    + (f" ({error})" if error else "")
                )

            store.record(_make_record(
                tgt, status=status, error=error, error_type=error_type,
                http_status=http_status, extractor=extractor, chars=chars,
                wall_s=round(wall, 3),
                attempt=store.attempt_count(tgt.url) + 1,
            ))

            if breaker is not None:
                breaker.record(status)
                if breaker.tripped(error_statuses):
                    tripped = True
                    print(
                        f"\n!! circuit breaker tripped: >{circuit_threshold:.0%} "
                        f"error-like statuses in the last {circuit_window} targets. "
                        f"Stopping at {i}/{len(targets)}.",
                        flush=True,
                    )
                    break

            if progress_every and i % progress_every == 0:
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                rate = i / elapsed if elapsed > 0 else 0
                eta = (len(targets) - i) / rate if rate > 0 else 0
                print(
                    f"  [progress] ok={fetched} cached={cached_hits} "
                    f"fail={failed} · {rate:.2f} tgt/s · "
                    f"eta {eta / 60:.1f} min",
                    flush=True,
                )

            if throttle_sleep > 0 and i < len(targets):
                time.sleep(throttle_sleep)
    finally:
        if owns_session:
            session.close()

    finished = datetime.now(timezone.utc)
    errors_path = store.write_errors_file()
    report_path = _render_pdf_report(
        out_dir=out_dir, store=store, request_log=config.request_log,
        started=started, finished=finished,
    )

    print(
        f"\nsummary: fetched={fetched} cached={cached_hits} failed={failed}"
        + ("  (circuit tripped)" if tripped else ""),
        flush=True,
    )
    print(f"  state:  {store.state_path}")
    print(f"  log:    {store.log_path}")
    print(f"  errors: {errors_path}")
    print(f"  report: {report_path}")
    return fetched, cached_hits, failed


def _make_record(
    tgt: PdfTarget,
    *,
    status: str,
    attempt: int,
    wall_s: float,
    error: Optional[str] = None,
    error_type: Optional[str] = None,
    http_status: Optional[int] = None,
    extractor: Optional[str] = None,
    chars: Optional[int] = None,
) -> PdfAttemptRecord:
    return PdfAttemptRecord(
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
    )


def _render_pdf_report(
    *,
    out_dir: Path,
    store: PdfStore,
    request_log: Optional[RequestLog],
    started: datetime,
    finished: datetime,
) -> Path:
    snap = store.snapshot()
    status_counts: Counter = Counter(
        r.get("status", "unknown") for r in snap.values()
    )
    extractor_counts: Counter = Counter(
        r.get("extractor") or "-" for r in snap.values()
    )
    by_doc_type: Counter = Counter(
        r.get("doc_type") or "-" for r in snap.values()
    )

    lines = [
        f"# PDF sweep — {out_dir.name}",
        "",
        f"- started:  {started.isoformat(timespec='seconds')}",
        f"- finished: {finished.isoformat(timespec='seconds')}",
        f"- elapsed:  {(finished - started).total_seconds():.1f}s",
        f"- targets:  {len(snap)}",
        "",
        "## Status",
        "",
        "| status | n |",
        "|--------|--:|",
    ]
    for s, n in sorted(status_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {s} | {n} |")
    lines += ["", "## Extractor", "", "| extractor | n |", "|-----------|--:|"]
    for e, n in sorted(extractor_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {e} | {n} |")
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
