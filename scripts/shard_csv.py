"""Split a (classe, processo) sweep CSV into N disjoint range-partitioned shards.

Range-partitioning (not round-robin) is chosen on purpose: it preserves
HC descending order within each shard, so "shard i is currently at HC X"
reasoning stays intuitive, and it gives each shard contiguous HTML-cache
locality if the same filesystem page is re-read (not critical but
pleasant).

Usage:

    uv run python scripts/shard_csv.py \\
        --csv tests/sweep/hc_all_desc.csv \\
        --shards 4 \\
        --out-dir tests/sweep/shards/

Writes `<out-dir>/<stem>.shard.{0..N-1}.csv`, each with the same header
as the input and a disjoint slice of rows. The union of shards equals
the input, minus the header which is replicated.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def shard_csv(csv_path: Path, shards: int, out_dir: Path) -> list[Path]:
    with csv_path.open(newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    out_dir.mkdir(parents=True, exist_ok=True)
    n = len(rows)
    stem = csv_path.stem
    paths: list[Path] = []
    for i in range(shards):
        lo = (i * n) // shards
        hi = ((i + 1) * n) // shards
        chunk = rows[lo:hi]
        out = out_dir / f"{stem}.shard.{i}.csv"
        with out.open("w", newline="") as g:
            w = csv.writer(g)
            w.writerow(header)
            w.writerows(chunk)
        paths.append(out)
        print(f"shard {i}: rows {lo}..{hi - 1} ({len(chunk)} rows) → {out}")
    return paths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    if args.shards < 1:
        raise SystemExit("--shards must be >= 1")
    shard_csv(args.csv, args.shards, args.out_dir)


if __name__ == "__main__":
    main()
