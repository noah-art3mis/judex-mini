"""Extract driver — the OCR/text half of the PDF pipeline.

Reads bytes from `data/cache/pdf/<sha1>.pdf.gz` (populated by
`baixar-pecas`), dispatches text extraction via
`src.scraping.ocr.extract_pdf` per `--provedor`, writes text +
sidecar + optional element list back to the same cache. Zero HTTP.

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
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from judex.scraping.ocr import ExtractResult, OCRConfig
from judex.scraping.ocr.dispatch import extract_pdf as _dispatch_extract
from judex.sweeps import shared as _shared
from judex.sweeps.peca_store import PecaAttemptRecord, PecaStore, load_retry_list
from judex.utils.pricing import estimate_ocr_cost
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
) -> tuple[int, int, int, int]:
    """Run a local-OCR extraction sweep.

    Returns `(extracted, cached_hits, no_bytes, failed)`.
    """
    out_dir = Path(out_dir)
    store = PecaStore(out_dir)

    if retry_from is not None:
        keep = set(load_retry_list(retry_from))
        targets = [t for t in targets if t.url in keep]

    if install_signal_handlers:
        _shared._reset_shutdown_for_tests()
        _shared.install_signal_handlers()

    if ocr_config is None:
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
            logging.warning(f"[{i}/{n}] {tgt.url}: no_bytes")
            return "no_bytes"

        # Sidecar-match skip (spec's truth table).
        sidecar = peca_cache.read_extractor(tgt.url)
        text_cached = peca_cache.read(tgt.url) is not None
        if sidecar == provedor and text_cached and not forcar:
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
                result = dispatch_fn(body, ocr_config)
                text = result.text
                elements = result.elements
                extractor_label = result.provider or provedor
            else:
                status = "unknown_type"
                error = "bytes are neither PDF nor RTF"
                error_type = "UnknownType"
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
            logging.info(
                f"[{i}/{n}] {tgt.url}: ok ({len(text)} chars, {extractor_label})"
            )
        elif status == "ok" and not text:
            status = "empty"
            counters.failed += 1
            error = error or "empty"
            error_type = error_type or "empty"
            logging.warning(f"[{i}/{n}] {tgt.url}: empty")
        else:
            counters.failed += 1
            logging.warning(
                f"[{i}/{n}] {tgt.url}: {status}"
                + (f" ({error})" if error else "")
            )

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
        print(
            f"  [progress] ok={counters.extracted} cached={counters.cached_hits} "
            f"no_bytes={counters.no_bytes} fail={counters.failed} · "
            f"{rate:.2f} tgt/s · eta {eta_s / 60:.1f} min",
            flush=True,
        )

    def is_already_done(tgt: PecaTarget) -> bool:
        return resume and store.already_ok(tgt.url)

    def on_resume_skip(_tgt: PecaTarget) -> None:
        counters.cached_hits += 1

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

    print(
        f"\nsummary: extracted={counters.extracted} cached={counters.cached_hits} "
        f"no_bytes={counters.no_bytes} failed={counters.failed}"
        + ("  (circuit tripped)" if tripped else ""),
        flush=True,
    )
    print(f"  {cost.summary_line()}")
    print(f"  state:  {store.state_path}")
    print(f"  log:    {store.log_path}")
    print(f"  errors: {errors_path}")
    print(f"  report: {report_path}")
    return (
        counters.extracted,
        counters.cached_hits,
        counters.no_bytes,
        counters.failed,
    )


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

    path = out_dir / "report.md"
    path.write_text("\n".join(lines) + "\n")
    return path
