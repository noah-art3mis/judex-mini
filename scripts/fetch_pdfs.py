"""General PDF sweep CLI.

Walks the judex-mini output tree, filters processes + their andamento
PDFs by classe / impetrante / doc_type / relator, and runs them
through the institutional PDF sweep driver (`src.sweeps.pdf_driver`).

Durability: every attempt goes to an atomic `pdfs.state.json`, an
append-only `pdfs.log.jsonl`, and a per-GET `requests.db`. `--resume`
skips already-ok URLs; `--retry-from <pdfs.errors.jsonl>` re-runs only
the URLs that failed in a prior run. SIGINT stops cleanly after the
in-flight target.

Usage:

    # Famous-lawyer preset
    PYTHONPATH=. uv run python scripts/fetch_pdfs.py \\
        --out runs/active/2026-04-17-famous-lawyers \\
        --classe HC \\
        --impte-contains "TORON,PIERPAOLO,ARRUDA BOTELHO,MARCELO LEONARDO,\\
NILO BATISTA,VILARDI,PODVAL,MUDROVITSCH,BADARO,DANIEL GERBER,\\
TRACY JOSEPH REINALDET,PEDRO MACHADO DE ALMEIDA CASTRO" \\
        --doc-types "DECISÃO MONOCRÁTICA,INTEIRO TEOR DO ACÓRDÃO,\\
MANIFESTAÇÃO DA PGR,DESPACHO" \\
        --throttle-sleep 2.0 --resume

    # All HC acórdãos from a specific relator
    PYTHONPATH=. uv run python scripts/fetch_pdfs.py \\
        --out runs/active/fachin-acordaos \\
        --classe HC --relator-contains FACHIN \\
        --doc-types "INTEIRO TEOR DO ACÓRDÃO"
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

from scripts._filters import add_filter_args, targets_from_args
from src.sweeps.pdf_driver import run_pdf_sweep
from src.utils import pdf_cache


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--out", required=True, type=Path,
        help="Output directory. Holds pdfs.state.json, pdfs.log.jsonl, "
             "pdfs.errors.jsonl, requests.db, report.md.",
    )
    add_filter_args(ap)
    ap.add_argument(
        "--throttle-sleep", type=float, default=2.0,
        help="Seconds between successive GETs (default: 2.0). Pass 0 to "
             "disable the outer-loop pace; the adaptive throttle still applies.",
    )
    ap.add_argument(
        "--limit", type=int, default=0,
        help="Truncate target list to N entries before running (0 = no limit). "
             "Applied after filtering.",
    )
    ap.add_argument(
        "--resume", action="store_true",
        help="Skip targets already recorded as status=ok in pdfs.state.json.",
    )
    ap.add_argument(
        "--retry-from", type=Path,
        help="Path to an existing pdfs.errors.jsonl; re-run those URLs only.",
    )
    ap.add_argument(
        "--circuit-window", type=int, default=50,
        help="Rolling window of recent targets the circuit breaker watches. "
             "Pass 0 to disable.",
    )
    ap.add_argument(
        "--circuit-threshold", type=float, default=0.8,
        help="Error-like fraction of the window that trips the breaker "
             "(default: 0.8).",
    )
    ap.add_argument(
        "--no-throttle", dest="adaptive_throttle",
        action="store_false", default=True,
        help="Disable the adaptive per-host throttle.",
    )
    ap.add_argument(
        "--throttle-max-delay", type=float, default=60.0,
        help="Upper bound on the adaptive throttle's per-GET sleep "
             "(default: 60s).",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print target count + doc-type breakdown and exit without fetching.",
    )
    ap.add_argument(
        "--check", action="store_true",
        help="Report cache coverage (cached vs missing) and exit.",
    )
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    targets = targets_from_args(args)
    n_procs = len({t.processo_id for t in targets if t.processo_id is not None})
    print(f"targets: {len(targets)} PDF URLs across {n_procs} processes")

    if args.dry_run:
        by_type = Counter(t.doc_type or "-" for t in targets)
        for k, v in by_type.most_common():
            print(f"  {v:4d}  {k}")
        return 0

    if args.check:
        missing = [t for t in targets if pdf_cache.read(t.url) is None]
        cached = len(targets) - len(missing)
        print(f"cached:  {cached}")
        print(f"missing: {len(missing)}")
        if missing:
            by_type = Counter(t.doc_type or "-" for t in missing)
            print("missing by type:")
            for k, v in by_type.most_common():
                print(f"  {v:4d}  {k}")
        return 0 if not missing else 1

    if args.limit and len(targets) > args.limit:
        targets = targets[: args.limit]

    fetched, cached_hits, failed = run_pdf_sweep(
        targets,
        out_dir=args.out,
        throttle_sleep=args.throttle_sleep,
        resume=args.resume,
        retry_from=args.retry_from,
        circuit_window=args.circuit_window,
        circuit_threshold=args.circuit_threshold,
        adaptive_throttle=args.adaptive_throttle,
        throttle_max_delay=args.throttle_max_delay,
    )

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
