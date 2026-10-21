"""Manifest-stage skill-scope filter.

Each actor-profile skill (`relatorio-advogado`, `relatorio-relator`)
ships its own filter constants — which doc_types are intrinsically not
this actor's voice, and which doc_types need a chars floor to weed out
routine procedural variants. This module holds the *shape* of those
filters (one helper function); the constants live per-skill so adding
a third actor doesn't fight a unified table.

Empirical anchor: Toron HC anchor run, 421 subagent calls produced
166 skips (39 %). The post-mortem identified two filterable classes:

  - MANIFESTAÇÃO DA PGR / DECISÃO DE JULGAMENTO: 100 % opposing-voice
    or extrato-de-ata for a defense-lawyer profile. Filter unconditional.
  - Short DESPACHO / short DJE: routine procedural orders (abra-se vista,
    concedo prazo) with median chars 905 vs. 3,679 for the substantive
    minority. Filter via a chars floor.

Design note — **denylist shape only**. This helper implements the
*denylist + chars-floor* filter pattern. It's the right shape for
profiles that start with a broad manifest and exclude noise
(`relatorio-advogado`: drop PGR + short Despachos).

The sibling skill `relatorio-relator` uses an **allowlist** pattern
instead — only DECISÃO MONOCRÁTICA / INTEIRO TEOR DO ACÓRDÃO / ACÓRDÃO
/ VOTO / DECISÃO DE JULGAMENTO are kept, with weights. That's a
different *shape*, not just different *constants*, so it lives in
`relatorio-relator/summarize.py` directly and doesn't import this
helper. Forcing both into a unified entry point would conflate two
genuinely different selection strategies; instead, the library offers
this denylist helper for skills that want it (advogado today; a
hypothetical PGR-profile or Defensoria-profile skill in the future)
and other skills implement their own shape inline.
"""
from __future__ import annotations

from typing import Iterable


def skill_filter_reason(
    doc_type: str,
    chars: int,
    *,
    irrelevant_doc_types: Iterable[str] = (),
    doc_type_chars_floor: dict[str, int] | None = None,
) -> str | None:
    """Return a short reason string if the peça should be filtered, else ``None``.

    Parameters
    ----------
    doc_type, chars
        The peça's metadata (from manifest / audit row).
    irrelevant_doc_types
        Set / iterable of doc_type strings to drop unconditionally.
        Matched as exact strings against the trimmed input.
    doc_type_chars_floor
        Optional ``{doc_type: min_chars}`` map. Peças of the listed
        doc_type with ``chars < min_chars`` are filtered with reason
        ``below_chars_floor(<N>)``.
    """
    dt = (doc_type or "").strip()
    irrelevant = set(irrelevant_doc_types)
    if dt in irrelevant:
        return "irrelevant_doc_type"
    floors = doc_type_chars_floor or {}
    floor = floors.get(dt)
    if floor is not None and chars < floor:
        return f"below_chars_floor({floor})"
    return None
