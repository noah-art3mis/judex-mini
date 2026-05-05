"""Tests for the suspicious-short detector.

Pins the contract from .scratch/peca-registry/PRD.md sub-issue 02:
flag substantive peças with short extracted text as likely
silent-extraction failures, leave procedural and unknown doc-types
alone.
"""
from __future__ import annotations

import pytest

from judex.analysis.peca_quality import is_suspicious_short


@pytest.mark.parametrize("chars,doc_type,expected", [
    # Canonical failure modes observed on disk (see file docstring of
    # peca_quality.py): ~10-50 chars of header text on a substantive
    # doc_type. Both must trigger.
    (10, "VOTO", True),                    # the 5843d6d8…txt.gz case
    (47, "VOTO", True),                    # the feb32c24…txt.gz case
    (50, "DECISÃO MONOCRÁTICA", True),
    (199, "ACÓRDÃO", True),                # one below threshold
    # Substantive peças at or above threshold are *not* suspicious —
    # short but plausibly real content.
    (200, "DECISÃO MONOCRÁTICA", False),   # at threshold
    (5_000, "DECISÃO MONOCRÁTICA", False),
    (30_000, "VOTO", False),
    # Procedural peças can legitimately be short — must NOT flag.
    (50, "CERTIDÃO", False),
    (10, "INTIMAÇÃO", False),
    (5, "COMUNICAÇÃO ASSINADA", False),
    # Unknown doc_type — no threshold applies.
    (5, "WEIRD_TYPE", False),
    (5, "", False),
    (5, None, False),
    # Accent-insensitive on the canonical pairs (ACÓRDÃO/ACORDAO,
    # DECISÃO/DECISAO etc.). Both should match.
    (50, "ACORDAO", True),
    (50, "DECISAO MONOCRATICA", True),
    (50, "RELATORIO", True),
    # Case-insensitive (operator might query with lowercase).
    (50, "voto", True),
    (50, "decisão monocrática", True),
])
def test_is_suspicious_short(
    chars: int, doc_type: str | None, expected: bool,
) -> None:
    assert is_suspicious_short(chars, doc_type) == expected


def test_threshold_is_load_bearing_constant() -> None:
    """The threshold must be importable so callers (warehouse builder,
    spot-check CLI) can document it. Pinning the import path keeps
    refactors honest."""
    from judex.analysis.peca_quality import SUSPICIOUS_THRESHOLD_CHARS
    assert SUSPICIOUS_THRESHOLD_CHARS == 200


def test_zero_chars_is_suspicious_too() -> None:
    """``chars == 0`` is already caught upstream by the runner's ``empty``
    status, but the detector must agree (no off-by-one — the runner's
    binary check and this graded check must not contradict)."""
    assert is_suspicious_short(0, "DECISÃO MONOCRÁTICA") is True
    # Procedural still false — empty CERTIDÃO is also fine.
    assert is_suspicious_short(0, "CERTIDÃO") is False


def test_chars_none_is_not_suspicious() -> None:
    """When ``chars`` is None (peça never extracted — LEFT JOIN miss
    on the warehouse), the detector returns False. That's a separate
    problem (no_bytes / missing-extraction) the runner's status
    surface owns; we must not conflate it with the silent-success
    short-text pattern this detector targets."""
    assert is_suspicious_short(None, "DECISÃO MONOCRÁTICA") is False
    assert is_suspicious_short(None, "DESPACHO") is False
    assert is_suspicious_short(None, None) is False
