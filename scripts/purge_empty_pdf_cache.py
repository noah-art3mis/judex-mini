"""One-shot cleanup: delete empty-body cache entries from `data/raw/pecas/`.

Pre-2026-05 the download driver wrote `gzip.compress(b'')` to disk and
called it `status=ok` whenever STF returned 200 OK with an empty body
(an edge-fronting glitch on sistemas.stf.jus.br during proxy / WAF
reset windows). The driver now routes empty bodies to
`status=empty_response` and *doesn't* write the cache file, but ~1,506
historical entries already exist on disk. They show up as `<sha1>.pdf.gz`
files that decompress to zero bytes — extractors flag them as
`status=unknown_type`, but they pollute glob counts, depress the
`_AVG_PDF_MB` anchor, and confuse cold-session triage.

This script walks `data/raw/pecas/*.pdf.gz`, decompresses each, and
deletes any whose body is empty. After the purge, the next
`baixar-pecas` sweep that targets these URLs (the source JSONs still
record them) will see `peca_cache.has_bytes(url) == False` and
re-download — most empty responses are transient and clear on retry.

Idempotent. Defaults to dry-run; pass ``--apply`` to delete.

Usage::

    uv run python scripts/purge_empty_pdf_cache.py             # report only
    uv run python scripts/purge_empty_pdf_cache.py --apply     # delete

The script prints the sha1s of deleted files so a follow-up sweep can
optionally feed them as a synthetic ``pdfs.errors.jsonl`` (one
``{"url": "..."}`` per line — but that requires the URL, not the
sha1, so the simpler path is to re-run ``baixar-pecas`` over the
year's CSV with ``--retomar`` and let the missing-bytes check
trigger the re-fetch).
"""

from __future__ import annotations

import argparse
import gzip
import sys
from pathlib import Path

PECAS_ROOT = Path("data/raw/pecas")


def _is_empty(gz_path: Path) -> bool:
    """True if the gzip decompresses to zero bytes."""
    with gzip.open(gz_path, "rb") as f:
        # 1-byte read is enough to detect "decompresses to nothing".
        return f.read(1) == b""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete. Without this flag, just report.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=PECAS_ROOT,
        help=f"Cache root to scan (default: {PECAS_ROOT}).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print every empty sha1 (default prints just first 10 + total).",
    )
    args = parser.parse_args()

    if not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2

    scanned = empty = deleted = 0
    empty_sha1s: list[str] = []

    for gz in args.root.glob("*.pdf.gz"):
        scanned += 1
        if not _is_empty(gz):
            continue
        empty += 1
        sha1 = gz.name.removesuffix(".pdf.gz")
        empty_sha1s.append(sha1)
        if args.apply:
            gz.unlink()
            deleted += 1

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"=== purge_empty_pdf_cache · {mode} · root={args.root} ===")
    print(f"  scanned: {scanned:>7}")
    print(f"  empty:   {empty:>7}  (would delete; pass --apply to do it)")
    if args.apply:
        print(f"  deleted: {deleted:>7}")

    if empty_sha1s:
        to_show = empty_sha1s if args.list else empty_sha1s[:10]
        print(f"\n  empty sha1s ({'all' if args.list else f'first {len(to_show)} of {len(empty_sha1s)}'}):")
        for sha1 in to_show:
            print(f"    {sha1}")
        if not args.list and len(empty_sha1s) > len(to_show):
            print(f"    … (--list to print all)")

    if not args.apply and empty:
        print("\n  re-run with --apply to delete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
