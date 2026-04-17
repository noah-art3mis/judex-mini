"""Stratified density probe of process_ids for any STF class.

Only hits `listarProcessos.asp` (one GET per candidate) — no full scrape,
no PDFs. 302 with `incidente=\\d+` → exists; 200 with empty Location →
missing. Buckets results so we can see how density varies across the
space and get a rough count estimate for the full class universe.

Usage:
    PYTHONPATH=. uv run python scripts/class_density_probe.py --classe HC
    PYTHONPATH=. uv run python scripts/class_density_probe.py --classe ADI --samples 20
    PYTHONPATH=. uv run python scripts/class_density_probe.py --classe RE --pacing 2.0

Known ceilings (binary-searched 2026-04-16, see docs/handoff.md):
    HC:  270,071
    ADI:   7,956
    RE:  640,321
"""

from __future__ import annotations

import argparse
import random
import time

import urllib3

from src.config import ScraperConfig
from src.scraper import new_session, resolve_incidente

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


KNOWN_CEILINGS: dict[str, int] = {
    "HC":  270_072,
    "ADI":   7_957,
    "RE":  640_322,
}


def make_bands(ceiling: int, n_bands: int) -> list[tuple[int, int]]:
    """Even-width bands from 1..ceiling. First band starts at 1."""
    if ceiling <= n_bands:
        return [(i, i + 1) for i in range(1, ceiling + 1)]
    edges = [1]
    for k in range(1, n_bands):
        edges.append(int(ceiling * (k / n_bands)))
    edges.append(ceiling)
    return [(edges[i], edges[i + 1]) for i in range(n_bands)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--classe", required=True, help="STF class code (HC, ADI, RE, ...)")
    ap.add_argument(
        "--ceiling", type=int,
        help="Highest process_id to consider. Defaults to known ceiling for "
             "HC/ADI/RE; required for other classes.",
    )
    ap.add_argument("--bands", type=int, default=8, help="Number of bands (default: 8)")
    ap.add_argument(
        "--samples", type=int, default=15,
        help="Random samples per band (default: 15)",
    )
    ap.add_argument(
        "--pacing", type=float, default=1.5,
        help="Seconds between probes (default: 1.5)",
    )
    ap.add_argument("--seed", type=int, default=20260416)
    args = ap.parse_args()

    ceiling = args.ceiling or KNOWN_CEILINGS.get(args.classe)
    if ceiling is None:
        ap.error(f"unknown class {args.classe!r}; pass --ceiling explicitly")

    bands = make_bands(ceiling, args.bands)
    rng = random.Random(args.seed)
    cfg = ScraperConfig(retry_403=True)

    samples: list[tuple[int, int]] = []  # (band_idx, processo)
    for i, (lo, hi) in enumerate(bands):
        size = hi - lo
        k = min(args.samples, size)
        picks = rng.sample(range(lo, hi), k)
        for p in picks:
            samples.append((i, p))

    print(f"=== density probe: {args.classe} · {len(samples)} samples across "
          f"{len(bands)} bands · ceiling={ceiling:,} ===")

    results: list[tuple[int, int, bool]] = []
    session = new_session()
    started = time.perf_counter()
    for j, (band_idx, p) in enumerate(samples, 1):
        try:
            incidente = resolve_incidente(session, args.classe, p, config=cfg)
        except Exception as e:
            print(f"  [{j:>3d}/{len(samples)}] {args.classe} {p}: "
                  f"ERROR {type(e).__name__}: {e}")
            results.append((band_idx, p, False))
        else:
            exists = incidente is not None
            results.append((band_idx, p, exists))
            mark = "ok " if exists else "   "
            print(f"  [{j:>3d}/{len(samples)}] {args.classe} {p:>7d} "
                  f"band={band_idx} {mark} inc={incidente}")
        if j < len(samples):
            time.sleep(args.pacing)

    elapsed = time.perf_counter() - started

    print()
    print("=" * 72)
    print(f"Elapsed: {elapsed:.1f}s  ({elapsed/len(samples):.2f}s/probe avg)")
    print()
    print(f"{args.classe} band density:")
    print(f"  {'range':<24}  {'n':>3}  {'exist':>5}  {'density':>7}  {'est.count':>9}")
    total_est = 0
    for i, (lo, hi) in enumerate(bands):
        band_results = [r for r in results if r[0] == i]
        n = len(band_results)
        exist = sum(1 for _, _, e in band_results if e)
        density = exist / n if n else 0.0
        band_size = hi - lo
        est = int(band_size * density)
        total_est += est
        print(f"  [{lo:>7d}, {hi:>7d})  {n:>3d}  {exist:>5d}  {density:>6.1%}  "
              f"{est:>9,d}")

    total_exist = sum(1 for _, _, e in results if e)
    total_n = len(results)
    print()
    print(f"Overall: {total_exist}/{total_n} = {total_exist/total_n:.1%}")
    print(f"Estimated {args.classe} count across 1..{ceiling-1}: ~{total_est:,d}")


if __name__ == "__main__":
    main()
