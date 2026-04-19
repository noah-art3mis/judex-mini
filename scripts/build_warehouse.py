"""CLI wrapper around `src.warehouse.builder.build`.

Rebuilds the DuckDB warehouse at `data/warehouse/judex.duckdb` from
the current `data/cases/` + `data/cache/pdf/` stores. Full rebuild,
atomic swap, no incremental logic.

Usage:
    PYTHONPATH=. uv run python scripts/build_warehouse.py
    PYTHONPATH=. uv run python scripts/build_warehouse.py --classe HC
    PYTHONPATH=. uv run python scripts/build_warehouse.py --output data/warehouse/dev.duckdb
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.warehouse import builder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases-root", type=Path, default=Path("data/cases"))
    parser.add_argument("--pdf-cache-root", type=Path, default=Path("data/cache/pdf"))
    parser.add_argument("--output", type=Path, default=Path("data/warehouse/judex.duckdb"))
    parser.add_argument(
        "--classe", action="append",
        help="Restrict ingest to one or more classes (e.g. --classe HC --classe ADI)."
    )
    parser.add_argument("--progress-every", type=int, default=10_000)
    args = parser.parse_args(argv)

    print(f"building warehouse → {args.output}")
    print(f"  cases   from {args.cases_root}")
    print(f"  pdfs    from {args.pdf_cache_root}")
    if args.classe:
        print(f"  classes {args.classe}")

    summary = builder.build(
        cases_root=args.cases_root,
        pdf_cache_root=args.pdf_cache_root,
        output_path=args.output,
        classes=args.classe,
        progress_every=args.progress_every,
    )

    size_mb = args.output.stat().st_size / 1024**2
    print()
    print(f"done in {summary.wall_s:.1f}s → {size_mb:.1f} MB")
    print(f"  cases        {summary.n_cases:>8,}")
    print(f"  partes       {summary.n_partes:>8,}")
    print(f"  andamentos   {summary.n_andamentos:>8,}")
    print(f"  documentos   {summary.n_documentos:>8,}")
    print(f"  pdfs         {summary.n_pdfs:>8,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
