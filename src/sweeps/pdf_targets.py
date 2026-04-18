"""Generic PDF target collection from judex-mini output files.

Walks `judex-mini_*.json` files under one or more roots, applies
per-item filters, and emits one PdfTarget per substantive-doc URL
in the andamento list. The filter parameters (classe, impte_contains,
doc_types, relator_contains) are driven by `scripts/fetch_pdfs.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence


@dataclass
class PdfTarget:
    url: str
    processo_id: Optional[int] = None
    classe: Optional[str] = None
    doc_type: Optional[str] = None
    context: dict[str, Any] = field(default_factory=dict)


def collect_pdf_targets(
    roots: Sequence[Path],
    *,
    classe: Optional[str] = None,
    impte_contains: Sequence[str] = (),
    doc_types: Sequence[str] = (),
    relator_contains: Sequence[str] = (),
    exclude_doc_types: Sequence[str] = (),
) -> list[PdfTarget]:
    """Collect PDF targets from judex-mini output files.

    All filters AND together. Leaving a filter empty/None disables it.

    - `classe`: match exactly, e.g. "HC", "RE", "ADI".
    - `impte_contains`: any of these (case-insensitive) substrings
      appears in a `.partes[].nome` field whose `.tipo == "IMPTE.(S)"`.
    - `doc_types`: `andamento.link_descricao` must be in this set.
    - `relator_contains`: any of these substrings appears in `.relator`.
    - `exclude_doc_types`: `andamento.link_descricao` must NOT be in
      this set. Applied after `doc_types`.

    Deduplicates by URL across input files.
    """
    files = sorted({
        p for r in roots if Path(r).exists()
        for p in Path(r).rglob("judex-mini_*.json")
    })

    doc_type_set = set(doc_types) if doc_types else None
    excluded_doc_types = set(exclude_doc_types) if exclude_doc_types else None
    impte_needles = tuple(s.upper() for s in impte_contains) or None
    relator_needles = tuple(s.upper() for s in relator_contains) or None

    seen_urls: set[str] = set()
    out: list[PdfTarget] = []

    for f in files:
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        rec = d[0] if isinstance(d, list) else d

        if classe is not None and rec.get("classe") != classe:
            continue

        impte_hits: list[str] = []
        if impte_needles is not None:
            for p in rec.get("partes") or []:
                if p.get("tipo") != "IMPTE.(S)":
                    continue
                nome = (p.get("nome") or "").upper()
                for needle in impte_needles:
                    if needle in nome and needle not in impte_hits:
                        impte_hits.append(needle)
            if not impte_hits:
                continue

        if relator_needles is not None:
            rel = (rec.get("relator") or "").upper()
            if not any(n in rel for n in relator_needles):
                continue

        pid = rec.get("processo_id")
        rec_classe = rec.get("classe")

        for a in rec.get("andamentos") or []:
            link = a.get("link")
            desc = a.get("link_descricao")
            url = link.get("url") if isinstance(link, dict) else None
            if not url or not url.lower().endswith(".pdf"):
                continue
            if doc_type_set is not None and desc not in doc_type_set:
                continue
            if excluded_doc_types is not None and desc in excluded_doc_types:
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)

            ctx: dict[str, Any] = {}
            if impte_hits:
                ctx["impte_hits"] = list(impte_hits)
            out.append(PdfTarget(
                url=url,
                processo_id=pid,
                classe=rec_classe,
                doc_type=desc,
                context=ctx,
            ))
    return out
