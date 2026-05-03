"""Extract driver — the OCR/text half of the PDF pipeline.

Reads bytes from `data/raw/pecas/<sha1>.<ext>.gz` (populated by
`baixar-pecas`), dispatches text extraction via
`src.scraping.ocr.extract_pdf` per `--provedor`, writes text +
sidecar + optional element list to `data/derived/pecas-texto/`.
Zero HTTP.

Skip logic per target:

    --retomar + state=ok   → skip, no dispatcher call
    has_bytes == False     → status=no_bytes, skip (no dispatcher call)
    sidecar == provedor
      + not forcar         → skip, status=cached
    otherwise              → dispatch → write

RTF-prefixed bytes bypass the provider entirely and go through
`extract_rtf_text`; the cached sidecar gets tagged `extractor=rtf`
regardless of `--provedor`. Preserves parity with the prior
`_default_fetcher` behavior where RTF was auto-detected.
"""

from __future__ import annotations

import logging

from judex.utils.log_render import (
    compact_target_id,
    render_progress_line,
    render_target_line,
)
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from judex.scraping.ocr import ExtractResult, OCRConfig
from judex.scraping.ocr.dispatch import extract_pdf as _dispatch_extract
from judex.scraping.ocr.tesseract_fly import OutlierPdfError
from judex.sweeps import shared as _shared
from judex.sweeps.peca_store import PecaAttemptRecord, PecaStore, urls_for_replay
from judex.utils.cost import estimate_ocr_cost
from judex.sweeps.peca_targets import PecaTarget
from judex.utils import peca_cache
from judex.utils.peca_utils import extract_rtf_text


DispatcherFn = Callable[[bytes, OCRConfig], ExtractResult]
"""(pdf_bytes, ocr_config) -> ExtractResult. Production leaves this
None and gets the registered provider via `extract_pdf`; tests inject
a deterministic dispatcher.
"""


@dataclass
class _Counters:
    extracted: int = 0
    cached_hits: int = 0
    no_bytes: int = 0
    failed: int = 0
    outlier_skipped: int = 0


def _detect_bytes_type(body: bytes) -> str:
    prefix = body[:100]
    if prefix.startswith(b"%PDF"):
        return "pdf"
    if prefix.startswith(b"{\\rtf"):
        return "rtf"
    return "unknown"


def run_extract_sweep(
    targets: list[PecaTarget],
    *,
    out_dir: Path,
    provedor: str,
    ocr_config: Optional[OCRConfig] = None,
    forcar: bool = False,
    resume: bool = False,
    retry_from: Optional[Path] = None,
    progress_every: int = 25,
    install_signal_handlers: bool = True,
    dispatcher: Optional[DispatcherFn] = None,
    provider_router: Optional[Callable[[PecaTarget], str]] = None,
    paralelo: int = 1,
) -> tuple[int, int, int, int]:
    """Run a local-OCR extraction sweep.

    `provider_router`, when given, picks the provider per-target from
    its `doc_type`. The run-level `provedor` is still recorded as the
    sweep label (e.g. "auto") so the report shows what mode was used.
    Each target's ocr_config is built lazily inside `on_item` from the
    router-picked provider; the sidecar match check uses the per-target
    provider too, so a previously cached `tesseract` extract on
    an ACÓRDÃO is treated as a hit.

    `paralelo` (default 1) drives the per-target dispatch fanout. The
    sequential path (paralelo=1) uses ``iterate_with_guards`` unchanged
    — same circuit breaker, same shutdown gates, same progress cadence.
    Values > 1 spawn a ``ThreadPoolExecutor(max_workers=paralelo)`` and
    submit ``on_item`` calls in parallel; the breaker is disabled in
    parallel mode (would race across threads) and shutdown checks are
    coarser (between submission and result-collection cycles). Use
    paralelo > 1 when ``provedor`` is a thin HTTP client (tesseract_fly,
    tesseract_modal, mistral) where most wall is network-bound and the
    GIL releases on the C-extension request call. Local providers
    (pypdf, tesseract) are CPU-bound and gain no throughput from thread
    fanout — leave at 1.

    Returns `(extracted, cached_hits, no_bytes, failed)`.
    """
    out_dir = Path(out_dir)
    store = PecaStore(out_dir)

    if retry_from is not None:
        keep = set(urls_for_replay(retry_from, stage="extrair"))
        targets = [t for t in targets if t.url in keep]

    if install_signal_handlers:
        _shared._reset_shutdown_for_tests()
        _shared.install_signal_handlers()

    # Single-provider runs reuse one OCRConfig; auto-routed runs build one
    # per target inside on_item, so a fixed ocr_config wouldn't apply.
    if provider_router is None and ocr_config is None:
        ocr_config = OCRConfig(provider=provedor, api_key="")
    dispatch_fn: DispatcherFn = dispatcher or _dispatch_extract

    counters = _Counters()
    started = datetime.now(timezone.utc)
    print(
        f"=== pdf extract · provedor={provedor} · "
        f"{len(targets)} targets · out={out_dir} ===",
        flush=True,
    )

    def on_item(i: int, n: int, tgt: PecaTarget) -> str:
        if not peca_cache.has_bytes(tgt.url):
            counters.no_bytes += 1
            store.record(_make_record(
                tgt, status="no_bytes",
                wall_s=0.0,
                error="run baixar-pecas first",
                error_type="NoLocalBytes",
                attempt=store.attempt_count(tgt.url) + 1,
            ))
            print(render_target_line(
                n=i, total=n, status="no_bytes",
                identifier=compact_target_id(
                    tgt.url, classe=tgt.classe, processo_id=tgt.processo_id,
                ),
                detail="run baixar-pecas first",
            ), flush=True)
            return "no_bytes"

        # Resolve the per-target provider — router fork (`auto` mode) or
        # the run-level provedor for single-provider runs.
        target_provedor = (
            provider_router(tgt) if provider_router is not None else provedor
        )
        target_ocr_config = (
            ocr_config
            if ocr_config is not None
            else OCRConfig(provider=target_provedor, api_key="")
        )

        # Sidecar-match skip (spec's truth table).
        sidecar = peca_cache.read_extractor(tgt.url)
        text_cached = peca_cache.read(tgt.url) is not None
        if sidecar == target_provedor and text_cached and not forcar:
            counters.cached_hits += 1
            store.record(_make_record(
                tgt, status="cached", extractor=sidecar,
                chars=len(peca_cache.read(tgt.url) or ""),
                wall_s=0.0,
                attempt=store.attempt_count(tgt.url) + 1,
            ))
            return "ok"

        body = peca_cache.read_bytes(tgt.url)
        assert body is not None  # has_bytes returned True above

        t0 = time.perf_counter()
        status = "ok"
        error: Optional[str] = None
        error_type: Optional[str] = None
        text: Optional[str] = None
        extractor_label: Optional[str] = None
        elements: Optional[list[dict]] = None

        kind = _detect_bytes_type(body)
        try:
            if kind == "rtf":
                text = extract_rtf_text(body) or ""
                extractor_label = "rtf"
            elif kind == "pdf":
                result = dispatch_fn(body, target_ocr_config)
                text = result.text
                elements = result.elements
                extractor_label = result.provider or target_provedor
            else:
                status = "unknown_type"
                error = "bytes are neither PDF nor RTF"
                error_type = "UnknownType"
        except OutlierPdfError as e:
            # Pre-flight size check fired in the provider; this is a
            # deliberate skip with a manual-fix recommendation, not a
            # provider bug. Don't classify as error_type via the generic
            # path — the report renderer surfaces these separately.
            status = "outlier_skipped"
            error_type = "OutlierPdf"
            error = str(e)
        except Exception as e:
            status = "provider_error"
            etype, _hstatus, _ = _shared.classify_exception(e)
            error_type = etype
            error = f"{etype}: {e}"

        wall = time.perf_counter() - t0

        if status == "ok" and text:
            peca_cache.write(tgt.url, text, extractor=extractor_label)
            if elements is not None:
                peca_cache.write_elements(tgt.url, elements)
            counters.extracted += 1
            print(render_target_line(
                n=i, total=n, status="ok",
                identifier=compact_target_id(
                    tgt.url, classe=tgt.classe, processo_id=tgt.processo_id,
                ),
                detail=f"{extractor_label} · {len(text):,} chars",
            ), flush=True)
        elif status == "ok" and not text:
            status = "empty"
            counters.failed += 1
            error = error or "empty"
            error_type = error_type or "empty"
            print(render_target_line(
                n=i, total=n, status="empty",
                identifier=compact_target_id(
                    tgt.url, classe=tgt.classe, processo_id=tgt.processo_id,
                ),
                detail=f"{extractor_label or '-'} · 0 chars",
            ), flush=True)
        elif status == "outlier_skipped":
            counters.outlier_skipped += 1
            print(render_target_line(
                n=i, total=n, status="outlier",
                identifier=compact_target_id(
                    tgt.url, classe=tgt.classe, processo_id=tgt.processo_id,
                ),
                detail=f"{len(body)/1024/1024:.2f} MB · skip — re-run locally",
            ), flush=True)
        else:
            counters.failed += 1
            print(render_target_line(
                n=i, total=n, status=status,
                identifier=compact_target_id(
                    tgt.url, classe=tgt.classe, processo_id=tgt.processo_id,
                ),
                detail=(error or status),
            ), flush=True)

        store.record(_make_record(
            tgt, status=status, error=error, error_type=error_type,
            extractor=extractor_label,
            chars=len(text) if text else None,
            wall_s=round(wall, 3),
            attempt=store.attempt_count(tgt.url) + 1,
        ))
        return status

    def on_progress(i: int, n: int) -> None:
        _, rate, eta_s = _shared.elapsed_rate_eta(started, i, n)
        print(render_progress_line(
            n=i, total=n,
            counters={
                "ok": counters.extracted,
                "cached": counters.cached_hits,
                "no_bytes": counters.no_bytes,
                "fail": counters.failed,
            },
            rate_per_sec=rate, rate_label="tgt/s",
            eta_min=eta_s / 60,
        ), flush=True)

    def is_already_done(tgt: PecaTarget) -> bool:
        return resume and store.already_ok(tgt.url)

    def on_resume_skip(_tgt: PecaTarget) -> None:
        counters.cached_hits += 1

    if paralelo > 1:
        # Parallel HTTP-fanout path. on_item's store/cache writes need
        # serialization since multiple threads call it; wrap store.record
        # in a Lock. peca_cache.write is sha1-keyed so per-URL writes
        # land on disjoint paths — no cross-thread collision there.
        store_lock = threading.Lock()
        original_record = store.record

        def _locked_record(rec):
            with store_lock:
                return original_record(rec)

        store.record = _locked_record  # type: ignore[method-assign]
        tripped = _iterate_parallel(
            targets,
            on_item=on_item,
            should_resume_skip=is_already_done,
            on_skip=on_resume_skip,
            progress_every=progress_every,
            on_progress=on_progress,
            paralelo=paralelo,
        )
    else:
        tripped = _shared.iterate_with_guards(
            targets,
            on_item=on_item,
            should_resume_skip=is_already_done,
            on_skip=on_resume_skip,
            breaker=None,  # extract has no WAF; provider errors retry via --retentar-de
            error_statuses=("provider_error",),
            trip_noun="extracts",
            progress_every=progress_every,
            on_progress=on_progress,
            throttle_sleep=0.0,
        )

    finished = datetime.now(timezone.utc)
    store.compact()
    errors_path = store.write_errors_file()

    # Estimate pages from total chars extracted this sweep. The 2 000-char/page
    # heuristic is a rough OCR-industry average for text-dense docs — good
    # enough for "is this run $1 or $100" reasoning, not for billing. Override
    # the provider rate via OCR_PRICE_<PROVIDER>_USD_PER_1K_PAGES env vars.
    snap = store.snapshot()
    chars_this_sweep = sum(
        r.get("chars") or 0
        for r in snap.values()
        if r.get("status") == "ok"
    )
    pages_estimate = max(1, chars_this_sweep // 2000) if chars_this_sweep else 0
    cost = estimate_ocr_cost(provider=provedor, pages=pages_estimate)

    report_path = _render_extract_report(
        out_dir=out_dir, store=store, provedor=provedor,
        started=started, finished=finished, cost=cost,
    )

    status_counts = Counter(r.get("status", "unknown") for r in snap.values())
    print(
        f"\nsummary: extracted={counters.extracted} cached={counters.cached_hits} "
        f"no_bytes={counters.no_bytes} failed={counters.failed}"
        + (f" outlier_skipped={counters.outlier_skipped}"
           if counters.outlier_skipped else "")
        + ("  (circuit tripped)" if tripped else ""),
        flush=True,
    )
    fail_breakdown = " ".join(
        f"{s}={n}"
        for s, n in sorted(status_counts.items(), key=lambda kv: -kv[1])
        if s not in ("ok", "cached") and n > 0
    )
    if fail_breakdown:
        print(f"  by status: {fail_breakdown}")
    # Anomalies = non-transient extraction failures that won't fix themselves
    # on retry: bytes that aren't PDF/RTF (legacy cache pollution from before
    # the write-time guard), and provider crashes (often a real bug or quota
    # issue, not a network blip).
    anomaly_counts = {
        s: status_counts.get(s, 0)
        for s in ("unknown_type", "provider_error", "empty")
        if status_counts.get(s, 0) > 0
    }
    if anomaly_counts:
        print(
            "  ATTENTION — anomalies (NOT transient, investigate before replaying):"
            f" {' '.join(f'{s}={n}' for s, n in anomaly_counts.items())}"
        )
        print(f"     grep -E 'unknown_type|provider_error|\"status\":\"empty\"' {store.log_path}")
        print(f"     replay all errors: --retentar-de {errors_path}")
    print(f"  {cost.summary_line()}")
    print(f"  state:  {store.state_path}")
    print(f"  log:    {store.log_path}")
    print(f"  errors: {errors_path}")
    print(f"  report: {report_path}")
    if counters.outlier_skipped:
        outliers_csv = out_dir / "outliers.csv"
        print(
            f"\n  NOTE — {counters.outlier_skipped} outlier(s) deferred to "
            "local OCR. Re-run with:"
        )
        print(
            f"    uv run judex extrair-pecas --csv {outliers_csv} \\\n"
            f"        --saida {out_dir} --provedor tesseract --forcar"
        )
    return (
        counters.extracted,
        counters.cached_hits,
        counters.no_bytes,
        counters.failed,
    )


def _iterate_parallel(
    items: list[PecaTarget],
    *,
    on_item: Callable[[int, int, PecaTarget], Optional[str]],
    should_resume_skip: Callable[[PecaTarget], bool],
    on_skip: Callable[[PecaTarget], None],
    progress_every: int,
    on_progress: Callable[[int, int], None],
    paralelo: int,
) -> bool:
    """Parallel variant of ``shared.iterate_with_guards`` for HTTP-bound
    extract sweeps.

    Resume-skip happens sequentially in the submission pass — fast
    filesystem checks shouldn't compete for thread-pool slots. The
    actual ``on_item`` calls (which dispatch the HTTP OCR request) run
    in a ``ThreadPoolExecutor(max_workers=paralelo)``. Results are
    drained via ``as_completed``; ``shutdown_requested()`` is checked
    on each completion so a SIGTERM stops new submissions and lets
    in-flight calls finish.

    Returns False (no breaker integration in parallel mode — provider
    errors are retried via ``--retentar-de`` instead).
    """
    n = len(items)
    completed = 0

    with ThreadPoolExecutor(max_workers=paralelo) as pool:
        pending: dict = {}
        # Submission phase: walk targets sequentially, submit work for
        # those that need it, mark resume-skips inline.
        for i, item in enumerate(items, 1):
            if _shared.shutdown_requested():
                print(f"  stopping submission at {i}/{n}", flush=True)
                break
            if should_resume_skip(item):
                on_skip(item)
                continue
            fut = pool.submit(on_item, i, n, item)
            pending[fut] = i

        # Drain phase: collect results in completion order.
        for fut in as_completed(list(pending)):
            try:
                fut.result()
            except Exception as e:
                logging.exception("parallel on_item raised: %s", e)
            completed += 1
            if progress_every and completed % progress_every == 0:
                on_progress(completed, len(pending))
            if _shared.shutdown_requested():
                # Cancel anything still queued (in-flight calls finish).
                for f in pending:
                    if not f.done():
                        f.cancel()
                break

    return False


def _make_record(
    tgt: PecaTarget,
    *,
    status: str,
    attempt: int,
    wall_s: float,
    error: Optional[str] = None,
    error_type: Optional[str] = None,
    extractor: Optional[str] = None,
    chars: Optional[int] = None,
) -> PecaAttemptRecord:
    return PecaAttemptRecord(
        ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        url=tgt.url,
        attempt=attempt,
        wall_s=wall_s,
        status=status,
        error=error,
        error_type=error_type,
        extractor=extractor,
        chars=chars,
        processo_id=tgt.processo_id,
        classe=tgt.classe,
        doc_type=tgt.doc_type,
        context=tgt.context,
    )


def _render_extract_report(
    *,
    out_dir: Path,
    store: PecaStore,
    provedor: str,
    started: datetime,
    finished: datetime,
    cost: Optional[object] = None,
) -> Path:
    snap = store.snapshot()
    status_counts: Counter = Counter(
        r.get("status", "unknown") for r in snap.values()
    )
    extractor_counts: Counter = Counter(
        r.get("extractor") or "-" for r in snap.values()
    )

    lines = [
        f"# PDF extract sweep — {out_dir.name}",
        "",
        f"- started:  {started.isoformat(timespec='seconds')}",
        f"- finished: {finished.isoformat(timespec='seconds')}",
        f"- elapsed:  {(finished - started).total_seconds():.1f}s",
        f"- provedor: {provedor}",
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
    lines += ["", "## Extractor", "", "| extractor | n |", "|-----------|--:|"]
    for e, n in sorted(extractor_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {e} | {n} |")

    outliers = [
        (url, r) for url, r in snap.items()
        if r.get("status") == "outlier_skipped"
    ]
    if outliers:
        # Write a minimal classe,processo CSV that extrair-pecas accepts
        # via --csv. The user can then re-OCR locally with no extra
        # massaging — the suggested command below is copy-pasteable.
        csv_path = out_dir / "outliers.csv"
        with csv_path.open("w") as f:
            f.write("classe,processo\n")
            seen: set[tuple[str, int]] = set()
            for url, r in outliers:
                classe = r.get("classe") or ""
                processo = r.get("processo_id")
                if processo is None:
                    continue
                key = (classe, int(processo))
                if key in seen:
                    continue
                seen.add(key)
                f.write(f"{classe},{processo}\n")
        lines += [
            "",
            "## Outliers — manual handling needed",
            "",
            f"{len(outliers)} PDF(s) (across {len(seen)} case(s)) exceeded the "
            "cloud-OCR safety envelope. Re-extract locally — local Tesseract "
            "has no proxy/watchdog constraints:",
            "",
            "```bash",
            f"uv run judex extrair-pecas \\",
            f"    --csv {csv_path.name} --saida {out_dir} \\",
            "    --provedor tesseract --forcar",
            "```",
            "",
            "Outlier URLs (status=outlier_skipped in `pdfs.log.jsonl`):",
            "",
        ]
        for url, r in outliers:
            classe = r.get("classe") or "?"
            processo = r.get("processo_id") or "?"
            lines.append(f"- `{url}` — {classe} {processo}")

    path = out_dir / "report.md"
    path.write_text("\n".join(lines) + "\n")
    return path
