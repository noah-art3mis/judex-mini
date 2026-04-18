"""Unified progress probe across N sweep shards.

A sharded sweep writes one `sweep.state.json` per shard. This script
unions them into a single view so you don't have to eyeball four probes
and mentally sum.

Usage:

    uv run python scripts/probe_sharded.py \\
        --out-root docs/sweep-results/2026-04-17-hc-full-backfill-sharded

Reads `<out-root>/shard-*/sweep.state.json` and prints:

- Global status counter (ok / fail / error).
- Per-shard regime distribution (only fresh-sweep entries have a regime).
- Per-shard most-recent HC seen (to eyeball which shard is furthest
  through its CSV slice).
- Oldest state-file mtime across shards → the staleness of the weakest
  link.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path


def probe(out_root: Path) -> None:
    shard_dirs = sorted(d for d in out_root.glob("shard-*") if d.is_dir())
    if not shard_dirs:
        raise SystemExit(f"no shard-* dirs under {out_root}")

    global_statuses: Counter[str] = Counter()
    global_regimes: Counter[str] = Counter()
    total_records = 0
    oldest_mtime = None

    print(f"shards found: {len(shard_dirs)}\n")
    for d in shard_dirs:
        sf = d / "sweep.state.json"
        if not sf.exists():
            print(f"  {d.name}: (no sweep.state.json yet)")
            continue
        mtime = sf.stat().st_mtime
        oldest_mtime = mtime if oldest_mtime is None else min(oldest_mtime, mtime)
        state = json.loads(sf.read_text())
        total_records += len(state)
        shard_statuses: Counter[str] = Counter()
        shard_regimes: Counter[str] = Counter()
        last_processo = None
        for k, v in state.items():
            if not isinstance(v, dict):
                continue
            st = v.get("status")
            if st:
                shard_statuses[st] += 1
                global_statuses[st] += 1
            rg = v.get("regime")
            if rg:
                shard_regimes[rg] += 1
                global_regimes[rg] += 1
            p = v.get("processo")
            if isinstance(p, int):
                last_processo = p if last_processo is None else min(last_processo, p)
        age_s = time.time() - mtime
        print(
            f"  {d.name}: {len(state)} recs "
            f"statuses={dict(shard_statuses)} "
            f"regimes={dict(shard_regimes) or '—'} "
            f"min_processo={last_processo} "
            f"mtime={time.strftime('%H:%M:%S', time.localtime(mtime))} "
            f"(age {age_s:.0f}s)"
        )

    print()
    print(f"global records: {total_records}")
    print(f"global statuses: {dict(global_statuses)}")
    print(f"global regimes:  {dict(global_regimes)}")
    if oldest_mtime is not None:
        print(
            f"oldest shard mtime: "
            f"{time.strftime('%H:%M:%S', time.localtime(oldest_mtime))} "
            f"(age {time.time() - oldest_mtime:.0f}s)"
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", type=Path, required=True)
    args = ap.parse_args()
    probe(args.out_root)


if __name__ == "__main__":
    main()
