"""Aggregate unallocated-pid observations across past sweeps.

Walks ``sweep.state.json`` files under ``--runs-root`` (recursively),
groups ``status=unallocated`` entries by processo_id, and writes two
files under ``--out``:

    <classe>.txt              # sorted pids confirmed unallocated (>= --min-obs)
    <classe>.candidates.tsv   # all observed pids with counts (auditable)

See ``judex/utils/unallocated_pids.py`` for the aggregation semantics
and ``docs/adr/0002-distinguish-unallocated-processo-id-from-scrape-failure.md``
for the framing rationale (per-attempt empty-body filtering happens at
sweep write time, so the aggregator predicate here is single-field).

Usage:

    uv run python scripts/aggregate_unallocated_pids.py --classe HC

    # Custom roots / stricter threshold
    uv run python scripts/aggregate_unallocated_pids.py --classe HC \\
        --runs-root runs/active --runs-root runs/archive \\
        --out data/derived/nao-alocados --min-observations 3
"""

from __future__ import annotations

import argparse
from pathlib import Path

from judex.utils.unallocated_pids import (
    classify_confirmed,
    collect_observations,
    write_unallocated_pid_files,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--classe", required=True,
        help="STF class to aggregate (HC, ADI, RE, ...).",
    )
    ap.add_argument(
        "--runs-root", type=Path, action="append",
        help="Directory to scan (recursively) for sweep.state.json files. "
             "Repeatable. Default: runs/",
    )
    ap.add_argument(
        "--out", type=Path, default=Path("data/derived/nao-alocados"),
        help="Output directory (creates <classe>.txt + <classe>.candidates.tsv).",
    )
    ap.add_argument(
        "--min-observations", type=int, default=2,
        help="Minimum independent observations required to promote a pid "
             "from candidate to confirmed-unallocated. Default: 2.",
    )
    args = ap.parse_args(argv)

    roots = args.runs_root or [Path("runs")]
    observations = collect_observations(roots, classe=args.classe)
    confirmed = classify_confirmed(observations, min_observations=args.min_observations)

    txt_path, tsv_path = write_unallocated_pid_files(
        observations,
        out_dir=args.out,
        classe=args.classe,
        min_observations=args.min_observations,
    )

    roots_str = ", ".join(str(r) for r in roots)
    print(
        f"classe={args.classe} roots=[{roots_str}] "
        f"observations={len(observations)} confirmed={len(confirmed)} "
        f"→ {txt_path} + {tsv_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
