"""Read-only connection helper for the DuckDB warehouse.

Primary audience is marimo notebooks in `analysis/`. The read-only
mode means multiple notebooks can attach to the same .duckdb file
concurrently without stepping on each other or interfering with a
`scripts/build_warehouse.py` rebuild (DuckDB lets read-only clients
keep old snapshots open while a separate writer produces a new file
via tempfile + os.replace — the usual atomic-swap trick).

Usage (marimo):

    from src.warehouse.query import open_readonly

    con = open_readonly()
    df = con.execute('''
        SELECT classe, processo_id, relator, data_protocolo_iso
        FROM cases
        WHERE classe = 'HC' AND data_protocolo_iso >= DATE '2024-01-01'
        ORDER BY data_protocolo_iso DESC
    ''').df()

Remember to regenerate the .duckdb file after a sweep via
`uv run python scripts/build_warehouse.py` — this helper doesn't
refresh anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb

DEFAULT_PATH = Path("data/warehouse/judex.duckdb")


def open_readonly(path: Optional[Path] = None) -> duckdb.DuckDBPyConnection:
    """Return a read-only connection to the warehouse.

    Raises FileNotFoundError with an actionable message if the file
    hasn't been built yet.
    """
    p = Path(path) if path is not None else DEFAULT_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"warehouse not found at {p}. Build it first:\n"
            f"    PYTHONPATH=. uv run python scripts/build_warehouse.py"
        )
    return duckdb.connect(str(p), read_only=True)


def manifest(path: Optional[Path] = None) -> dict:
    """One-shot snapshot of the last-build manifest."""
    with open_readonly(path) as con:
        row = con.execute(
            "SELECT built_at, classes, n_cases, n_partes, n_andamentos, "
            "n_documentos, n_pdfs, build_wall_s, judex_commit "
            "FROM manifest ORDER BY built_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        raise RuntimeError("warehouse has no manifest row — rebuild it.")
    return {
        "built_at":      row[0],
        "classes":       list(row[1]) if row[1] is not None else [],
        "n_cases":       row[2],
        "n_partes":      row[3],
        "n_andamentos":  row[4],
        "n_documentos":  row[5],
        "n_pdfs":        row[6],
        "build_wall_s":  row[7],
        "judex_commit":  row[8],
    }
