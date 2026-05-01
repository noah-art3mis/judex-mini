"""Audit `data/raw/pecas/` for byte-level integrity issues.

Runs the same validators we'd want at write time, but read-only over
the existing on-disk cache. Surfaces the prevalence of:

- **bad_magic** — file claims to be PDF/RTF by suffix but the bytes
  don't start with the right magic. Should be 0 after the
  `rename_rtf_cache.py` migration; non-zero means a regression.
- **truncated_pdf** — `%PDF` magic but no `%%EOF` in the last 1 KB.
  Spec-mandated trailer; missing it means STF cut the response
  mid-stream (or our retry logic stitched a partial body).
- **truncated_rtf** — `{\\rtf` magic but the file doesn't end with
  `}` (after rstrip). Real RTFs always close their root group.
- **empty** — gzip decompresses to zero bytes. Should be 0 after
  `purge_empty_pdf_cache.py`; non-zero means a regression.

Idempotent. Always read-only. Run periodically — or after any
download-driver change — to confirm no new bad entries leaked in.

Usage::

    uv run python scripts/audit_peca_cache.py             # report
    uv run python scripts/audit_peca_cache.py --list      # all sha1s

This script does NOT modify the cache. Acting on the findings is a
separate decision: bad entries can be deleted (they'll re-fetch on
the next sweep) or simply tolerated until the next replay cycle.
"""

from __future__ import annotations

import argparse
import gzip
import sys
from pathlib import Path
from typing import Iterable

PECAS_ROOT = Path("data/raw/pecas")
EOF_TAIL_BYTES = 1024
"""How far back in the file to look for `%%EOF`. Spec puts the trailer
within the last several hundred bytes; 1 KB is a safe upper bound that
also accommodates incremental-update markers (multiple `%%EOF`s,
consumers want any of them near the tail)."""


def _classify(body: bytes) -> str:
    """Return one of: ok_pdf, ok_rtf, bad_magic, truncated_pdf,
    truncated_rtf, empty.
    """
    if not body:
        return "empty"
    prefix = body[:8]
    if prefix.startswith(b"%PDF"):
        if b"%%EOF" not in body[-EOF_TAIL_BYTES:]:
            return "truncated_pdf"
        return "ok_pdf"
    if prefix.startswith(b"{\\rtf"):
        if not body.rstrip().endswith(b"}"):
            return "truncated_rtf"
        return "ok_rtf"
    return "bad_magic"


def _scan(paths: Iterable[Path]) -> dict[str, list[str]]:
    """Walk paths, return {classification: [sha1, ...]}."""
    buckets: dict[str, list[str]] = {}
    for p in paths:
        try:
            body = gzip.decompress(p.read_bytes())
        except Exception as e:
            buckets.setdefault("gzip_error", []).append(f"{p.name}: {e}")
            continue
        kind = _classify(body)
        sha1 = p.name.split(".", 1)[0]
        buckets.setdefault(kind, []).append(sha1)
    return buckets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=PECAS_ROOT,
        help=f"Cache root to scan (default: {PECAS_ROOT}).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print every offending sha1 (default prints first 10 per bucket).",
    )
    args = parser.parse_args()

    if not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2

    pdfs = sorted(args.root.glob("*.pdf.gz"))
    rtfs = sorted(args.root.glob("*.rtf.gz"))
    print(f"=== audit_peca_cache · root={args.root} ===")
    print(f"  .pdf.gz files: {len(pdfs):>7}")
    print(f"  .rtf.gz files: {len(rtfs):>7}")

    buckets = _scan(pdfs + rtfs)
    print()
    print("  classification:")
    order = (
        "ok_pdf",
        "ok_rtf",
        "truncated_pdf",
        "truncated_rtf",
        "bad_magic",
        "empty",
        "gzip_error",
    )
    for kind in order:
        n = len(buckets.get(kind, []))
        if n:
            print(f"    {kind:<14} {n:>7}")
    # Print any unexpected bucket too.
    for kind, members in buckets.items():
        if kind not in order:
            print(f"    {kind:<14} {len(members):>7}")

    issue_kinds = ("truncated_pdf", "truncated_rtf", "bad_magic", "empty", "gzip_error")
    total_issues = sum(len(buckets.get(k, [])) for k in issue_kinds)

    if total_issues == 0:
        print("\n  no integrity issues found.")
        return 0

    print(f"\n  {total_issues} entries need attention. Sample:")
    for kind in issue_kinds:
        members = buckets.get(kind, [])
        if not members:
            continue
        to_show = members if args.list else members[:10]
        print(f"\n  ## {kind} ({len(members)})")
        for s in to_show:
            print(f"    {s}")
        if not args.list and len(members) > len(to_show):
            print(f"    … (--list to print all)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
