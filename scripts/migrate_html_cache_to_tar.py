"""Migrate legacy per-file-gz HTML cache dirs into per-case tar.gz.

Background
----------
`data/cache/html/` carries two generations side-by-side (see
`docs/current_progress.md § Operational hygiene`):

  (a) **tar-only** cases — `<classe>_<processo>.tar.gz` only. Current
      layout, written by `judex/utils/html_cache.py`. Untouched here.
  (b) **paired** cases — both a `.tar.gz` and a legacy
      `<classe>_<processo>/` dir exist. The tar is authoritative
      (`has_case()` reads it). If the tar is a content-superset of the
      dir in tab names, the dir is safe to delete.
  (c) **dir-only** cases — only the legacy dir exists. Invisible to
      `has_case()`. Rewritten here as `.tar.gz` from the gzipped tab
      files on disk (zero HTTP), then the dir is removed.

**Run this only when no `varrer-processos` sweep is live** — concurrent
case scrapes write to `<classe>_<processo>.tar.gz` and can race the
migration's "no tar → write tar" path.

Safety
------
- Writes go through `html_cache.write_case()`, which is atomic
  (tmp + `os.replace`).
- After a migrate write, the script reads every emitted tab back
  through the canonical `html_cache.read()` and verifies round-trip
  before removing the source dir.
- `--dry-run` classifies only — no writes, no deletes.

Usage
-----

    # Classify dirs into buckets (no writes).
    uv run python scripts/migrate_html_cache_to_tar.py --dry-run

    # Execute: migrate dir-only → tar.gz, delete paired dirs whose
    # tar is a content-superset. Parallel across cases.
    uv run python scripts/migrate_html_cache_to_tar.py --workers 2

    # Only run one of the two paths:
    uv run python scripts/migrate_html_cache_to_tar.py --only-migrate
    uv run python scripts/migrate_html_cache_to_tar.py --only-dedupe

Summary line at the end reports counts of migrated / deduped /
skipped_mismatch / error.
"""

from __future__ import annotations

import argparse
import gzip
import logging
import shutil
import sys
import tarfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from judex.utils import html_cache

CACHE_ROOT = Path("data/cache/html")

logger = logging.getLogger("migrate_html_cache_to_tar")


@dataclass(frozen=True)
class Case:
    classe: str
    processo: int
    dir_path: Path
    tar_path: Path


@dataclass
class Result:
    classe: str
    processo: int
    action: str
    detail: str = ""


def _parse_case_from_dir(dir_path: Path) -> Optional[Case]:
    name = dir_path.name
    classe, sep, rest = name.partition("_")
    if not sep or not classe or not rest:
        return None
    try:
        processo = int(rest)
    except ValueError:
        return None
    tar_path = CACHE_ROOT / f"{classe}_{processo}.tar.gz"
    return Case(classe=classe, processo=processo, dir_path=dir_path, tar_path=tar_path)


def _list_dir_tabs(dir_path: Path) -> dict[str, Path]:
    tabs: dict[str, Path] = {}
    for p in dir_path.iterdir():
        if p.is_dir():
            continue
        n = p.name
        if n.endswith(".html.gz"):
            tabs[n[: -len(".html.gz")]] = p
        elif n.endswith(".html"):
            tabs[n[: -len(".html")]] = p
    return tabs


def _read_html_tab(path: Path) -> str:
    if path.name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return f.read()
    return path.read_text(encoding="utf-8")


def _list_tar_tabs(tar_path: Path) -> set[str]:
    out: set[str] = set()
    with tarfile.open(tar_path, "r:gz") as tf:
        for name in tf.getnames():
            if name == "incidente.txt":
                continue
            if name.endswith(".html"):
                out.add(name[: -len(".html")])
    return out


def _read_incidente(dir_path: Path) -> Optional[int]:
    p = dir_path / "incidente.txt"
    if not p.exists():
        return None
    txt = p.read_text(encoding="utf-8").strip()
    return int(txt) if txt.isdigit() else None


def _process_case(
    case: Case,
    *,
    dry_run: bool,
    only_migrate: bool,
    only_dedupe: bool,
) -> Result:
    try:
        tar_exists = case.tar_path.exists()
        dir_tabs_map = _list_dir_tabs(case.dir_path)
        dir_tabs = set(dir_tabs_map.keys())
        if not dir_tabs:
            return Result(case.classe, case.processo, "error", "dir has no html members")

        if tar_exists:
            if only_migrate:
                return Result(case.classe, case.processo, "skipped_paired")
            tar_tabs = _list_tar_tabs(case.tar_path)
            missing = dir_tabs - tar_tabs
            if missing:
                return Result(
                    case.classe,
                    case.processo,
                    "skipped_mismatch",
                    f"tar missing {sorted(missing)}",
                )
            if not dry_run:
                shutil.rmtree(case.dir_path)
            return Result(
                case.classe,
                case.processo,
                "deduped",
                f"{len(dir_tabs)} dir tabs ⊆ tar",
            )

        if only_dedupe:
            return Result(case.classe, case.processo, "skipped_dir_only")

        incidente = _read_incidente(case.dir_path)
        if incidente is None:
            return Result(
                case.classe,
                case.processo,
                "error",
                "missing or non-integer incidente.txt",
            )

        tabs_text: dict[str, str] = {
            tab: _read_html_tab(path) for tab, path in dir_tabs_map.items()
        }

        if not dry_run:
            if case.tar_path.exists():
                return Result(
                    case.classe,
                    case.processo,
                    "skipped_race",
                    "tar appeared between classification and write",
                )
            html_cache.write_case(
                case.classe,
                case.processo,
                tabs=tabs_text,
                incidente=incidente,
            )
            for tab in dir_tabs:
                if html_cache.read(case.classe, case.processo, tab) is None:
                    return Result(
                        case.classe,
                        case.processo,
                        "error",
                        f"post-write read of {tab!r} returned None",
                    )
            shutil.rmtree(case.dir_path)
        return Result(
            case.classe,
            case.processo,
            "migrated",
            f"{len(dir_tabs)} tabs + incidente={incidente}",
        )
    except Exception as e:
        return Result(case.classe, case.processo, "error", f"{type(e).__name__}: {e}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--dry-run", action="store_true", help="Classify only; no writes or deletes")
    ap.add_argument("--workers", type=int, default=1, help="Parallel workers (default 1)")
    ap.add_argument(
        "--only-migrate",
        action="store_true",
        help="Skip paired dedupe; only migrate dir-only cases",
    )
    ap.add_argument(
        "--only-dedupe",
        action="store_true",
        help="Skip migration; only delete paired dirs whose tar is a superset",
    )
    ap.add_argument("--classe", default=None, help="Restrict to one classe (e.g. HC)")
    ap.add_argument("--limit", type=int, default=None, help="Stop after N cases (smoke-test)")
    args = ap.parse_args(argv)

    if args.only_migrate and args.only_dedupe:
        ap.error("--only-migrate and --only-dedupe are mutually exclusive")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not CACHE_ROOT.exists():
        logger.error("cache root %s does not exist", CACHE_ROOT)
        return 2

    cases: list[Case] = []
    for p in CACHE_ROOT.iterdir():
        if not p.is_dir():
            continue
        c = _parse_case_from_dir(p)
        if c is None:
            continue
        if args.classe and c.classe != args.classe:
            continue
        cases.append(c)
    if args.limit is not None:
        cases = cases[: args.limit]
    logger.info("Considering %d case dirs under %s", len(cases), CACHE_ROOT)

    t0 = time.time()
    counts: dict[str, int] = {}
    first_errors: list[Result] = []
    first_mismatches: list[Result] = []

    def _tally(r: Result) -> None:
        counts[r.action] = counts.get(r.action, 0) + 1
        if r.action == "error" and len(first_errors) < 10:
            first_errors.append(r)
        if r.action == "skipped_mismatch" and len(first_mismatches) < 10:
            first_mismatches.append(r)

    if args.workers <= 1:
        for c in cases:
            _tally(
                _process_case(
                    c,
                    dry_run=args.dry_run,
                    only_migrate=args.only_migrate,
                    only_dedupe=args.only_dedupe,
                )
            )
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = [
                ex.submit(
                    _process_case,
                    c,
                    dry_run=args.dry_run,
                    only_migrate=args.only_migrate,
                    only_dedupe=args.only_dedupe,
                )
                for c in cases
            ]
            for fut in as_completed(futs):
                _tally(fut.result())

    dt = time.time() - t0
    logger.info("Done in %.1fs. Counts: %s", dt, counts)
    if first_mismatches:
        logger.info("First mismatches (paired, tar lacks dir tabs — left intact):")
        for r in first_mismatches:
            logger.info("  %s_%d: %s", r.classe, r.processo, r.detail)
    if first_errors:
        logger.info("First errors:")
        for r in first_errors:
            logger.info("  %s_%d: %s", r.classe, r.processo, r.detail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
