"""Re-extract image-only PDFs via an OCR provider.

Generic successor to the Unstructured-only variant: dispatches through
`src.scraping.ocr.extract_pdf` so the provider is a `--provider` flag
(default: `mistral`) rather than a hard-coded vendor.

Filters are the same as `scripts/fetch_pdfs.py` (``--classe /
--impte-contains / --doc-types / --relator-contains``). Routes through
`src.sweeps.pdf_driver.run_pdf_sweep` so every attempt lands in
`pdfs.state.json` / `pdfs.log.jsonl` / `pdfs.errors.jsonl` under ``--out``
with `--resume`, `--retry-from`, circuit breaker, and per-GET latency
for free.

Cache semantics:

- **Default** (`--force` not set): a PDF text entry is only overwritten
  when the new extraction is **strictly longer** than the prior cached
  text. A shorter result does not touch the cache; the attempt is
  recorded in the sweep log with `status=unchanged` so you can audit
  what was skipped.
- **`--force`**: unconditionally overwrites the text cache + elements
  cache + extractor sidecar with whatever the provider returns. Use
  this when you've chosen a higher-quality provider and want the new
  output regardless of length (e.g. Mistral markdown is often shorter
  than Unstructured plain text but more structured).

Usage:

    # Dry run — show what would be re-extracted, no API calls.
    PYTHONPATH=. uv run python scripts/reextract_unstructured.py \\
        --out runs/active/$(date +%Y-%m-%d)-reextract \\
        --classe HC --dry-run

    # Mistral (default), famous-lawyer HC preset:
    PYTHONPATH=. uv run python scripts/reextract_unstructured.py \\
        --out runs/active/2026-04-19-famous-lawyers-ocr \\
        --classe HC \\
        --impte-contains "TORON,PIERPAOLO,ARRUDA BOTELHO,MARCELO LEONARDO,NILO BATISTA,VILARDI,PODVAL,MUDROVITSCH,BADARO,DANIEL GERBER,TRACY JOSEPH REINALDET" \\
        --doc-types "DECISÃO MONOCRÁTICA,INTEIRO TEOR DO ACÓRDÃO,MANIFESTAÇÃO DA PGR" \\
        --min-chars 5000

    # Force-rewrite the cache with Unstructured hi_res output:
    PYTHONPATH=. uv run python scripts/reextract_unstructured.py \\
        --out runs/active/2026-04-19-force-unstructured \\
        --provider unstructured --strategy hi_res --force \\
        --classe HC --limit 100

Optional env vars (only the selected provider's key is required):
    MISTRAL_API_KEY        mistral (default)
    UNSTRUCTURED_API_KEY   unstructured
    CHANDRA_API_KEY        chandra
    UNSTRUCTURED_API_URL   overrides the SaaS general endpoint
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from scripts._filters import add_filter_args, targets_from_args
from src.scraping.http_session import _http_get_with_retry
from src.scraping.ocr import OCRConfig, extract_pdf
from src.sweeps.pdf_driver import FetcherFn, run_pdf_sweep
from src.sweeps.pdf_targets import PdfTarget
from src.utils import pdf_cache


PROVIDERS = ("mistral", "unstructured", "chandra")
DEFAULT_PROVIDER = "mistral"

# Env-var name per provider. Default is uppercase of the provider name
# plus `_API_KEY`. Unstructured also honors `UNSTRUCTURED_API_URL` as
# a URL override — the only provider that needs that today.
_API_KEY_ENV = {
    "mistral": "MISTRAL_API_KEY",
    "unstructured": "UNSTRUCTURED_API_KEY",
    "chandra": "CHANDRA_API_KEY",
}


def _concat_elements(elements: Any) -> str:
    """Join `text` fields of structured elements in document order.

    Kept as a thin local helper so the existing unit test stays valid
    — the canonical implementation is in `src.scraping.ocr.unstructured`.
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


def _build_ocr_config(
    *, provider: str, api_key: str, api_url: Optional[str],
    strategy: str, mode: str, batch: bool, timeout: int,
) -> OCRConfig:
    """Assemble an `OCRConfig` from CLI args, keeping provider-specific
    knobs inert for providers that don't use them."""
    return OCRConfig(
        provider=provider,
        api_key=api_key,
        api_url=api_url,
        languages=("por",),
        timeout=timeout,
        # provider-specific
        strategy=strategy,
        mode=mode,
        batch=batch,
    )


def _make_fetcher(
    *,
    ocr_config: OCRConfig,
    old_len_by_url: dict[str, int],
    force: bool,
) -> FetcherFn:
    """Build a FetcherFn suitable for `pdf_driver.run_pdf_sweep`.

    Monotonic guard: unless `force` is set, the cache is only overwritten
    when the new extraction's text is **strictly longer** than the prior
    cached text. Under `force`, the guard is disabled — any non-empty
    provider output replaces the cache (text + elements + extractor
    sidecar).
    """
    provider = ocr_config.provider

    def fetcher(
        session: Any, target: PdfTarget, config: Any,
    ) -> tuple[Optional[str], Optional[str], str]:
        r = _http_get_with_retry(session, target.url, config=config, timeout=90)
        if not r.content.startswith(b"%PDF"):
            return (None, provider, "unknown_type")

        result = extract_pdf(r.content, config=ocr_config)
        new_text = (result.text or "").strip()
        new_len = len(new_text)
        old_len = old_len_by_url.get(target.url, 0)

        # Monotonic guard (opt-out via --force).
        if not force and new_len <= old_len:
            # Returning text=None tells the driver to skip `pdf_cache.write`.
            # The attempt is still recorded in `pdfs.log.jsonl` via the sweep
            # store, with extractor=provider + status=unchanged so you can
            # audit which URLs the guard rejected.
            return (None, provider, "unchanged")

        if not new_text:
            return (None, provider, "empty")

        if result.elements:
            pdf_cache.write_elements(target.url, result.elements)
        return (new_text, provider, "ok")

    return fetcher


def _classify_candidates(
    targets: list[PdfTarget], *, min_chars: int, force: bool,
) -> tuple[list[tuple[PdfTarget, int]], int, int]:
    """Split targets into (re-extract candidates, cached-ok, no-cache).

    Returns `(candidates, cached_ok, no_cache)` where each candidate
    is a `(target, old_len)` pair (0 if no prior cache).

    When `force` is True, long-cached entries are included as
    candidates so they get re-OCR'd; without it, they short-circuit to
    `cached_ok`.
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
        "--provider", default=DEFAULT_PROVIDER, choices=PROVIDERS,
        help=f"OCR provider (default: {DEFAULT_PROVIDER}). "
             "Each provider reads its own API key env var "
             "(MISTRAL_API_KEY / UNSTRUCTURED_API_KEY / CHANDRA_API_KEY).",
    )
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
        help="Unstructured partition strategy (default: hi_res). "
             "Ignored for non-Unstructured providers.",
    )
    ap.add_argument(
        "--mode", default="accurate",
        choices=["accurate", "balanced", "fast"],
        help="Chandra mode (default: accurate). Ignored for non-Chandra "
             "providers.",
    )
    ap.add_argument(
        "--batch", action="store_true",
        help="Mistral batch API (~24h turnaround, ~50%% cheaper). Ignored "
             "for non-Mistral providers. NB: the current driver is sync — "
             "this flag is wired into OCRConfig for forward compat but not "
             "yet routed through the batch orchestrator.",
    )
    ap.add_argument(
        "--timeout", type=int, default=300,
        help="per-PDF OCR timeout in seconds (default: 300).",
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
        help="(1) include cache entries >= --min-chars as candidates AND "
             "(2) bypass the monotonic guard — unconditionally overwrite "
             "the cache with the new provider output when non-empty.",
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

    api_key_env = _API_KEY_ENV[args.provider]
    api_key = os.environ.get(api_key_env)
    api_url = (
        os.environ.get("UNSTRUCTURED_API_URL")
        if args.provider == "unstructured" else None
    )
    if not api_key and not args.dry_run:
        print(
            f"ERROR: {api_key_env} not set (checked env + .env) for "
            f"provider={args.provider!r}.",
            file=sys.stderr,
        )
        return 2

    targets = targets_from_args(args)
    n_procs = len({t.processo_id for t in targets if t.processo_id is not None})
    print(
        f"target pool: {len(targets)} PDFs across {n_procs} processes "
        f"· provider={args.provider} · force={args.force}"
    )

    candidates, cached_ok, no_cache = _classify_candidates(
        targets, min_chars=args.min_chars, force=args.force,
    )

    print(f"  cached with >= {args.min_chars} chars: {cached_ok}"
          + (" (ignored under --force)" if args.force else ""))
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

    ocr_config = _build_ocr_config(
        provider=args.provider,
        api_key=api_key or "",
        api_url=api_url,
        strategy=args.strategy,
        mode=args.mode,
        batch=args.batch,
        timeout=args.timeout,
    )

    fetcher = _make_fetcher(
        ocr_config=ocr_config,
        old_len_by_url=old_len_by_url,
        force=args.force,
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
