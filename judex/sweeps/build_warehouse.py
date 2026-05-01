"""Library wrapper around ``judex.warehouse.builder.build``.

Rebuilds the DuckDB warehouse at ``data/derived/warehouse/judex.duckdb``
from the current ``data/source/processos/`` + ``data/derived/pecas-texto/``
stores. Full rebuild, atomic swap, no incremental logic.

Surfaced via Typer at ``judex atualizar-warehouse``; library entry point
is :func:`run_build_warehouse`. Examples:

    uv run judex atualizar-warehouse
    uv run judex atualizar-warehouse --classe HC
    uv run judex atualizar-warehouse --year 2026 --classe HC \\
        --output data/derived/warehouse/judex-2026.duckdb
"""

from __future__ import annotations

from pathlib import Path

from judex.warehouse import builder


def run_build_warehouse(
    *,
    cases_root: Path = Path("data/source/processos"),
    pecas_texto_root: Path = Path("data/derived/pecas-texto"),
    output: Path = Path("data/derived/warehouse/judex.duckdb"),
    classe: list[str] | None = None,
    year: int | None = None,
    progress_every: int = 10_000,
    strict: bool = False,
    unallocated_pids_root: Path = Path("data/derived/nao-alocados"),
) -> int:
    id_range = None
    if year is not None:
        if classe != ["HC"]:
            print("ERROR: --year requires --classe HC (calendar is HC-only)")
            return 2
        from judex.utils.hc_calendar import year_to_id_range
        id_range = year_to_id_range(year)
        print(f"  year {year} → id_range {id_range[0]}..{id_range[1]}")

    print(f"building warehouse → {output}")
    print(f"  processos    from {cases_root}")
    print(f"  pecas-texto  from {pecas_texto_root}")
    if classe:
        print(f"  classes {classe}")

    try:
        summary = builder.build(
            cases_root=cases_root,
            pecas_texto_root=pecas_texto_root,
            output_path=output,
            classes=classe,
            id_range=id_range,
            progress_every=progress_every,
            strict=strict,
            unallocated_pids_root=unallocated_pids_root,
        )
    except builder.BuildValidationError as e:
        # `strict=True` raises *after* writing the warehouse file + printing
        # stats — so the user sees what failed. Return non-zero so CI / any
        # scheduled rebuild catches the regression.
        print(f"\nERROR: {e}")
        return 2

    size_mb = output.stat().st_size / 1024**2
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
    print(f"  unallocated_pids  {summary.n_unallocated:>10,}")
    return 0


