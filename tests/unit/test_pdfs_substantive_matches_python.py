"""Pin the equivalence between Python ``filter_substantive`` and the
warehouse SQL view ``pdfs_substantive``.

The two encode the same "which peça doc_types are worth keeping?"
policy in different languages — Python as a tier-C blacklist, SQL as
a tier-A/B allowlist. Drift between them produces silent count gaps
between "what the runner downloaded" and "what the warehouse counts
as substantive," which would survive into research outputs without
surfacing as a runtime error.

The two policies are NOT strictly equivalent on unseen tipos — Python
fails open (keep unknown), SQL fails closed (drop unknown). That's
documented and intentional. What this file pins is the *intersection*:

* every tipo the SQL view kept must be known to Python as tier-A or
  tier-B (no orphan SQL allowlist entries),
* every tier-A tipo with an andamento-side mention must be in the
  SQL's andamento allowlist (no silently-dropped argumentation),
* every Python tier-A session-virtual tipo must be in the SQL's
  ``documentos`` allowlist,
* every tier-B tipo (whose Python contract is "keep at download,
  filter at warehouse with a length gate") must appear in the SQL
  with a length-gate clause — not silently dropped.
"""

from __future__ import annotations

import re

import pytest

from judex.sweeps.peca_classification import (
    TIER_A_DOC_TYPES,
    TIER_B_DOC_TYPES,
    TIER_C_DOC_TYPES,
)
from judex.warehouse.builder import _SCHEMA_SQL


# Andamentos-side tier-A members (uppercase tipos served via
# ``andamentos[].link_tipo``). The other tier-A tipos are
# session-virtual (title case, served via ``documentos[].doc_type``).
_ANDAMENTO_TIER_A = frozenset({
    "DECISÃO MONOCRÁTICA",
    "INTEIRO TEOR DO ACÓRDÃO",
    "MANIFESTAÇÃO DA PGR",
})
_SESSAO_VIRTUAL_TIER_A = TIER_A_DOC_TYPES - _ANDAMENTO_TIER_A


def _extract_pdfs_substantive_block() -> str:
    """Slice the ``CREATE VIEW pdfs_substantive AS ... ;`` block out of
    the schema string. Anchors on the next ``CREATE`` after the view's
    semicolon — robust to additional clauses being added inside.
    """
    m = re.search(
        r"CREATE VIEW pdfs_substantive AS(.*?);",
        _SCHEMA_SQL,
        re.DOTALL,
    )
    assert m is not None, (
        "pdfs_substantive view not found in _SCHEMA_SQL — has the "
        "view been renamed or removed?"
    )
    return m.group(1)


def _string_literals_in(block: str) -> set[str]:
    """Pull every single-quoted string literal from a SQL block. Good
    enough for the view we care about — no nested quotes, no escapes."""
    return set(re.findall(r"'([^']+)'", block))


@pytest.fixture(scope="module")
def view_block() -> str:
    return _extract_pdfs_substantive_block()


@pytest.fixture(scope="module")
def view_doc_types(view_block: str) -> set[str]:
    """Every string literal in the view block, minus the schema
    constants (``'A'``, ``'B'`` tier labels; ``'andamento'``,
    ``'sessao_virtual'`` source markers). What's left is the doc_type
    allowlist the view enforces."""
    literals = _string_literals_in(view_block)
    schema_noise = {"A", "B", "andamento", "sessao_virtual"}
    return literals - schema_noise


def test_view_allowlist_is_known_python_tier_a_or_b(
    view_doc_types: set[str],
) -> None:
    """Every doc_type the SQL view names must be classified as tier A
    or B on the Python side. An orphan SQL entry would mean the
    warehouse silently includes a tipo the runner doesn't recognise —
    a downstream count would diverge from anything computed on the
    Python representation of the same corpus.
    """
    python_substantive = TIER_A_DOC_TYPES | TIER_B_DOC_TYPES
    orphans = view_doc_types - python_substantive
    assert not orphans, (
        f"SQL pdfs_substantive view names doc_types not in Python "
        f"TIER_A ∪ TIER_B: {sorted(orphans)}. Either add them to the "
        f"Python tiers (and update tests/docs) or remove them from the "
        f"view."
    )


def test_andamento_tier_a_is_in_view(view_doc_types: set[str]) -> None:
    """Every andamento-surface tier-A tipo must appear in the view's
    allowlist. A missing entry would mean the warehouse drops
    argumentation the runner correctly downloaded — invisible to
    SELECT-based analysis."""
    missing = _ANDAMENTO_TIER_A - view_doc_types
    assert not missing, (
        f"Andamento-side tier-A tipos missing from pdfs_substantive "
        f"view: {sorted(missing)}. The warehouse will silently drop "
        f"these from substantive counts."
    )


def test_session_virtual_tier_a_is_in_view(view_doc_types: set[str]) -> None:
    """Every session-virtual tier-A tipo (Voto / Relatório / Voto Vogal
    / Voto Vista) must appear in the view's ``documentos`` allowlist.
    Same failure mode as the andamento check, on the other surface."""
    missing = _SESSAO_VIRTUAL_TIER_A - view_doc_types
    assert not missing, (
        f"Session-virtual tier-A tipos missing from pdfs_substantive "
        f"view: {sorted(missing)}. The warehouse will silently drop "
        f"these from substantive counts."
    )


@pytest.mark.xfail(
    reason=(
        "Known drift: 'DECISÃO DE JULGAMENTO' is Python TIER_B but the "
        "pdfs_substantive view omits it entirely. Resolution requires "
        "the empirical sampling in "
        "docs/reports/2026-04-23-peca-tipo-tier-validation.md to pick "
        "between (a) add to SQL with a length gate (which threshold?) "
        "or (b) demote to TIER_C in peca_classification.py. The "
        "module docstring's own 'tier-C — ...decisão-de-julgamento "
        "stubs' line suggests (b) may be the intended end state."
    ),
    strict=True,
)
def test_tier_b_is_in_view_with_length_gate(
    view_block: str, view_doc_types: set[str],
) -> None:
    """Tier B's contract is "keep at download, filter at warehouse with
    a length gate". Two failure modes the test catches:

    1. **Silent drop**: a tier-B tipo isn't in the view at all. The
       runner downloads it, the warehouse never sees it as substantive.
    2. **Hard include**: a tier-B tipo is in the view *without* a
       length gate — would over-include the boilerplate end of the
       distribution that the tier contract specifically wants gated
       out at warehouse time.

    The length-gate detection is heuristic: we look for ``n_chars``
    in the same conjunctive clause as the tipo's string literal.
    """
    missing = TIER_B_DOC_TYPES - view_doc_types
    assert not missing, (
        f"Tier-B tipos missing from pdfs_substantive view: "
        f"{sorted(missing)}. Their Python contract says they're "
        f"substantive (with a query-time length gate); the SQL "
        f"currently drops them entirely. Either add them with a "
        f"length-gate clause, or move them to TIER_C_DOC_TYPES."
    )

    for tipo in TIER_B_DOC_TYPES:
        clause_pat = re.compile(
            r"a\.link_tipo\s*=\s*'" + re.escape(tipo) + r"'\s+AND\s+"
            r"\([^)]*n_chars[^)]*\)",
            re.DOTALL,
        )
        assert clause_pat.search(view_block), (
            f"Tier-B tipo {tipo!r} appears in the view but without a "
            f"length-gate clause. Either gate it (e.g. "
            f"``AND (p.n_chars IS NULL OR p.n_chars > N)``) or move "
            f"it to TIER_C_DOC_TYPES."
        )


def test_tier_c_never_appears_in_view(view_doc_types: set[str]) -> None:
    """The view's positive-list shape (allow tier A + B) plus the
    tier-C blacklist must agree: no tier-C tipo should ever appear in
    the view's allowlist. A drift would mean the warehouse counts
    boilerplate as substantive while the runner refused to download
    it — an empty-by-design row in the warehouse, with no way to tell
    it's a definition gap rather than a coverage gap.
    """
    leaks = TIER_C_DOC_TYPES & view_doc_types
    assert not leaks, (
        f"Tier-C tipos found in pdfs_substantive view: {sorted(leaks)}. "
        f"The runner drops these by default; the warehouse counting "
        f"them as substantive will produce empty-by-design rows."
    )
