"""Tests for ``judex.analysis.peca_spot_check``.

In-memory DuckDB harness: build minimal cases + pdfs_substantive
fixtures, call sample_pecas, verify filter and is_suspicious_short
flagging.
"""
from __future__ import annotations

import duckdb
import pytest

from judex.analysis.peca_spot_check import (
    PecaSample,
    render_samples,
    sample_pecas,
)


@pytest.fixture
def con():
    """A fresh DuckDB connection with the minimum schema sample_pecas needs.

    The schema mirrors the production warehouse's relevant tables:
    ``cases`` for year filtering, ``andamentos`` + ``documentos`` for
    doc_type-tagged peça URLs, ``pdfs`` for text content. The function
    builds its own metadata CTE from these — there's no
    ``pdfs_substantive`` view in the test harness.
    """
    c = duckdb.connect(":memory:")
    c.execute("""
        CREATE TABLE cases (
            classe VARCHAR,
            processo_id INTEGER,
            data_protocolo_iso DATE
        )
    """)
    c.execute("""
        CREATE TABLE andamentos (
            classe VARCHAR,
            processo_id INTEGER,
            link_tipo VARCHAR,
            link_url VARCHAR,
            link_url_sha1 VARCHAR
        )
    """)
    c.execute("""
        CREATE TABLE documentos (
            classe VARCHAR,
            processo_id INTEGER,
            doc_type VARCHAR,
            url VARCHAR,
            url_sha1 VARCHAR,
            text VARCHAR
        )
    """)
    c.execute("""
        CREATE TABLE pdfs (
            sha1 VARCHAR,
            n_chars INTEGER,
            text VARCHAR
        )
    """)

    cases_data = [
        ("HC", 100, "2024-01-15"),
        ("HC", 200, "2024-06-10"),
        ("HC", 300, "2025-03-01"),
        ("HC", 400, "2025-08-22"),
        ("ADI", 50,  "2024-04-04"),
        ("ADI", 60,  "2025-09-09"),
    ]
    for row in cases_data:
        c.execute("INSERT INTO cases VALUES (?, ?, ?)", row)

    # Andamentos-sourced peças (filter set: DECISÃO MONOCRÁTICA, INTEIRO
    # TEOR DO ACÓRDÃO, MANIFESTAÇÃO DA PGR, DESPACHO — matches the
    # ``meta`` CTE in sample_pecas).
    andamentos = [
        # (classe, pid, link_tipo, link_url, link_url_sha1)
        ("HC", 100, "DECISÃO MONOCRÁTICA",      "u-100a", "sha-100a"),
        ("HC", 200, "INTEIRO TEOR DO ACÓRDÃO",  "u-200a", "sha-200a"),
        ("HC", 300, "DECISÃO MONOCRÁTICA",      "u-300a", "sha-300a"),
        ("HC", 400, "DESPACHO",                  "u-400a", "sha-400a"),
        # Non-substantive — must NOT appear in samples.
        ("HC", 100, "CERTIDÃO",                  "u-cert",  "sha-cert"),
    ]
    for row in andamentos:
        c.execute("INSERT INTO andamentos VALUES (?, ?, ?, ?, ?)", row)

    # Sessão-virtual documentos peças (filter set: Voto / Relatório /
    # Voto Vogal / Voto Vista).
    documentos = [
        # (classe, pid, doc_type, url, url_sha1, text)
        # n_chars is derived as length(text) — fixture text lengths
        # must be realistic so the suspicious-short detector behaves
        # like it would on real data.
        ("HC",  100, "Voto",  "u-100b", "sha-100b", "Voto-Vista"),  # 10 — short
        ("ADI", 50,  "Voto",  "u-50a",  "sha-50a",  "voto do relator " * 1500),
    ]
    for row in documentos:
        c.execute("INSERT INTO documentos VALUES (?, ?, ?, ?, ?, ?)", row)

    # pdfs holds the canonical n_chars + text. Andamentos-sourced peças
    # are joined via sha1; documentos peças have their own inline text
    # (n_chars derived from length in the SQL). HC 100 Voto deliberately
    # has no pdfs row to mirror the documentos-only path; its text comes
    # from documentos.text via the LEFT JOIN.
    pdfs = [
        ("sha-100a", 5_000,  "decisão completa com fundamentação …"),
        ("sha-200a", 50,     "Plenário Virtual …"),       # suspicious-short
        ("sha-300a", 12_000, "outro pronunciamento …"),
        ("sha-400a", 800,    "despacho ordinatório …"),
        ("sha-cert", 200,    "certidão de coisa julgada …"),
    ]
    for row in pdfs:
        c.execute("INSERT INTO pdfs VALUES (?, ?, ?)", row)
    return c


def test_sample_pecas_no_filter_returns_n(con) -> None:
    samples = sample_pecas(con, n=3, seed=42)
    assert len(samples) == 3
    assert all(isinstance(s, PecaSample) for s in samples)


def test_sample_pecas_classe_filter(con) -> None:
    samples = sample_pecas(con, classe="ADI", n=10, seed=42)
    assert len(samples) == 1
    assert samples[0].classe == "ADI"


def test_sample_pecas_year_filter(con) -> None:
    samples_2024 = sample_pecas(con, year=2024, n=10, seed=42)
    classes_pids_2024 = {(s.classe, s.processo_id) for s in samples_2024}
    # 2024 cases: HC 100, HC 200, ADI 50 → their peças.
    expected_2024 = {("HC", 100), ("HC", 200), ("ADI", 50)}
    assert classes_pids_2024 == expected_2024


def test_sample_pecas_doc_type_filter(con) -> None:
    samples = sample_pecas(con, doc_type="Voto", n=10, seed=42)
    assert {s.doc_type for s in samples} == {"Voto"}
    assert len(samples) == 2  # HC 100 voto + ADI 50 voto


def test_sample_pecas_combined_filters(con) -> None:
    samples = sample_pecas(
        con, classe="HC", year=2024, doc_type="Voto", n=10, seed=42,
    )
    assert len(samples) == 1
    assert samples[0].sha1 == "sha-100b"
    # 10 chars + doc_type 'Voto' (sessão-virtual cased label) is
    # suspicious-short — peca_quality detector is case-insensitive on
    # the substantive set.
    assert samples[0].is_suspicious_short is True


def test_sample_pecas_flags_suspicious_short(con) -> None:
    """The two short peças (10-char VOTO, 50-char ACÓRDÃO) must be
    flagged. The healthy ones (5k-char DECISÃO, 12k-char DECISÃO,
    20k-char VOTO) must not."""
    all_samples = sample_pecas(con, n=10, seed=42)
    by_sha = {s.sha1: s for s in all_samples}
    assert by_sha["sha-100b"].is_suspicious_short is True
    assert by_sha["sha-200a"].is_suspicious_short is True
    assert by_sha["sha-100a"].is_suspicious_short is False
    assert by_sha["sha-300a"].is_suspicious_short is False
    assert by_sha["sha-50a"].is_suspicious_short is False


def test_sample_pecas_seed_makes_deterministic(con) -> None:
    """Same seed → same sample; different seed → (likely) different sample."""
    a = sample_pecas(con, n=3, seed=42)
    b = sample_pecas(con, n=3, seed=42)
    assert [s.sha1 for s in a] == [s.sha1 for s in b]


def test_sample_pecas_n_larger_than_population(con) -> None:
    """Asking for more than exists returns everything that exists."""
    samples = sample_pecas(con, classe="ADI", n=100, seed=42)
    assert len(samples) == 1


def test_render_samples_empty_population(con) -> None:
    out = render_samples([])
    assert "nenhuma" in out


def test_render_samples_marks_suspicious(con) -> None:
    samples = sample_pecas(con, n=10, seed=42)
    out = render_samples(samples)
    # Header line names the suspicious count.
    assert "suspeitas-curtas" in out
    # The two known-suspicious shas appear with the warning marker.
    assert "⚠" in out
