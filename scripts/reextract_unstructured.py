"""Re-extract image-only PDFs via the Unstructured API.

OCR counterpart to `scripts/fetch_pdfs.py`: same filter flags
(``--classe / --impte-contains / --doc-types / --relator-contains``),
same target collection, but instead of the default pypdf path each
short-cached PDF is POSTed to the Unstructured SaaS API with
``strategy=hi_res``.

Routes through `src.sweeps.pdf_driver.run_pdf_sweep` so every attempt
is captured in `pdfs.state.json` / `pdfs.log.jsonl` / `pdfs.errors.jsonl`
under ``--out``. That gives `--resume`, `--retry-from`, circuit breaker,
and per-GET latency history for free.

Cache-monotonic: only overwrites ``data/cache/pdf/<sha1(url)>.txt.gz`` when
the new OCR extract is strictly longer than the prior cached text.
The per-attempt record uses ``extractor="unstructured_api"`` on
improvement and ``extractor="unchanged"`` otherwise, so the report
at `<out>/report.md` breaks down improved vs unchanged.

Usage:

    # Dry run — show what would be re-extracted.
    PYTHONPATH=. uv run python scripts/reextract_unstructured.py \\
        --out runs/active/$(date +%Y-%m-%d)-reextract \\
        --classe HC --dry-run

    # Famous-lawyer HC preset (matches fetch_pdfs.py's preset).
    PYTHONPATH=. uv run python scripts/reextract_unstructured.py \\
        --out runs/active/2026-04-17-famous-lawyers-ocr \\
        --classe HC \\
        --impte-contains "TORON,PIERPAOLO,PEDRO MACHADO DE ALMEIDA CASTRO,\\
ARRUDA BOTELHO,MARCELO LEONARDO,NILO BATISTA,VILARDI,PODVAL,\\
MUDROVITSCH,BADARO,DANIEL GERBER,TRACY JOSEPH REINALDET" \\
        --doc-types "DECISÃO MONOCRÁTICA,INTEIRO TEOR DO ACÓRDÃO,\\
MANIFESTAÇÃO DA PGR" \\
        --min-chars 5000

Optional env vars:
    UNSTRUCTURED_API_KEY   required to run (not needed for --dry-run)
    UNSTRUCTURED_API_URL   defaults to the SaaS general endpoint
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

from scripts._filters import add_filter_args, targets_from_args
from src.sweeps.pdf_driver import FetcherFn, run_pdf_sweep
from src.sweeps.pdf_targets import PdfTarget
from src.scraping.http_session import _http_get_with_retry
from src.utils import pdf_cache


DEFAULT_UNSTRUCTURED_URL = "https://api.unstructuredapp.io/general/v0/general"


def _concat_elements(elements: Any) -> str:
    """Join `text` fields of Unstructured elements in document order.

    Tolerant of malformed rows: missing `text`, non-dict entries, and
    whitespace-only strings are skipped.
    """
    if not elements:
        return ""
    pieces: list[str] = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        txt = (el.get("text") or "").strip()
        if txt:
            pieces.append(txt)
    return "\n".join(pieces).strip()


def _extract_with_unstructured(
    pdf_bytes: bytes,
    *,
    api_url: str,
    api_key: str,
    strategy: str = "hi_res",
    languages: tuple[str, ...] = ("por",),
    timeout: int = 300,
) -> tuple[Optional[str], list[dict[str, Any]]]:
    """POST PDF bytes to the Unstructured SaaS API.

    Returns `(joined_text, elements)`. The elements list is the raw
    API response — dicts with `type`, `text`, `metadata`, etc. —
    written to the parallel elements cache when accepted so downstream
    consumers can recover section titles, page numbers, and table
    structure that the flat text throws away.
    """
    headers = {
        "unstructured-api-key": api_key,
        "accept": "application/json",
    }
    files = {"files": ("doc.pdf", pdf_bytes, "application/pdf")}
    data: list[tuple[str, str]] = [("strategy", strategy)]
    for lg in languages:
        data.append(("languages", lg))
    r = requests.post(
        api_url, headers=headers, files=files, data=data, timeout=timeout
    )
    r.raise_for_status()
    elements = r.json() or []
    if not isinstance(elements, list):
        elements = []
    return _concat_elements(elements), elements


def _make_fetcher(
    *,
    api_url: str,
    api_key: str,
    strategy: str,
    old_len_by_url: dict[str, int],
) -> FetcherFn:
    """Build a FetcherFn suitable for `pdf_driver.run_pdf_sweep`.

    The closure captures the per-URL "prior length" map so the
    monotonic guard can compare without a fresh `pdf_cache.read`.
    """
    def fetcher(
        session: Any, target: PdfTarget, config: Any,
    ) -> tuple[Optional[str], Optional[str], str]:
        r = _http_get_with_retry(session, target.url, config=config, timeout=90)
        if not r.content.startswith(b"%PDF"):
            return (None, "unstructured_api", "unknown_type")

        new_text, new_elements = _extract_with_unstructured(
            r.content, api_url=api_url, api_key=api_key, strategy=strategy,
        )
        new_len = len(new_text or "")
        old_len = old_len_by_url.get(target.url, 0)
        old_text = pdf_cache.read(target.url) or ""

        if new_text and new_len > old_len:
            pdf_cache.write_elements(target.url, new_elements)
            return (new_text, "unstructured_api", "ok")

        # No improvement — preserve the prior cache, record as "unchanged".
        if old_text:
            return (old_text, "unchanged", "ok")
        return (None, "unstructured_api", "empty")

    return fetcher


def _classify_candidates(
    targets: list[PdfTarget], *, min_chars: int, force: bool,
) -> tuple[list[tuple[PdfTarget, int]], int, int]:
    """Split targets into (re-extract candidates, cached-ok, no-cache).

    Returns `(candidates, cached_ok, no_cache)` where each candidate
    is a `(target, old_len)` pair (0 if no prior cache).
    """
    candidates: list[tuple[PdfTarget, int]] = []
    cached_ok = 0
    no_cache = 0
    for t in targets:
        existing = pdf_cache.read(t.url)
        if existing is None:
            candidates.append((t, 0))
            no_cache += 1
        elif force or len(existing) < min_chars:
            candidates.append((t, len(existing)))
        else:
            cached_ok += 1
    return candidates, cached_ok, no_cache


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--out", required=True, type=Path,
        help="Output DIRECTORY for pdfs.state.json / pdfs.log.jsonl / "
             "pdfs.errors.jsonl / requests.db / report.md.",
    )
    add_filter_args(ap)
    ap.add_argument(
        "--min-chars", type=int, default=1000,
        help="re-extract cache entries shorter than this (default: 1000).",
    )
    ap.add_argument(
        "--throttle-sleep", type=float, default=2.0,
        help="seconds between successive targets (default: 2.0). Paces "
             "STF PDF downloads; the adaptive throttle still applies.",
    )
    ap.add_argument(
        "--strategy", default="hi_res",
        choices=["hi_res", "ocr_only", "fast", "auto"],
        help="Unstructured partition strategy (default: hi_res).",
    )
    ap.add_argument(
        "--limit", type=int, default=0,
        help="stop after N re-extractions (0 = no limit).",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="print candidate count + doc-type breakdown and exit.",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="re-extract even if cached length >= --min-chars.",
    )
    ap.add_argument(
        "--resume", action="store_true",
        help="skip URLs already recorded as status=ok in pdfs.state.json.",
    )
    ap.add_argument(
        "--retry-from", type=Path,
        help="path to a prior pdfs.errors.jsonl; re-run those URLs only.",
    )
    ap.add_argument(
        "--circuit-window", type=int, default=50,
        help="rolling window of recent targets the breaker watches (0 = off).",
    )
    ap.add_argument(
        "--circuit-threshold", type=float, default=0.8,
        help="error-like fraction that trips the breaker (default: 0.8).",
    )
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv()

    api_key = os.environ.get("UNSTRUCTURED_API_KEY")
    api_url = os.environ.get("UNSTRUCTURED_API_URL", DEFAULT_UNSTRUCTURED_URL)
    if not api_key and not args.dry_run:
        print(
            "ERROR: UNSTRUCTURED_API_KEY not set (checked env + .env).",
            file=sys.stderr,
        )
        return 2

    targets = targets_from_args(args)
    n_procs = len({t.processo_id for t in targets if t.processo_id is not None})
    print(f"target pool: {len(targets)} PDFs across {n_procs} processes")

    candidates, cached_ok, no_cache = _classify_candidates(
        targets, min_chars=args.min_chars, force=args.force,
    )

    print(f"  cached with >= {args.min_chars} chars: {cached_ok}")
    print(f"  re-extraction candidates:             {len(candidates)} "
          f"(of which {no_cache} have no cache entry at all)")
    by_type = Counter((t.doc_type or "-") for t, _ in candidates)
    for k, v in by_type.most_common():
        print(f"    {v:3d}  {k}")

    if args.dry_run:
        return 0

    if args.limit and len(candidates) > args.limit:
        candidates = candidates[: args.limit]
        print(f"  limited to first {args.limit}")

    candidate_targets = [t for t, _ in candidates]
    old_len_by_url = {t.url: old_len for t, old_len in candidates}

    fetcher = _make_fetcher(
        api_url=api_url, api_key=api_key or "",
        strategy=args.strategy,
        old_len_by_url=old_len_by_url,
    )

    fetched, cached_hits, failed = run_pdf_sweep(
        candidate_targets,
        out_dir=args.out,
        throttle_sleep=args.throttle_sleep,
        resume=args.resume,
        retry_from=args.retry_from,
        circuit_window=args.circuit_window,
        circuit_threshold=args.circuit_threshold,
        fetcher=fetcher,
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
