"""Split a (classe, processo) sweep CSV into N disjoint shards.

Two partitioning strategies:

- **interleave** (default) — assign row i to shard (i % N). Every
  shard sees a statistically-even sample of the input regardless of
  how it's ordered, which defeats load skew when the CSV is sorted
  by a dimension correlated with workload (e.g., pid ascending +
  fresh-vs-cached URL mix — the skew that bit the 2026-04-19 PDF
  sweep).
- **range** — assign rows `[i*N/shards .. (i+1)*N/shards)` to shard i.
  Preserves pid locality (handy when the mental model is "shard-a is
  currently at HC X") but concentrates correlated workload in the
  early shards. Retained as an opt-in.

Usage:

    uv run python scripts/shard_csv.py \\
        --csv tests/sweep/hc_all_desc.csv \\
        --shards 4 \\
        --out-dir tests/sweep/shards/

    # opt into the legacy range partitioning
    uv run python scripts/shard_csv.py \\
        --csv X.csv --shards 4 --out-dir out/ --strategy range

Writes ``<out-dir>/<stem>.shard.{0..N-1}.csv``, each with the same
header as the input and a disjoint slice of rows. Regardless of
strategy, the union of shards equals the input (minus the header,
which is replicated).
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Literal

ShardStrategy = Literal["interleave", "range"]


def shard_csv(
    csv_path: Path,
    shards: int,
    out_dir: Path,
    *,
    strategy: ShardStrategy = "interleave",
) -> list[Path]:
    if strategy not in ("interleave", "range"):
        raise ValueError(
            f"unknown strategy {strategy!r}; expected 'interleave' or 'range'"
        )

    with csv_path.open(newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    out_dir.mkdir(parents=True, exist_ok=True)
    n = len(rows)
    stem = csv_path.stem

    if strategy == "interleave":
        chunks: list[list[list[str]]] = [[] for _ in range(shards)]
        for idx, row in enumerate(rows):
            chunks[idx % shards].append(row)
    else:  # range
        chunks = []
        for i in range(shards):
            lo = (i * n) // shards
            hi = ((i + 1) * n) // shards
            chunks.append(rows[lo:hi])

    paths: list[Path] = []
    for i, chunk in enumerate(chunks):
        out = out_dir / f"{stem}.shard.{i}.csv"
        with out.open("w", newline="") as g:
            w = csv.writer(g)
            w.writerow(header)
            w.writerows(chunk)
        paths.append(out)
        print(
            f"shard {i} ({strategy}): {len(chunk)} rows → {out}"
        )
    return paths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument(
        "--strategy",
        choices=("interleave", "range"),
        default="interleave",
        help=(
            "interleave (default): assign row i to shard (i %% N), "
            "balances correlated workloads. range: contiguous slices, "
            "preserves pid locality."
        ),
    )
    args = ap.parse_args()
    if args.shards < 1:
        raise SystemExit("--shards must be >= 1")
    shard_csv(args.csv, args.shards, args.out_dir, strategy=args.strategy)


if __name__ == "__main__":
    main()
