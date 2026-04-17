"""Re-extract image-only PDFs via the Unstructured API.

Generic counterpart to `scripts/fetch_pdfs.py`: same filter flags
(``--classe / --impte-contains / --doc-types / --relator-contains``),
same target collection, but instead of the normal pypdf path this
script POSTs each short-cached PDF to the Unstructured SaaS API
with ``strategy=hi_res`` (OCR).

Cache-monotonic: only overwrites ``.cache/pdf/<sha1(url)>.txt.gz``
when the new extract is longer than the old. Safe to re-run; the
cache only ever improves.

Usage:

    # Dry run — show what would be re-extracted.
    PYTHONPATH=. uv run python scripts/reextract_unstructured.py \\
        --classe HC --dry-run

    # Famous-lawyer HC preset (matches fetch_pdfs.py's preset).
    PYTHONPATH=. uv run python scripts/reextract_unstructured.py \\
        --classe HC \\
        --impte-contains "TORON,PIERPAOLO,PEDRO MACHADO DE ALMEIDA CASTRO,\\
ARRUDA BOTELHO,MARCELO LEONARDO,NILO BATISTA,VILARDI,PODVAL,\\
MUDROVITSCH,BADARO,DANIEL GERBER,TRACY JOSEPH REINALDET" \\
        --doc-types "DECISÃO MONOCRÁTICA,INTEIRO TEOR DO ACÓRDÃO,\\
MANIFESTAÇÃO DA PGR" \\
        --min-chars 5000

    # Re-OCR Fachin's acórdãos specifically.
    PYTHONPATH=. uv run python scripts/reextract_unstructured.py \\
        --classe HC --relator-contains FACHIN \\
        --doc-types "INTEIRO TEOR DO ACÓRDÃO"

Optional env vars:
    UNSTRUCTURED_API_KEY   required to run (not needed for --dry-run)
    UNSTRUCTURED_API_URL   defaults to the SaaS general endpoint

Known gaps (pre-Phase-A debt):

- **Does not route through `src/pdf_driver.run_pdf_sweep`.** The
  loop below is inlined; `PdfStore` / `pdfs.state.json` /
  `pdfs.log.jsonl` / `pdfs.errors.jsonl` / `requests.db` are NOT
  produced. Only stdout logging + the URL-keyed `.cache/pdf/*.txt.gz`
  cache. Consequences: no `--resume`, no `--retry-from`, no circuit
  breaker, no per-GET latency data. Fix = write a `FetcherFn` that
  does the POST+cache.write and pass it as `pdf_driver.run_pdf_sweep`'s
  `fetcher=` kwarg.
- **Cache overwrite is monotonic-by-length but non-archival.** The
  pypdf extract is discarded when OCR wins. If OCR ever writes
  garbage that happens to be longer than the real extract, we lose
  the real extract. Mitigation after Phase-A routing: the prior
  attempt survives in `pdfs.log.jsonl` even after cache overwrite.
- **`--api-sleep` has no measured rationale.** Unstructured's
  `hi_res` OCR is self-paced by response latency (2–10s per call).
  The 1s sleep on top is padding atop a naturally paced call;
  drop to 0 on next run if you want to verify.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

from scripts._filters import add_filter_args, targets_from_args
from src.config import ScraperConfig
from src.scraper_http import _http_get_with_retry, new_session
from src.utils import pdf_cache
from src.utils.adaptive_throttle import AdaptiveThrottle


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
) -> Optional[str]:
    """POST PDF bytes to the Unstructured SaaS API, return joined text."""
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
    return _concat_elements(r.json())


def _build_session_and_config(throttle_sleep: float) -> tuple[Any, ScraperConfig]:
    session = new_session()
    throttle = AdaptiveThrottle(
        target_concurrency=1.0,
        start_delay=throttle_sleep,
        min_delay=throttle_sleep,
        max_delay=max(throttle_sleep * 10, 30.0),
    )
    return session, ScraperConfig(throttle=throttle)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_filter_args(ap)
    ap.add_argument(
        "--min-chars", type=int, default=1000,
        help="re-extract cache entries shorter than this (default: 1000).",
    )
    ap.add_argument(
        "--throttle-sleep", type=float, default=2.0,
        help="seconds between STF portal PDF downloads (default: 2.0).",
    )
    ap.add_argument(
        "--api-sleep", type=float, default=1.0,
        help="seconds between successive Unstructured API calls (default: 1.0).",
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

    candidates: list[tuple[Any, int]] = []
    cached_ok = 0
    no_cache = 0
    for t in targets:
        existing = pdf_cache.read(t.url)
        if existing is None:
            candidates.append((t, 0))
            no_cache += 1
        elif args.force or len(existing) < args.min_chars:
            candidates.append((t, len(existing)))
        else:
            cached_ok += 1

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

    session, config = _build_session_and_config(args.throttle_sleep)

    improved = 0
    unchanged = 0
    failed = 0
    try:
        for i, (t, old_len) in enumerate(candidates, 1):
            prefix = f"[{i}/{len(candidates)}] {t.classe} {t.processo_id} {t.doc_type}"
            try:
                r = _http_get_with_retry(
                    session, t.url, config=config, timeout=90,
                )
                pdf_bytes = r.content
            except Exception as e:
                logging.warning(f"{prefix}: download FAIL {e}")
                failed += 1
                continue

            if not pdf_bytes.startswith(b"%PDF"):
                logging.warning(
                    f"{prefix}: not a PDF (first bytes: {pdf_bytes[:8]!r})"
                )
                failed += 1
                continue

            try:
                new_text = _extract_with_unstructured(
                    pdf_bytes,
                    api_url=api_url, api_key=api_key,
                    strategy=args.strategy,
                )
            except requests.HTTPError as e:
                status = getattr(e.response, "status_code", "?")
                logging.warning(f"{prefix}: unstructured FAIL http {status}")
                failed += 1
                continue
            except Exception as e:
                logging.warning(f"{prefix}: unstructured FAIL {e}")
                failed += 1
                continue

            new_len = len(new_text or "")
            if new_text and new_len > old_len:
                pdf_cache.write(t.url, new_text)
                improved += 1
                logging.info(
                    f"{prefix}: ok (old {old_len} → new {new_len} chars)"
                )
            else:
                unchanged += 1
                logging.info(
                    f"{prefix}: no improvement (old {old_len}, new {new_len})"
                )

            if args.api_sleep and i < len(candidates):
                time.sleep(args.api_sleep)
    finally:
        session.close()

    print(f"\nsummary: improved={improved} unchanged={unchanged} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
