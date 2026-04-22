"""CLI wrapper around `src.warehouse.builder.build`.

Rebuilds the DuckDB warehouse at `data/warehouse/judex.duckdb` from
the current `data/cases/` + `data/cache/pdf/` stores. Full rebuild,
atomic swap, no incremental logic.

Usage:
    PYTHONPATH=. uv run python scripts/build_warehouse.py
    PYTHONPATH=. uv run python scripts/build_warehouse.py --classe HC
    PYTHONPATH=. uv run python scripts/build_warehouse.py --year 2026 --classe HC \\
        --output data/warehouse/judex-2026.duckdb
    PYTHONPATH=. uv run python scripts/build_warehouse.py --output data/warehouse/dev.duckdb
"""

from __future__ import annotations

import argparse
from pathlib import Path

from judex.warehouse import builder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases-root", type=Path, default=Path("data/cases"))
    parser.add_argument("--pdf-cache-root", type=Path, default=Path("data/cache/pdf"))
    parser.add_argument("--output", type=Path, default=Path("data/warehouse/judex.duckdb"))
    parser.add_argument(
        "--classe", action="append",
        help="Restrict ingest to one or more classes (e.g. --classe HC --classe ADI)."
    )
    parser.add_argument(
        "--year", type=int,
        help="Filter to one HC year via hc_calendar.year_to_id_range (requires --classe HC)."
    )
    parser.add_argument("--progress-every", type=int, default=10_000)
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero if any case-level population rate (partes, "
             "andamentos, pautas, sessao_virtual, publicacoes_dje) falls "
             "below its threshold. Warehouse file is still written so the "
             "bad build can be inspected manually; this only gates CI. "
             "Thresholds live in judex.warehouse.builder.MIN_POPULATION_RATES."
    )
    args = parser.parse_args(argv)

    id_range = None
    if args.year is not None:
        if args.classe != ["HC"]:
            parser.error("--year requires --classe HC (calendar is HC-only)")
        from judex.utils.hc_calendar import year_to_id_range
        id_range = year_to_id_range(args.year)
        print(f"  year {args.year} → id_range {id_range[0]}..{id_range[1]}")

    print(f"building warehouse → {args.output}")
    print(f"  cases   from {args.cases_root}")
    print(f"  pdfs    from {args.pdf_cache_root}")
    if args.classe:
        print(f"  classes {args.classe}")

    try:
        summary = builder.build(
            cases_root=args.cases_root,
            pdf_cache_root=args.pdf_cache_root,
            output_path=args.output,
            classes=args.classe,
            id_range=id_range,
            progress_every=args.progress_every,
            strict=args.strict,
        )
    except builder.BuildValidationError as e:
        # `strict=True` raises *after* writing the warehouse file + printing
        # stats — so the user sees what failed. Return non-zero so CI / any
        # scheduled rebuild catches the regression.
        print(f"\nERROR: {e}")
        return 2

    size_mb = args.output.stat().st_size / 1024**2
    print()
    print(f"done in {summary.wall_s:.1f}s → {size_mb:.1f} MB")
    print(f"  cases             {summary.n_cases:>10,}")
    print(f"  partes            {summary.n_partes:>10,}")
    print(f"  andamentos        {summary.n_andamentos:>10,}")
    print(f"  documentos        {summary.n_documentos:>10,}")
    print(f"  pautas            {summary.n_pautas:>10,}")
    print(f"  publicacoes_dje   {summary.n_publicacoes_dje:>10,}")
    print(f"  decisoes_dje      {summary.n_decisoes_dje:>10,}")
    print(f"  pdfs              {summary.n_pdfs:>10,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
