"""Peça tipo classification — shared between `baixar-pecas` (download-time
filter) and `judex/warehouse/builder.py` (query-time view).

The tier-C list below is the exclusion set used by the default
``--apenas-substantivas`` filter on ``baixar-pecas``: all are
procedural boilerplate (certidões, termos, intimações, comunicações,
decisão-de-julgamento stubs) whose content is either a standard
template or data already structured in ``cases`` / ``andamentos``.

**Matching is case- and accent-insensitive.** Both sides of the
comparison are folded via Unicode NFKD + combining-mark strip +
uppercase + strip, so labeling drift like ``"CERTIDAO"`` or
``"Certidão"`` still matches the canonical ``"CERTIDÃO"`` entry.

See ``docs/peca-tipo-classification.md`` for tier definitions,
per-tipo content notes, and the validation sampling that backs this
list.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Iterable


def _fold(s: str | None) -> str:
    """Case- and accent-insensitive canonical form for tipo matching.

    NFKD decomposes accented characters into base + combining marks;
    dropping combining marks strips the accent. ``upper().strip()``
    handles case + surrounding whitespace. Returns ``""`` for None
    so the caller's membership check is a clean no-match.
    """
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).upper().strip()


# Tier A — substantive argumentation. Always kept.
TIER_A_DOC_TYPES: frozenset[str] = frozenset({
    "DECISÃO MONOCRÁTICA",
    "INTEIRO TEOR DO ACÓRDÃO",
    "MANIFESTAÇÃO DA PGR",
})

# Tier B — mixed; kept at the download layer (length gate is post-hoc in
# the warehouse view).
TIER_B_DOC_TYPES: frozenset[str] = frozenset({
    "DESPACHO",
})

# Tier C — procedural boilerplate. Skip by default on `baixar-pecas`.
TIER_C_DOC_TYPES: frozenset[str] = frozenset({
    "CERTIDÃO DE TRÂNSITO EM JULGADO",
    "CERTIDÃO",
    "DECISÃO DE JULGAMENTO",
    "COMUNICAÇÃO ASSINADA",
    "CERTIDÃO DE JULGAMENTO",
    "TERMO DE REMESSA",
    "VISTA À PGR",
    "TERMO DE BAIXA",
    "INTIMAÇÃO",
    "VISTA À PARTE EMBARGADA",
    "VISTA À PARTE AGRAVADA",
    "OUTRAS PEÇAS",
    "CERTIDÃO DE DECURSO DE PRAZO PARA RESPOSTA",
})

# Every tipo we've observed & classified. Anything outside this set is
# "unseen" and triggers the pre-flight diagnostic in `baixar-pecas`.
KNOWN_DOC_TYPES: frozenset[str] = (
    TIER_A_DOC_TYPES | TIER_B_DOC_TYPES | TIER_C_DOC_TYPES
)

# Precomputed folded sets — avoids re-folding the constants on every call.
_TIER_C_FOLDED: frozenset[str] = frozenset(_fold(s) for s in TIER_C_DOC_TYPES)
_KNOWN_FOLDED: frozenset[str] = frozenset(_fold(s) for s in KNOWN_DOC_TYPES)


def filter_substantive(targets: Iterable) -> list:
    """Drop targets whose ``doc_type`` matches a tier-C entry.

    **Policy: fail-open on genuinely new tipos.** Match is
    case/accent-insensitive (see module docstring), so ``"certidao"``
    and ``"CERTIDÃO"`` both drop. But a tipo that folds to something
    not in ``TIER_C_DOC_TYPES`` — whether ``None`` (pre-download
    ambiguity) or a brand-new STF label — passes through. This
    guarantees no silent data loss on labeling reforms; worst case is
    wasting HTTP requests on an unclassified stub until someone
    notices it via the warehouse's ``SELECT DISTINCT link_tipo`` or
    the unseen-tipos warning printed at sweep start.
    """
    return [t for t in targets if _fold(t.doc_type) not in _TIER_C_FOLDED]


def summarize_tipos(
    targets: Iterable, *, top_n: int = 5
) -> tuple[list[tuple[str | None, int]], dict[str, int]]:
    """Return ``(top_tipos_by_count, unseen_tipos_with_counts)``.

    - ``top_tipos_by_count``: the ``top_n`` most common ``doc_type``
      values across ``targets``, including ``None``. Used for a
      one-line pre-flight summary so operators see the shape of what
      they're about to download.
    - ``unseen_tipos_with_counts``: every ``doc_type`` that folds to
      something not in ``KNOWN_DOC_TYPES`` (excluding ``None``, which
      is a separate non-classifiable signal). Used to warn about
      tipos introduced by STF since the classification was last
      refreshed.
    """
    counts: Counter[str | None] = Counter(t.doc_type for t in targets)
    top = counts.most_common(top_n)
    unseen: dict[str, int] = {
        tipo: n for tipo, n in counts.items()
        if tipo is not None and _fold(tipo) not in _KNOWN_FOLDED
    }
    return top, unseen
