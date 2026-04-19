"""Derive a coarse outcome label from assembled item data.

Unlike the fragment extractors this one takes the assembled StfItem
dict (sessao_virtual + andamentos) and returns a small provenance
record, so downstream analysis can tell HC-main-verdict from
HC-AgR-verdict apart. Verdict vocabulary lives in
`src.analysis.legal_vocab.VERDICT_PATTERNS`.
"""

from __future__ import annotations

from typing import Optional

from src.analysis.legal_vocab import VERDICT_PATTERNS
from src.data.types import OutcomeInfo
from src.scraping.extraction._shared import to_iso


def derive_outcome(item: dict) -> Optional[OutcomeInfo]:
    """Return {verdict, source, source_index, date_iso} or None.

    Checks sessao_virtual[-1].voto_relator first (later sessions override
    earlier ones), then falls back to scanning andamentos nome+complemento
    newest-first. Returns None when nothing matches the verdict vocabulary.
    """
    sv = item.get("sessao_virtual") or []
    if isinstance(sv, list) and sv:
        last_idx = len(sv) - 1
        last = sv[last_idx]
        if isinstance(last, dict):
            voto = (last.get("voto_relator") or "").strip()
            if voto:
                verdict = _match_verdict(voto)
                if verdict is not None:
                    return _outcome_from_sessao(last, verdict, last_idx)

    for a in item.get("andamentos") or []:
        if not isinstance(a, dict):
            continue
        blob = f"{a.get('nome', '')}\n{a.get('complemento', '') or ''}"
        verdict = _match_verdict(blob)
        if verdict is not None:
            return OutcomeInfo(
                verdict=verdict,
                source="andamentos",
                source_index=int(a.get("index_num") or 0),
                date_iso=a.get("data_iso") or to_iso(a.get("data")),
            )

    return None


def _match_verdict(text: str) -> Optional[str]:
    for pattern, label in VERDICT_PATTERNS:
        if pattern.search(text):
            return label
    return None


def _outcome_from_sessao(session: dict, verdict: str, index: int) -> OutcomeInfo:
    # sessao_virtual metadata uses Portuguese keys; the accented spelling
    # is what the live scraper + fixtures emit (HC_158802 etc.).
    meta = session.get("metadata") or {}
    raw = (
        meta.get("data_início")
        or meta.get("data_inicio")
        or meta.get("data_prevista_fim")
    )
    return OutcomeInfo(
        verdict=verdict,
        source="sessao_virtual",
        source_index=index,
        date_iso=to_iso(raw),
    )
