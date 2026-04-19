"""Migrate the HTML cache from per-tab `.html.gz` files to per-case tar.gz.

Old layout:
    data/cache/html/<CLASSE>_<N>/
        detalhe.html.gz
        abaPartes.html.gz
        ...
        incidente.txt
        sessao_sessaoVirtual_<inc>.html.gz

New layout (one archive per case):
    data/cache/html/<CLASSE>_<N>.tar.gz
        members: {tab}.html, incidente.txt

The script is idempotent — it skips cases that already have a .tar.gz
sibling. It verifies each round-trip (every member readable through
`html_cache.read*`) before deleting the source directory.

Run with --dry-run first on a real backfill cache. --keep-dirs keeps
the source dirs around even after a successful migration (useful for
the first few thousand cases while you sanity-check the new layout).

Usage:
    PYTHONPATH=. uv run python scripts/migrate_html_cache_to_tar.py --dry-run
    PYTHONPATH=. uv run python scripts/migrate_html_cache_to_tar.py --classe HC --limit 100
    PYTHONPATH=. uv run python scripts/migrate_html_cache_to_tar.py --keep-dirs
"""

from __future__ import annotations

import argparse
import gzip
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Iterator, Optional

from src.utils import html_cache

CACHE_ROOT = Path("data/cache/html")
_DIR_NAME_RE = re.compile(r"^([A-Z]+)_(\d+)$")


def _iter_case_dirs(classe_filter: Optional[str]) -> Iterator[tuple[str, int, Path]]:
    for entry in sorted(CACHE_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        m = _DIR_NAME_RE.match(entry.name)
        if not m:
            continue
        classe, processo_str = m.group(1), m.group(2)
        if classe_filter and classe != classe_filter:
            continue
        yield classe, int(processo_str), entry


def _read_dir_entries(case_dir: Path) -> tuple[dict[str, str], Optional[int]]:
    tabs: dict[str, str] = {}
    incidente: Optional[int] = None
    for f in case_dir.iterdir():
        if f.name == "incidente.txt":
            text = f.read_text().strip()
            incidente = int(text) if text.isdigit() else None
        elif f.name.endswith(".html.gz"):
            tab = f.name.removesuffix(".html.gz")
            tabs[tab] = gzip.decompress(f.read_bytes()).decode("utf-8")
        elif f.name.endswith(".html"):
            tab = f.name.removesuffix(".html")
            tabs[tab] = f.read_text(encoding="utf-8")
    return tabs, incidente


def _verify_roundtrip(classe: str, processo: int, tabs: dict[str, str], incidente: int) -> None:
    got_incidente = html_cache.read_incidente(classe, processo)
    if got_incidente != incidente:
        raise AssertionError(
            f"{classe}/{processo}: incidente mismatch after write "
            f"(source={incidente}, tar={got_incidente})"
        )
    for tab, expected in tabs.items():
        got = html_cache.read(classe, processo, tab)
        if got != expected:
            raise AssertionError(
                f"{classe}/{processo}: tab {tab!r} mismatch "
                f"(source_len={len(expected)}, tar_len={0 if got is None else len(got)})"
            )


def _migrate_one(
    classe: str,
    processo: int,
    case_dir: Path,
    *,
    dry_run: bool,
    keep_dirs: bool,
) -> tuple[str, int, int]:
    """Return (status, source_bytes, archive_bytes). status ∈ {skip, ok, empty, err}."""
    archive_path = CACHE_ROOT / f"{classe}_{processo}.tar.gz"
    if archive_path.exists():
        return ("skip", 0, archive_path.stat().st_size)

    tabs, incidente = _read_dir_entries(case_dir)
    if incidente is None or not tabs:
        return ("empty", 0, 0)

    source_bytes = sum(f.stat().st_size for f in case_dir.iterdir() if f.is_file())

    if dry_run:
        return ("ok", source_bytes, 0)

    html_cache.write_case(classe, processo, tabs=tabs, incidente=incidente)
    _verify_roundtrip(classe, processo, tabs, incidente)
    archive_bytes = archive_path.stat().st_size

    if not keep_dirs:
        shutil.rmtree(case_dir)

    return ("ok", source_bytes, archive_bytes)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Inspect without writing or deleting.")
    parser.add_argument("--keep-dirs", action="store_true", help="Keep source dirs after writing the archive.")
    parser.add_argument("--classe", help="Filter by classe (e.g. HC, ADI).")
    parser.add_argument("--limit", type=int, help="Process at most N cases.")
    parser.add_argument("--progress-every", type=int, default=500, help="Print progress every N cases.")
    args = parser.parse_args(argv)

    t0 = time.monotonic()
    counters = {"ok": 0, "skip": 0, "empty": 0, "err": 0}
    source_total = 0
    archive_total = 0

    for i, (classe, processo, case_dir) in enumerate(_iter_case_dirs(args.classe)):
        if args.limit and i >= args.limit:
            break
        try:
            status, src, arc = _migrate_one(
                classe, processo, case_dir,
                dry_run=args.dry_run, keep_dirs=args.keep_dirs,
            )
        except Exception as e:
            counters["err"] += 1
            print(f"  ERR {classe}/{processo}: {e!r}", file=sys.stderr)
            continue
        counters[status] += 1
        source_total += src
        archive_total += arc
        if (i + 1) % args.progress_every == 0:
            print(
                f"  [{i+1}] ok={counters['ok']} skip={counters['skip']} "
                f"empty={counters['empty']} err={counters['err']}"
            )

    wall = time.monotonic() - t0
    print()
    print(f"Migration {'(DRY RUN) ' if args.dry_run else ''}finished in {wall:.1f}s")
    print(f"  ok={counters['ok']} skip={counters['skip']} empty={counters['empty']} err={counters['err']}")
    if source_total and archive_total:
        ratio = archive_total / source_total
        print(f"  source={source_total/1024**2:.1f}MB archives={archive_total/1024**2:.1f}MB "
              f"(ratio={ratio:.2f})")
    return 0 if counters["err"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
