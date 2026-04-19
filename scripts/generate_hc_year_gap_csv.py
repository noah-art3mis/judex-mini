"""Generate a (classe, processo) CSV for one HC year, filtering out IDs
already on disk under `data/cases/HC/`.

Used by the year-priority 4-shard backfill (see
`docs/hc-backfill-extension-plan.md`). The output CSV contains only
uncaptured HC processo_ids in descending order — ready to feed directly
to `scripts/shard_csv.py` + `scripts/run_sweep.py`.

Usage:

    PYTHONPATH=. uv run python scripts/generate_hc_year_gap_csv.py \\
        --year 2026 --out tests/sweep/hc_2026_gap.csv

    # Override the captures directory (default: data/cases/HC)
    PYTHONPATH=. uv run python scripts/generate_hc_year_gap_csv.py \\
        --year 2025 --out /tmp/hc_2025_gap.csv --cases-dir data/cases/HC
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

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


def write_gap_csv(year: int, out_path: Path, cases_dir: Path) -> int:
    lo, hi = year_to_id_range(year)
    have = captured_ids(cases_dir)
    gap = [n for n in range(hi, lo - 1, -1) if n not in have]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["classe", "processo"])
        for n in gap:
            w.writerow(["HC", n])

    print(
        f"year={year} range={lo}..{hi} width={hi - lo + 1} "
        f"have={sum(1 for n in range(lo, hi + 1) if n in have)} "
        f"gap={len(gap)} → {out_path}"
    )
    return len(gap)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cases-dir", type=Path, default=Path("data/cases/HC"))
    args = ap.parse_args()
    write_gap_csv(args.year, args.out, args.cases_dir)


if __name__ == "__main__":
    main()
