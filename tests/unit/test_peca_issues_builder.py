"""Tests for ``judex.warehouse.peca_issues.build_peca_issues``.

Synthesise:
  - ``runs/`` with two state.json files (one mono, one sharded);
  - a peca-cache dir with extractor + dismissal sidecars;
  - an in-memory DuckDB seeded with andamentos/documentos/pdfs/cases;
…then build the table and inspect the result.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pytest


def _sha1(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _write_state(path: Path, cases: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "started_at": "2026-05-04T00:00:00Z",
        "snapshot_at": "2026-05-04T00:00:01Z",
        "cases": cases,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def warehouse_con():
    """Empty in-memory DuckDB with the schema build_peca_issues
    expects to read (andamentos / documentos / pdfs) and write
    (peca_issues)."""
    con = duckdb.connect(":memory:")
    # Tables read by enrich_warehouse_joins
    con.execute("CREATE TABLE andamentos (link_url VARCHAR, link_tipo VARCHAR)")
    con.execute("CREATE TABLE documentos (url VARCHAR, doc_type VARCHAR)")
    con.execute("CREATE TABLE pdfs (sha1 VARCHAR, n_chars INTEGER)")
    # Output table — schema mirrors builder._SCHEMA_SQL.
    con.execute("""
        CREATE TABLE peca_issues (
            url VARCHAR PRIMARY KEY, sha1 VARCHAR NOT NULL,
            classe VARCHAR, processo_id INTEGER, doc_type VARCHAR,
            latest_status VARCHAR, latest_extractor VARCHAR,
            n_chars INTEGER, is_suspicious_short BOOLEAN,
            n_attempts_seen INTEGER NOT NULL,
            first_seen_at VARCHAR, last_seen_at VARCHAR,
            last_run_dir VARCHAR,
            dismissed_at VARCHAR, dismissed_reason VARCHAR
        )
    """)
    return con


def test_build_peca_issues_empty_runs_root(tmp_path: Path, warehouse_con) -> None:
    """No state.json files → 0 rows, no error."""
    from judex.warehouse.peca_issues import build_peca_issues
    n = build_peca_issues(
        warehouse_con,
        runs_root=tmp_path / "runs",
        pecas_texto_root=tmp_path / "pecas-texto",
    )
    assert n == 0


def test_build_peca_issues_aggregates_across_runs(
    tmp_path: Path, warehouse_con,
) -> None:
    """Two run dirs with overlapping URLs collapse to one row per URL.
    n_attempts_seen counts both observations; last-write-wins picks the
    higher ts as the latest_status."""
    from judex.warehouse.peca_issues import build_peca_issues

    runs = tmp_path / "runs"
    # Run A: u1 had a transient failure at 09:00.
    _write_state(runs / "run-a" / "executar.state.json", {
        "HC-1": {
            "fetch_meta": {"status": "ok", "ts": "2026-05-04T09:00:00Z",
                           "retry_count": 0, "error": None},
            "fetch_bytes": {
                "u1": {"status": "http_error",
                       "ts": "2026-05-04T09:00:00Z",
                       "doc_type": "X", "retry_count": 1, "error": "timeout"},
            },
        },
    })
    # Run B: u1 succeeded at 10:00; u2 newly seen.
    _write_state(runs / "run-b" / "executar.state.json", {
        "HC-1": {
            "fetch_meta": {"status": "ok", "ts": "2026-05-04T10:00:00Z",
                           "retry_count": 0, "error": None},
            "fetch_bytes": {
                "u1": {"status": "ok", "ts": "2026-05-04T10:00:00Z",
                       "doc_type": "X", "retry_count": 0, "error": None},
                "u2": {"status": "empty", "ts": "2026-05-04T10:01:00Z",
                       "doc_type": "Y", "retry_count": 0, "error": None},
            },
        },
    })

    n = build_peca_issues(
        warehouse_con, runs_root=runs, pecas_texto_root=tmp_path / "missing",
    )
    assert n == 2

    rows = warehouse_con.execute(
        "SELECT url, latest_status, n_attempts_seen, last_run_dir, "
        "first_seen_at, last_seen_at FROM peca_issues ORDER BY url"
    ).fetchall()
    assert rows[0][0] == "u1"
    assert rows[0][1] == "ok"  # latest > earlier http_error
    assert rows[0][2] == 2     # seen in both runs
    assert rows[0][3] == "run-b"
    assert rows[0][4] == "2026-05-04T09:00:00Z"  # first
    assert rows[0][5] == "2026-05-04T10:00:00Z"  # last

    assert rows[1][0] == "u2"
    assert rows[1][1] == "empty"
    assert rows[1][2] == 1


def test_build_peca_issues_pulls_doc_type_from_andamentos(
    tmp_path: Path, warehouse_con,
) -> None:
    """doc_type is joined from the warehouse's andamentos table."""
    from judex.warehouse.peca_issues import build_peca_issues

    warehouse_con.execute(
        "INSERT INTO andamentos VALUES (?, ?)",
        ("u1", "DECISÃO MONOCRÁTICA"),
    )

    runs = tmp_path / "runs"
    _write_state(runs / "run-a" / "executar.state.json", {
        "HC-1": {
            "fetch_bytes": {
                "u1": {"status": "ok", "ts": "x", "retry_count": 0,
                       "error": None, "doc_type": "X"},
            },
        },
    })
    build_peca_issues(
        warehouse_con, runs_root=runs, pecas_texto_root=tmp_path / "missing",
    )
    doc_type = warehouse_con.execute(
        "SELECT doc_type FROM peca_issues WHERE url='u1'"
    ).fetchone()[0]
    assert doc_type == "DECISÃO MONOCRÁTICA"


def test_build_peca_issues_pulls_chars_and_flags_suspicious(
    tmp_path: Path, warehouse_con,
) -> None:
    """n_chars from pdfs + doc_type from andamentos → is_suspicious_short
    fires when the substantive peça's text is too short."""
    from judex.warehouse.peca_issues import build_peca_issues

    sha1 = _sha1("u1")
    warehouse_con.execute(
        "INSERT INTO andamentos VALUES (?, ?)", ("u1", "DECISÃO MONOCRÁTICA"),
    )
    warehouse_con.execute(
        "INSERT INTO pdfs VALUES (?, ?)", (sha1, 50),  # 50 chars: suspicious
    )

    runs = tmp_path / "runs"
    _write_state(runs / "run-a" / "executar.state.json", {
        "HC-1": {
            "fetch_bytes": {
                "u1": {"status": "ok", "ts": "x", "retry_count": 0,
                       "error": None, "doc_type": "X"},
            },
        },
    })
    build_peca_issues(
        warehouse_con, runs_root=runs, pecas_texto_root=tmp_path / "missing",
    )
    n_chars, is_susp = warehouse_con.execute(
        "SELECT n_chars, is_suspicious_short FROM peca_issues WHERE url='u1'"
    ).fetchone()
    assert n_chars == 50
    assert is_susp is True


def test_build_peca_issues_reads_extractor_and_dismissal_sidecars(
    tmp_path: Path, warehouse_con,
) -> None:
    """latest_extractor + dismissed_{at,reason} populated from the
    peca-cache directory's sidecar files."""
    from judex.warehouse.peca_issues import build_peca_issues

    pecas_texto = tmp_path / "pecas-texto"
    pecas_texto.mkdir()
    sha1 = _sha1("u1")
    (pecas_texto / f"{sha1}.extractor").write_text("tesseract", encoding="utf-8")
    (pecas_texto / f"{sha1}.dismissed.json").write_text(json.dumps({
        "url": "u1", "reason": "PDF retirado",
        "dismissed_at": "2026-05-04T11:00:00+00:00",
    }))

    runs = tmp_path / "runs"
    _write_state(runs / "run-a" / "executar.state.json", {
        "HC-1": {
            "fetch_bytes": {
                "u1": {"status": "ok", "ts": "x", "retry_count": 0,
                       "error": None, "doc_type": "X"},
            },
        },
    })
    build_peca_issues(
        warehouse_con, runs_root=runs, pecas_texto_root=pecas_texto,
    )
    extractor, dismissed_at, dismissed_reason = warehouse_con.execute(
        "SELECT latest_extractor, dismissed_at, dismissed_reason "
        "FROM peca_issues WHERE url='u1'"
    ).fetchone()
    assert extractor == "tesseract"
    assert dismissed_at == "2026-05-04T11:00:00+00:00"
    assert dismissed_reason == "PDF retirado"


def test_build_peca_issues_skips_malformed_state_json(
    tmp_path: Path, warehouse_con,
) -> None:
    """A malformed state.json (truncated tail, invalid JSON) must not
    abort the build — skip silently and let the rest of the runs
    contribute their data."""
    from judex.warehouse.peca_issues import build_peca_issues

    runs = tmp_path / "runs"
    (runs / "broken").mkdir(parents=True)
    (runs / "broken" / "executar.state.json").write_text("{not valid json")
    _write_state(runs / "good" / "executar.state.json", {
        "HC-1": {
            "fetch_bytes": {
                "u1": {"status": "ok", "ts": "x", "retry_count": 0,
                       "error": None, "doc_type": "X"},
            },
        },
    })
    n = build_peca_issues(
        warehouse_con, runs_root=runs, pecas_texto_root=tmp_path / "missing",
    )
    assert n == 1  # broken skipped, good ingested


def test_build_peca_issues_walks_legacy_pdfs_state_json(
    tmp_path: Path, warehouse_con,
) -> None:
    """Legacy three-command-chain dirs use ``pdfs.state.json`` (not
    ``executar.state.json``). Both filenames must be picked up."""
    from judex.warehouse.peca_issues import build_peca_issues

    runs = tmp_path / "runs"
    _write_state(runs / "legacy" / "pdfs.state.json", {
        "HC-1": {
            "fetch_bytes": {
                "u1": {"status": "ok", "ts": "x", "retry_count": 0,
                       "error": None, "doc_type": "X"},
            },
        },
    })
    n = build_peca_issues(
        warehouse_con, runs_root=runs, pecas_texto_root=tmp_path / "missing",
    )
    assert n == 1
