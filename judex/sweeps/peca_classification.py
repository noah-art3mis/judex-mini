"""Peça tipo classification — shared between ``baixar-pecas`` (download-time
filter) and ``judex/warehouse/builder.py`` (query-time view).

Three tiers, ordered by argumentative content per byte:

* **Tier A — substantive (always keep).** Where legal reasoning lives.
  Three andamento-side tipos (``DECISÃO MONOCRÁTICA`` ~7.9k chars
  median, ``INTEIRO TEOR DO ACÓRDÃO`` ~11.2k, ``MANIFESTAÇÃO DA PGR``
  ~10.1k — filter the last to ``n_chars > 1000`` to drop "CIENTE"
  stamps) plus four session-virtual ``documentos`` tipos (``Voto``,
  ``Relatório``, ``Voto Vogal``, ``Voto Vista``).
* **Tier B — mixed (keep at the download layer; filter at query
  time).** ``DESPACHO`` and ``DECISÃO DE JULGAMENTO``: content varies
  within the same tipo, so the warehouse view applies a length gate
  (``n_chars > 1500`` for Despacho) rather than blanket-skipping.
* **Tier C — boilerplate (skip by default).** Certidões, termos,
  intimações, comunicações, decisão-de-julgamento stubs. ~131k of the
  237k HC-corpus PDFs are tier C; skipping them at ``baixar-pecas``
  saves ~55% of HTTP requests (and proportional WAF exposure). Their
  content is either a standard template or data already structured in
  ``cases`` / ``andamentos`` / ``outcome``.

**Redundancy note.** ``INTEIRO TEOR DO ACÓRDÃO`` is the compiled form
of ``Voto`` + ``Relatório`` + ``Voto Vogal`` + ``Voto Vista`` for the
same case. When both are present, prefer Inteiro Teor (one PDF,
complete picture); the individual votes are the fallback when Inteiro
Teor is missing (still being compiled, or capture gap).

**Matching is case- and accent-insensitive.** Both sides of the
comparison are folded via Unicode NFKD + combining-mark strip +
uppercase + strip, so labeling drift like ``"CERTIDAO"`` or
``"Certidão"`` still matches the canonical ``"CERTIDÃO"`` entry.
Empirically the current corpus has zero case/accent variants (verified
2026-04-23: 17 distinct tipos, all uniformly uppercase + canonically
accented), so the fold is pure defense — zero current silent misses
caught, but a future STF rename (e.g. portal migration to lowercase
labels) won't silently re-enable the filter for the renamed tipo.

**Policy on unseen tipos: fail-open.** Anything outside ``KNOWN_DOC_TYPES``
passes through ``filter_substantive`` — both ``None`` (pre-download
ambiguity) and a brand-new STF label. The worst case is wasting some
HTTP requests on a new stub until ``summarize_tipos`` warns about it
at sweep launch; there is never silent data loss. If a new tipo turns
out to be procedural, sample a few PDFs and add it to ``TIER_C_DOC_TYPES``.

**Scope.** HC peça PDFs reached via ``andamentos.link_url`` (served by
``portal.stf.jus.br/processos/downloadPeca.asp``) and session-virtual
documents reached via ``cases.sessao_virtual[].documentos[].url``.
Does *not* cover DJe RTFs under ``decisoes_dje.rtf_url`` — separate
pipeline; classification is premature until the DJe backfill lands.

See ``docs/peca-tipo-classification.md`` for the warehouse view's
``pdfs_substantive`` SQL and operator-facing CLI semantics, and
``docs/reports/2026-04-23-peca-tipo-tier-validation.md`` for the
empirical row-count / median-char / sampling methodology snapshot
that backs the tier assignments.
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
#
# First three are `andamentos[].link.tipo` values (surface 1, ALL CAPS).
# Last four are `sessao_virtual[].documentos[].tipo` values (surface 2,
# title case) — added when ADR-0001 promoted that surface to a
# first-class peça source. All seven are intrinsically argumentative;
# see docs/peca-tipo-classification.md § Tier A for the per-tipo
# rationale and the redundancy note vs. INTEIRO TEOR DO ACÓRDÃO.
TIER_A_DOC_TYPES: frozenset[str] = frozenset({
    "DECISÃO MONOCRÁTICA",
    "INTEIRO TEOR DO ACÓRDÃO",
    "MANIFESTAÇÃO DA PGR",
    "Voto",
    "Relatório",
    "Voto Vogal",
    "Voto Vista",
})

# Tier B — mixed; kept at the download layer (length gate is post-hoc in
# the warehouse view).
TIER_B_DOC_TYPES: frozenset[str] = frozenset({
    "DESPACHO",
    "DECISÃO DE JULGAMENTO",
})

# Tier C — procedural boilerplate. Skip by default on `baixar-pecas`.
TIER_C_DOC_TYPES: frozenset[str] = frozenset({
    "CERTIDÃO DE TRÂNSITO EM JULGADO",
    "CERTIDÃO",
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
