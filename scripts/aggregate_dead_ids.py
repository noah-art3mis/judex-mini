"""Aggregate NoIncidente observations across past sweeps into a dead-ID store.

Walks ``sweep.state.json`` files under ``--runs-root`` (recursively),
groups ``status=fail / error_type=NoIncidente`` entries by processo_id,
and writes two files under ``--out``:

    <classe>.txt              # sorted pids confirmed dead (>= --min-obs with empty body)
    <classe>.candidates.tsv   # all observed pids with counts (auditable)

See ``judex/utils/dead_ids.py`` for the aggregation semantics (why
``body_head == ""`` matters, etc.).

Usage:

    uv run python scripts/aggregate_dead_ids.py --classe HC

    # Custom roots / stricter threshold
    uv run python scripts/aggregate_dead_ids.py --classe HC \\
        --runs-root runs/active --runs-root runs/archive \\
        --out data/dead_ids --min-observations 3
"""

from __future__ import annotations

import argparse
from pathlib import Path

from judex.utils.dead_ids import (
    classify_confirmed,
    collect_observations,
    write_dead_id_files,
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
        "--out", type=Path, default=Path("data/dead_ids"),
        help="Output directory (creates <classe>.txt + <classe>.candidates.tsv).",
    )
    ap.add_argument(
        "--min-observations", type=int, default=2,
        help="Minimum independent NoIncidente observations (with empty "
             "body_head) required to promote a pid from candidate to "
             "confirmed-dead. Default: 2.",
    )
    ap.add_argument(
        "--allow-non-empty-body", action="store_true",
        help="Count observations whose body_head is non-empty. Off by "
             "default — a non-empty Location header on a NoIncidente fail "
             "is most likely a proxy soft-block, not a genuine STF gap.",
    )
    args = ap.parse_args(argv)

    roots = args.runs_root or [Path("runs")]
    observations = collect_observations(roots, classe=args.classe)

    if args.allow_non_empty_body:
        confirmed = classify_confirmed(
            observations,
            min_observations=args.min_observations,
            require_empty_body=False,
        )
    else:
        confirmed = classify_confirmed(
            observations,
            min_observations=args.min_observations,
            require_empty_body=True,
        )

    txt_path, tsv_path = write_dead_id_files(
        observations,
        out_dir=args.out,
        classe=args.classe,
        min_observations=args.min_observations,
    )

    n_candidates = len(observations)
    n_confirmed = len(confirmed)
    roots_str = ", ".join(str(r) for r in roots)
    print(
        f"classe={args.classe} roots=[{roots_str}] "
        f"observations={n_candidates} confirmed={n_confirmed} "
        f"→ {txt_path} + {tsv_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
