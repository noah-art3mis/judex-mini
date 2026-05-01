"""One-shot migration: rename `.pdf.gz` cache entries that are actually RTF.

Pre-2026-05 the bytes cache hard-coded `<sha1>.pdf.gz` for every payload,
so DJe surface-3 URLs (which serve `{\\rtf...` bytes) landed in `.pdf.gz`
files whose suffix lied. `peca_cache.write_bytes` now picks the
extension from the payload's magic bytes, but pre-existing cache
entries still need renaming. This script does that, idempotently.

Reads every `data/raw/pecas/*.pdf.gz`, decompresses the first 16 bytes,
and:

- `%PDF` prefix → leave alone (correctly named).
- `{\\rtf` prefix → `os.replace` to `<sha1>.rtf.gz`.
- anything else → log the sha1 and the prefix; leave on disk.

`os.replace` is atomic on POSIX, so re-running the script after a
partial run only finishes work, never duplicates or corrupts.

Defaults to dry-run; pass ``--apply`` to actually rename. Run from the
repo root::

    uv run python scripts/rename_rtf_cache.py            # report only
    uv run python scripts/rename_rtf_cache.py --apply    # do it
"""

from __future__ import annotations

import argparse
import gzip
import os
import sys
from pathlib import Path

PECAS_ROOT = Path("data/raw/pecas")


def _sniff(gz_path: Path) -> str:
    """Return 'pdf', 'rtf', or 'unknown' from the gzip's first 16 bytes."""
    with gzip.open(gz_path, "rb") as f:
        prefix = f.read(16)
    if prefix.startswith(b"%PDF"):
        return "pdf"
    if prefix.startswith(b"{\\rtf"):
        return "rtf"
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually rename. Without this flag, just report.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=PECAS_ROOT,
        help=f"Cache root to scan (default: {PECAS_ROOT}).",
    )
    args = parser.parse_args()

    if not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2

    scanned = renamed = unchanged = unknown = 0
    unknown_samples: list[tuple[str, bytes]] = []

    for gz in args.root.glob("*.pdf.gz"):
        scanned += 1
        kind = _sniff(gz)
        if kind == "pdf":
            unchanged += 1
            continue
        if kind == "rtf":
            target = gz.with_name(gz.name.replace(".pdf.gz", ".rtf.gz"))
            if args.apply:
                os.replace(gz, target)
            renamed += 1
            continue
        unknown += 1
        if len(unknown_samples) < 10:
            with gzip.open(gz, "rb") as f:
                unknown_samples.append((gz.stem, f.read(32)))

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"=== rename_rtf_cache · {mode} · root={args.root} ===")
    print(f"  scanned:   {scanned:>7}")
    print(f"  unchanged: {unchanged:>7}  (already correctly named .pdf.gz)")
    print(f"  renamed:   {renamed:>7}  (.pdf.gz → .rtf.gz)")
    print(f"  unknown:   {unknown:>7}  (neither %PDF nor {{\\rtf — left alone)")
    if unknown_samples:
        print("\n  unknown samples (sha1 → first 32 bytes):")
        for sha1, prefix in unknown_samples:
            print(f"    {sha1}  {prefix!r}")
    if not args.apply and renamed:
        print("\n  re-run with --apply to perform the rename.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
