"""One-shot postprocessor for the peça-text cache.

Walks ``data/derived/pecas-texto/*.txt.gz``, applies
``src.scraping.ocr.cleanup.clean_pdf_text``, and atomically rewrites
each file. Idempotent — re-running is a no-op on already-clean texts.

Usage:

    # Clean the whole cache (default path):
    uv run python scripts/clean_pdf_text.py

    # Preview the fix rate without touching any file:
    uv run python scripts/clean_pdf_text.py --dry-run

    # Restrict to a subset (e.g. only files you just extracted):
    uv run python scripts/clean_pdf_text.py --cache-dir data/derived/pecas-texto

The script reports: (files scanned, files changed, total before/after
byte delta). Changed files get ``tempfile → os.replace`` semantics so
interruption cannot leave a half-written ``.txt.gz`` on disk.
"""

from __future__ import annotations

import argparse
import gzip
import sys
from pathlib import Path

from judex.scraping.ocr.cleanup import clean_pdf_text


def _clean_one(path: Path, *, dry_run: bool) -> tuple[bool, int, int]:
    """Clean a single .txt.gz in place. Returns (changed, before_len, after_len)."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        before = f.read()
    after = clean_pdf_text(before)
    if after == before:
        return False, len(before), len(after)
    if not dry_run:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            f.write(after)
        tmp.replace(path)
    return True, len(before), len(after)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache-dir", type=Path, default=Path("data/derived/pecas-texto"),
                    help="Where .txt.gz files live (default: data/derived/pecas-texto).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Scan + compute diffs but don't rewrite any file.")
    ap.add_argument("--progress-every", type=int, default=2000,
                    help="Print a progress line every N files.")
    args = ap.parse_args(argv)

    if not args.cache_dir.is_dir():
        print(f"error: --cache-dir {args.cache_dir} not a directory", file=sys.stderr)
        return 2

    files = sorted(args.cache_dir.glob("*.txt.gz"))
    print(f"=== clean_pdf_text · {len(files)} file(s) in {args.cache_dir} "
          f"{'(dry-run)' if args.dry_run else ''} ===", flush=True)

    changed = 0
    before_total = 0
    after_total = 0
    for i, p in enumerate(files, 1):
        c, bl, al = _clean_one(p, dry_run=args.dry_run)
        before_total += bl
        after_total += al
        if c:
            changed += 1
        if args.progress_every and i % args.progress_every == 0:
            print(
                f"  [{i}/{len(files)}] changed={changed} "
                f"delta={after_total - before_total:+d} chars",
                flush=True,
            )

    delta = after_total - before_total
    pct = 100 * changed / len(files) if files else 0
    print(
        f"\nsummary: files={len(files)}  changed={changed} ({pct:.1f}%)  "
        f"chars_before={before_total:,}  chars_after={after_total:,}  "
        f"delta={delta:+,}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
