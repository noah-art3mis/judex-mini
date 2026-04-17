"""Derive a coarse outcome label from assembled item data.

Unlike the fragment extractors this one takes the assembled StfItem
dict (sessao_virtual + andamentos). Verdict vocabulary lives in
`src.analysis.legal_vocab.VERDICT_PATTERNS`.
"""

from __future__ import annotations

from typing import Optional

from src.analysis.legal_vocab import VERDICT_PATTERNS


def derive_outcome(item: dict) -> Optional[str]:
    """Return a verdict label, or None for pending/unclassified cases."""
    # 1. sessao_virtual: check the LAST session's voto_relator text.
    #    A later session overrides any earlier ones.
    sv = item.get("sessao_virtual") or []
    if isinstance(sv, list) and sv:
        last = sv[-1]
        if isinstance(last, dict):
            voto = (last.get("voto_relator") or "").strip()
            if voto:
                outcome = _match_verdict(voto)
                if outcome is not None:
                    return outcome

    # 2. andamentos fallback: scan nome+complemento for verdict phrases.
    for a in item.get("andamentos") or []:
        if not isinstance(a, dict):
            continue
        blob = f"{a.get('nome', '')}\n{a.get('complemento', '') or ''}"
        outcome = _match_verdict(blob)
        if outcome is not None:
            return outcome

    return None


def _match_verdict(text: str) -> Optional[str]:
    for pattern, label in VERDICT_PATTERNS:
        if pattern.search(text):
            return label
    return None
