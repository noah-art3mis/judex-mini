"""Sample peças from the warehouse for manual quality inspection.

Operator workflow: "did the last warehouse rebuild produce healthy
text?" — sample N peças, filter by year / doc-type / classe, print
text previews flagged with :func:`peca_quality.is_suspicious_short`.

The pypdf silent-failure pattern (chars > 0 but text is just header
metadata) is invisible to the runner's binary `empty`/`ok` decision.
This is the operator-facing detector.

PRD: .scratch/peca-registry/PRD.md sub-issue 05.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from judex.analysis.peca_quality import is_suspicious_short


@dataclass(frozen=True)
class PecaSample:
    """One sampled peça row from the warehouse, ready for printing."""

    classe: str
    processo_id: int
    doc_type: Optional[str]
    sha1: str
    url: Optional[str]
    n_chars: int
    text_preview: str
    is_suspicious_short: bool


def sample_pecas(
    con,
    *,
    classe: Optional[str] = None,
    year: Optional[int] = None,
    doc_type: Optional[str] = None,
    n: int = 10,
    preview_chars: int = 200,
    seed: Optional[int] = None,
) -> list[PecaSample]:
    """Sample N peças from the warehouse matching the given filters.

    ``con`` is a DuckDB connection (use
    :func:`judex.warehouse.query.open_readonly`). Filters are
    AND-combined; ``None`` filters are skipped. ``seed`` makes the
    sampling deterministic for testing.

    Returns a list of at most N :class:`PecaSample` records (fewer if
    the filtered population is smaller than N).
    """
    where_parts: list[str] = []
    params: list = []

    if classe is not None:
        where_parts.append("ps.classe = ?")
        params.append(classe)

    if year is not None:
        # Join cases on (classe, processo_id) to filter by data_protocolo
        # year. The pdfs_substantive view doesn't carry the date directly.
        where_parts.append(
            "EXISTS (SELECT 1 FROM cases c "
            "WHERE c.classe = ps.classe AND c.processo_id = ps.processo_id "
            "AND EXTRACT(YEAR FROM c.data_protocolo_iso) = ?)"
        )
        params.append(year)

    if doc_type is not None:
        where_parts.append("ps.doc_type = ?")
        params.append(doc_type)

    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    # DuckDB's reservoir-sample-with-seed syntax: ``USING SAMPLE n ROWS
    # (reservoir, seed)``. Without seed, omit the parenthesised tail.
    sample_clause = (
        f"USING SAMPLE {int(n)} ROWS (reservoir, {int(seed)})"
        if seed is not None
        else f"USING SAMPLE {int(n)} ROWS"
    )

    # Two-step strategy to avoid OOM at corpus scale: build a thin
    # metadata CTE (no text column), sample from it, then join ``pdfs``
    # to fetch text only for the n sampled rows. Sampling from
    # ``pdfs_substantive`` directly OOMs because the view's UNION ALL
    # + LEFT JOIN materialises the full text inline before sampling.
    sql = f"""
        WITH meta AS (
            SELECT a.classe, a.processo_id, a.link_tipo AS doc_type,
                   a.link_url_sha1 AS sha1, a.link_url AS url, p.n_chars
            FROM andamentos a
            LEFT JOIN pdfs p ON a.link_url_sha1 = p.sha1
            WHERE a.link_url IS NOT NULL
              AND a.link_tipo IN (
                  'DECISÃO MONOCRÁTICA',
                  'INTEIRO TEOR DO ACÓRDÃO',
                  'MANIFESTAÇÃO DA PGR',
                  'DESPACHO'
              )

            UNION ALL

            SELECT d.classe, d.processo_id, d.doc_type,
                   d.url_sha1 AS sha1, d.url,
                   CAST(length(d.text) AS INTEGER) AS n_chars
            FROM documentos d
            WHERE d.url IS NOT NULL
              AND d.doc_type IN ('Voto', 'Relatório', 'Voto Vogal', 'Voto Vista')
        ),
        sampled AS (
            SELECT ps.classe, ps.processo_id, ps.doc_type, ps.sha1,
                   ps.url, ps.n_chars
            FROM meta ps
            {where_clause}
            {sample_clause}
        )
        SELECT s.classe, s.processo_id, s.doc_type, s.sha1, s.url,
               s.n_chars, SUBSTR(p.text, 1, {preview_chars}) AS text_preview
        FROM sampled s
        LEFT JOIN pdfs p ON s.sha1 = p.sha1
    """
    rows = con.execute(sql, params).fetchall()

    return [
        PecaSample(
            classe=classe_,
            processo_id=processo_id,
            doc_type=doc_type_,
            sha1=sha1,
            url=url,
            n_chars=n_chars,
            text_preview=text_preview or "",
            is_suspicious_short=is_suspicious_short(n_chars, doc_type_),
        )
        for (classe_, processo_id, doc_type_, sha1, url, n_chars, text_preview) in rows
    ]


def render_samples(samples: list[PecaSample]) -> str:
    """Pretty-print a list of samples for the CLI.

    Two lines per sample (header + preview). Suspicious-short rows
    get a leading ``⚠``.
    """
    if not samples:
        return "(nenhuma peça correspondeu aos filtros)\n"

    lines: list[str] = []
    n_suspicious = sum(1 for s in samples if s.is_suspicious_short)
    lines.append(
        f"{len(samples)} peças amostradas · {n_suspicious} suspeitas-curtas\n"
    )
    for s in samples:
        flag = "⚠ " if s.is_suspicious_short else "  "
        # n_chars can be None when bytes were never extracted (LEFT JOIN
        # miss to pdfs); render explicitly so the operator sees the gap.
        chars_str = f"{s.n_chars:,} chars" if s.n_chars is not None else "(no extract)"
        lines.append(
            f"{flag}{s.classe} {s.processo_id} · {s.doc_type or '—'} · "
            f"{chars_str} · sha1={s.sha1[:12]}…"
        )
        preview = s.text_preview.replace("\n", " ").strip()
        lines.append(f"    {preview[:160]!r}")
    return "\n".join(lines) + "\n"
