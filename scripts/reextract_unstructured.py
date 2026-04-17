"""Re-extract image-only famous-lawyer HC PDFs via the Unstructured API.

Context. `analysis/famous_lawyers_profile.md` notes that 78/108 of the
substantive PDFs fetched for the marquee criminal-bar HC corpus are
image-only scans. pypdf's `extract_text` only returns header/footer
from those, so the on-disk `.cache/pdf/<sha1>.txt.gz` entries are
short and useless for downstream text analysis.

This script:

1. Rebuilds the same famous-lawyer PDF target set used by the original
   `fetch_famous_lawyer_pdfs.py` / `fetch_pdfs.py` preset.
2. Flags cache entries with length < --min-chars (or no entry at all)
   as re-extraction candidates.
3. Re-downloads each candidate PDF via the STF-aware scraper session
   (WAF-aware retries / pacing) and POSTs the bytes to the Unstructured
   SaaS API with `strategy=hi_res` (OCR).
4. If the Unstructured extract is longer than what was cached,
   overwrites the cache entry.

Usage:

    # Show what would be re-extracted (no network, no API spend).
    PYTHONPATH=. uv run python scripts/reextract_unstructured.py --dry-run

    # Actually re-extract (requires UNSTRUCTURED_API_KEY in .env).
    PYTHONPATH=. uv run python scripts/reextract_unstructured.py \\
        --min-chars 1000 --throttle-sleep 2.0

Optional env vars:
    UNSTRUCTURED_API_KEY   required to run (not needed for --dry-run)
    UNSTRUCTURED_API_URL   defaults to https://api.unstructuredapp.io/general/v0/general
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

from src.config import ScraperConfig
from src.pdf_targets import collect_pdf_targets
from src.scraper_http import _http_get_with_retry, new_session
from src.utils import pdf_cache
from src.utils.adaptive_throttle import AdaptiveThrottle


FAMOUS_NEEDLES: list[str] = [
    "TORON",
    "PIERPAOLO",
    "PEDRO MACHADO DE ALMEIDA CASTRO",
    "ARRUDA BOTELHO",
    "MARCELO LEONARDO",
    "NILO BATISTA",
    "VILARDI",
    "PODVAL",
    "MUDROVITSCH",
    "BADARO",
    "DANIEL GERBER",
    "TRACY JOSEPH REINALDET",
]

DOC_TYPES: list[str] = [
    "DECISÃO MONOCRÁTICA",
    "INTEIRO TEOR DO ACÓRDÃO",
    "MANIFESTAÇÃO DA PGR",
    "DESPACHO",
]

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

    roots = [Path("output"), Path("output/sample")]
    targets = collect_pdf_targets(
        roots,
        classe="HC",
        impte_contains=FAMOUS_NEEDLES,
        doc_types=DOC_TYPES,
    )
    n_hcs = len({t.processo_id for t in targets if t.processo_id is not None})
    print(f"target pool: {len(targets)} PDFs across {n_hcs} HCs")

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
            prefix = f"[{i}/{len(candidates)}] HC {t.processo_id} {t.doc_type}"
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
