"""Generate a (classe, processo) CSV for one HC year.

Two modes:

- **Gap mode** (default): exclude pids already on disk under
  `data/cases/HC/` and (optionally) pids confirmed dead in
  `data/dead_ids/HC.txt`. Output covers only uncaptured pids.
- **Full-range mode** (`--full-range` / `include_captured=True`):
  exclude only confirmed deads. Output covers every pid in the
  year's range — used when re-scraping on-disk cases to pick up
  a wider HTML surface (e.g. v8+DJe content path on top of
  cases that are already structurally v8).

Output is descending order — ready to feed directly to
`scripts/shard_csv.py` + `scripts/run_sweep.py`.

Usage:

    uv run python scripts/generate_hc_year_gap_csv.py \\
        --year 2026 --out tests/sweep/hc_2026_gap.csv

    # Exclude dead IDs aggregated from past sweeps
    uv run python scripts/generate_hc_year_gap_csv.py \\
        --year 2026 --out /tmp/hc_2026_gap.csv \\
        --dead-ids data/dead_ids/HC.txt

    # Full-range re-scrape (keep on-disk pids; still drop deads)
    uv run python scripts/generate_hc_year_gap_csv.py \\
        --year 2025 --out /tmp/hc_2025_full.csv \\
        --dead-ids data/dead_ids/HC.txt --full-range
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Optional

from judex.utils.dead_ids import load_dead_ids
from judex.utils.hc_calendar import year_to_id_range


def captured_ids(cases_dir: Path) -> set[int]:
    """Return the set of HC processo_ids already on disk under cases_dir.

    Writer convention: `judex-mini_HC_<lo>-<hi>.json` where lo == hi for
    single-record chunks (current producer) or lo < hi for range-exports
    (legacy). Both are accepted here.
    """
    out: set[int] = set()
    for f in cases_dir.glob("judex-mini_HC_*.json"):
        stem = f.stem.replace("judex-mini_HC_", "", 1)
        if "-" not in stem:
            continue
        lo_s, hi_s = stem.split("-", 1)
        try:
            lo, hi = int(lo_s), int(hi_s)
        except ValueError:
            continue
        if lo > hi:
            continue
        out.update(range(lo, hi + 1))
    return out


def write_gap_csv(
    year: int,
    out_path: Path,
    cases_dir: Path,
    dead_ids_path: Optional[Path] = None,
    include_captured: bool = False,
) -> int:
    lo, hi = year_to_id_range(year)
    have = captured_ids(cases_dir)
    dead = load_dead_ids(dead_ids_path) if dead_ids_path else set()
    rows = [
        n for n in range(hi, lo - 1, -1)
        if (include_captured or n not in have) and n not in dead
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["classe", "processo"])
        for n in rows:
            w.writerow(["HC", n])

    dead_in_range = sum(1 for n in range(lo, hi + 1) if n in dead)
    have_in_range = sum(1 for n in range(lo, hi + 1) if n in have)
    mode = "full" if include_captured else "gap"
    print(
        f"year={year} range={lo}..{hi} width={hi - lo + 1} "
        f"have={have_in_range} dead={dead_in_range} "
        f"{mode}={len(rows)} → {out_path}"
    )
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cases-dir", type=Path, default=Path("data/cases/HC"))
    ap.add_argument(
        "--dead-ids", type=Path, default=None,
        help="Optional path to a dead-ID file (one pid per line) — IDs "
             "listed there are excluded from the output. Typical: "
             "data/dead_ids/HC.txt, produced by "
             "scripts/aggregate_dead_ids.py.",
    )
    ap.add_argument(
        "--full-range", action="store_true",
        help="Keep pids that are already on disk (only exclude confirmed "
             "deads). Used for full-year re-scrape sweeps where existing "
             "cases need to be refreshed against a wider extractor "
             "surface (e.g. v8+DJe on top of structurally-v8-but-content-"
             "stale files).",
    )
    args = ap.parse_args()
    write_gap_csv(
        args.year,
        args.out,
        args.cases_dir,
        dead_ids_path=args.dead_ids,
        include_captured=args.full_range,
    )


if __name__ == "__main__":
    main()
