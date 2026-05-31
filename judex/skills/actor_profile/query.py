"""Query helper over Stage 2b subagent summaries.

Used during Stage 3 (synthesis) to spot-check a volume of breadth-pass
output without re-reading peça text. Each subagent emits a structured
record per peça (teses, registro, fundamentos, padrão retórico,
resultado, relevância); this helper joins those records to the
manifest (case, doc_type, surface, chars) and lets the synthesis agent
filter by structured fields.

Empirical anchor: the same Toron run that motivated the tripwire also
demonstrated **misattribution by inference-without-consultation** —
the narrative grouped HC 252.920 under the "art. 312 CPP / fundamentação
genérica" register, but all 3 analysed peças for that case carry
``registro = "constitucional"`` with ``fundamentos = ["art. 29, X, CF",
"art. 77, I, CPP"]``. The error was catchable in seconds via this query:

    rows = query_summaries(
        internal=Path("…/internal"),
        case="HC 252920",
        fields=("registro", "fundamentos"),
    )

The function is intentionally **cheap to call**: ``fields`` cuts each
row to the requested keys (drops the ~500-token padrão-retórico /
trecho-notável fields when only registro / resultado are needed). Use
``n`` + ``seed`` for random sampling.
"""
from __future__ import annotations

import json
import pathlib
import random
from typing import Iterable


def _load_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _as_set(x: str | Iterable[str] | None) -> set[str] | None:
    if x is None:
        return None
    if isinstance(x, str):
        return {x.lower()}
    return {s.lower() for s in x}


def _has(needle: str | None, hay) -> bool:
    if not needle:
        return True
    hay_s = " ".join(hay) if isinstance(hay, list) else (hay or "")
    return needle.lower() in hay_s.lower()


def query_summaries(
    internal: pathlib.Path,
    *,
    # filters on manifest-level fields (joined from manifest.jsonl)
    case: str | None = None,
    doc_type: str | Iterable[str] | None = None,
    surface: str | Iterable[str] | None = None,
    # filters on summary-level fields
    registro: str | Iterable[str] | None = None,
    resultado: str | Iterable[str] | None = None,
    relevancia: str | Iterable[str] | None = None,
    # substring matches across the structured prose fields
    tese_contains: str | None = None,
    fundamento_contains: str | None = None,
    precedente_contains: str | None = None,
    notavel_contains: str | None = None,
    retorico_contains: str | None = None,
    # skip handling
    include_skipped: bool = False,
    only_skipped: bool = False,
    # sampling
    n: int | None = None,
    seed: int | None = None,
    # output shape
    fields: Iterable[str] | None = None,
) -> list[dict]:
    """Return flat rows joining manifest + summaries; one row per peça SHA.

    All filters AND-combine. Substring matches are case-insensitive.
    ``n`` caps the result; if ``seed`` is set, the cap is a uniform
    sample (Random(seed).shuffle then slice).

    The manifest is read once and deduped by SHA (defensive against the
    duplicate-row bug observed in early manifest builds; a SHA that
    appears twice in manifest.jsonl yields one row in the output).
    """
    mfst = {m["sha"]: m for m in _load_jsonl(internal / "manifest.jsonl")}
    summ = {
        s["sha"]: (s.get("summary") or {})
        for s in _load_jsonl(internal / "summaries.jsonl")
    }

    reg_set, res_set, rel_set = map(_as_set, (registro, resultado, relevancia))
    dt_set, surf_set = map(_as_set, (doc_type, surface))

    out: list[dict] = []
    for sha, s in summ.items():
        m = mfst.get(sha)
        if not m:
            continue
        is_skip = bool(s.get("skip"))
        if only_skipped and not is_skip:
            continue
        if is_skip and not (include_skipped or only_skipped):
            continue

        if case and case not in m["case"]:
            continue
        if dt_set and (m.get("doc_type") or "").lower() not in dt_set:
            continue
        if surf_set and (m.get("surface") or "").lower() not in surf_set:
            continue

        if not is_skip:
            if reg_set and (s.get("registro") or "").lower() not in reg_set:
                continue
            if res_set and (s.get("resultado_caso") or "").lower() not in res_set:
                continue
            if rel_set and (s.get("relevancia") or "").lower() not in rel_set:
                continue
            if not _has(tese_contains,        s.get("teses_impetrante")):       continue
            if not _has(fundamento_contains,  s.get("fundamentos_invocados")):  continue
            if not _has(precedente_contains,  s.get("precedentes_citados")):    continue
            if not _has(notavel_contains,     s.get("trecho_notavel")):         continue
            if not _has(retorico_contains,    s.get("padrao_retorico")):        continue

        row = {
            "sha": sha,
            "case": m["case"],
            "doc_type": m.get("doc_type"),
            "surface": m.get("surface"),
            "chars": m.get("chars"),
            "skip": is_skip,
            "skip_reason": s.get("reason") if is_skip else None,
            "registro": s.get("registro"),
            "resultado_caso": s.get("resultado_caso"),
            "relevancia": s.get("relevancia"),
            "teses": s.get("teses_impetrante", []),
            "fundamentos": s.get("fundamentos_invocados", []),
            "precedentes": s.get("precedentes_citados", []),
            "padrao_retorico": s.get("padrao_retorico"),
            "trecho_notavel": s.get("trecho_notavel"),
        }
        if fields:
            keep = set(fields) | {"sha", "case"}
            row = {k: v for k, v in row.items() if k in keep}
        out.append(row)

    if n is not None and len(out) > n:
        if seed is not None:
            random.Random(seed).shuffle(out)
        out = out[:n]
    return out
