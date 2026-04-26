"""Typer wrapper `judex atualizar-warehouse`.

Behavior-level coverage — the heavy lifting is already pinned by
`test_build_warehouse.py` against `judex.warehouse.builder.build`. Here
we only verify the CLI plumbing: flags reach the builder, the output
DuckDB materializes, and a non-default `--saida` is honored.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
from typer.testing import CliRunner

from judex.cli import app


def _write_case(root: Path, *, classe: str, processo_id: int) -> None:
    d = root / classe
    d.mkdir(parents=True, exist_ok=True)
    item = {
        "incidente": 1000 + processo_id,
        "classe": classe,
        "processo_id": processo_id,
        "numero_unico": f"0000{processo_id}-00.2020.1.00.0000",
        "meio": "ELETRONICO",
        "publicidade": "PUBLICO",
        "badges": [],
        "assuntos": [],
        "data_protocolo": "15/03/2020",
        "orgao_origem": "STJ",
        "origem": "SP",
        "numero_origem": [],
        "volumes": 1, "folhas": 1, "apensos": 0,
        "relator": "MIN. TESTE",
        "primeiro_autor": "Fulano",
        "partes": [],
        "andamentos": [],
        "sessao_virtual": [],
        "deslocamentos": [], "peticoes": [], "recursos": [], "pautas": None,
        "outcome": "pending",
        "status": 200,
        "extraido": "2026-04-19T00:00:00",
        "html": "<html/>",
    }
    (d / f"judex-mini_{classe}_{processo_id}.json").write_text(json.dumps([item]))


def test_atualizar_warehouse_builds_duckdb_at_saida(tmp_path: Path) -> None:
    """The wrapper must actually produce a queryable .duckdb at --saida."""
    cases = tmp_path / "cases"
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    _write_case(cases, classe="HC", processo_id=1)
    out = tmp_path / "judex.duckdb"

    result = CliRunner().invoke(app, [
        "atualizar-warehouse",
        "--diretorio-processos", str(cases),
        "--diretorio-pecas-texto", str(pdfs),
        "--saida", str(out),
    ])

    assert result.exit_code == 0, result.output
    assert out.exists()
    with duckdb.connect(str(out), read_only=True) as con:
        n = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    assert n == 1


def test_atualizar_warehouse_classe_filter_restricts_ingest(tmp_path: Path) -> None:
    """`--classe HC` must reach the builder and filter the ingest."""
    cases = tmp_path / "cases"
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    _write_case(cases, classe="HC", processo_id=1)
    _write_case(cases, classe="ADI", processo_id=10)
    out = tmp_path / "judex.duckdb"

    result = CliRunner().invoke(app, [
        "atualizar-warehouse",
        "--diretorio-processos", str(cases),
        "--diretorio-pecas-texto", str(pdfs),
        "--saida", str(out),
        "--classe", "HC",
    ])

    assert result.exit_code == 0, result.output
    with duckdb.connect(str(out), read_only=True) as con:
        rows = con.execute("SELECT DISTINCT classe FROM cases").fetchall()
    assert rows == [("HC",)]


def test_atualizar_warehouse_year_requires_classe_hc(tmp_path: Path) -> None:
    """`--ano` without `--classe HC` must error out (from build_warehouse.py)."""
    cases = tmp_path / "cases"
    cases.mkdir()
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    out = tmp_path / "judex.duckdb"

    result = CliRunner().invoke(app, [
        "atualizar-warehouse",
        "--diretorio-processos", str(cases),
        "--diretorio-pecas-texto", str(pdfs),
        "--saida", str(out),
        "--ano", "2020",
    ])
    assert result.exit_code != 0
