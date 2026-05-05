"""Heuristics for spotting silent extraction failures in peças.

The unified pipeline marks an extraction ``empty`` only when ``chars
== 0``. In practice pypdf often returns a few characters of header
metadata (e.g. ``"Voto-Vista"`` — 10 chars — observed on
``5843d6d8…txt.gz``) and reports success despite never extracting the
document body. The runner can't distinguish that from a legitimate
short peça (a one-line ``CERTIDÃO``).

This module's :func:`is_suspicious_short` answers "would a substantive
peça plausibly be this short?" — the basis for the registry's
``is_suspicious_short`` column (.scratch/peca-registry/PRD.md sub-issue
02).
"""

from __future__ import annotations

from typing import Optional


# Doc-type labels (uppercase, accent-removed where it varies in the
# corpus) where extracted text below the threshold below is almost
# certainly a silent extraction failure. Substantive types only —
# procedural peças (CERTIDÃO, INTIMAÇÃO, COMUNICAÇÃO ASSINADA, …) can
# legitimately be short, so they're absent from this set.
_SUSPICIOUS_DOC_TYPES: frozenset[str] = frozenset({
    "DECISÃO MONOCRÁTICA", "DECISAO MONOCRATICA",
    "ACÓRDÃO", "ACORDAO",
    "INTEIRO TEOR DO ACÓRDÃO", "INTEIRO TEOR DO ACORDAO",
    "VOTO", "VOTO-VISTA",
    "RELATÓRIO", "RELATORIO",
    "PARECER",
    "PETIÇÃO INICIAL", "PETICAO INICIAL",
    "DECISÃO DE JULGAMENTO", "DECISAO DE JULGAMENTO",
    "DESPACHO",
})

# Minimum chars expected for a substantive peça. Below this, the
# extraction almost certainly missed the body. 200 is conservative —
# even short DECISÃO MONOCRÁTICAs run to a few hundred characters; the
# ``Voto-Vista`` (10 chars) and ``Plenário Virtual - minuta de voto -
# 22/02/2021`` (47 chars) cases observed on disk are the canonical
# failure modes this threshold catches.
SUSPICIOUS_THRESHOLD_CHARS: int = 200


def is_suspicious_short(chars: int, doc_type: Optional[str]) -> bool:
    """True if a peça's extracted text is suspiciously short.

    Heuristic for the pypdf silent-failure pattern (chars > 0 but the
    text is just header metadata, missing the document body). Returns
    False for procedural doc_types (CERTIDÃO, INTIMAÇÃO, etc.) where
    short text is expected, and for unknown / ``None`` doc_types where
    no threshold applies.
    """
    if doc_type is None:
        return False
    upper = doc_type.upper().strip()
    if upper not in _SUSPICIOUS_DOC_TYPES:
        return False
    return chars < SUSPICIOUS_THRESHOLD_CHARS
