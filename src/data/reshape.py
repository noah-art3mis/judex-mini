"""Pure JSON-to-JSON migration: v1/v2/v3 case dicts → v6 shape.

Complements `scripts/renormalize_cases.py`'s full rebuild path. The
full rebuild reruns extractors against the cached HTML fragments,
which is the source of truth — but ~78 % of the corpus has incomplete
HTML caches and short-circuits to `needs_rescrape`.

Most of the v1→v6 diff is deterministic dict surgery: list-unwrap,
key renames, date reformatting, `_meta` slot synthesis. This module
does only that, never reads the HTML cache, and is safe to apply
even when the rescrape path is unavailable.

What it cannot fix: data that was missing from the original scrape
(empty `pautas` / `recursos` when those tabs were never captured),
PDF text/extractor provenance (filled by `extrair-pecas`), or
`OutcomeInfo.source_index` when `derive_outcome` no longer matches
the verdict against the in-memory andamentos.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from src.data.types import SCHEMA_VERSION
from src.scraping.extraction.outcome import derive_outcome
from src.scraping.extraction.partes import extract_primeiro_autor


_DDMMYYYY = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_DDMMYYYY_HHMMSS = re.compile(r"^(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2}:\d{2})$")

_SESSAO_METADATA_RENAMES = {
    "data_início": "data_inicio",
    "data_prevista_fim": "data_fim_prevista",
    "relatora": "relator",
    "órgão_julgador": "orgao_julgador",
}


def reshape_to_v7(raw: Any) -> dict:
    """Top-level entry. Accepts list-wrapped or bare-dict input."""
    rec = raw[0] if isinstance(raw, list) else raw
    if not isinstance(rec, dict):
        raise TypeError(f"reshape_to_v7 expects dict or [dict], got {type(raw).__name__}")
    rec = dict(rec)  # shallow copy; nested mutators copy as needed

    rec = _migrate_meta(rec)
    rec["data_protocolo"] = _date_to_iso(_pop_with_iso(rec, "data_protocolo"))
    rec["andamentos"] = [_normalize_andamento(a) for a in rec.get("andamentos") or []]
    rec["pautas"] = [_normalize_pauta(p) for p in rec.get("pautas") or []]
    rec["deslocamentos"] = [_normalize_deslocamento(d) for d in rec.get("deslocamentos") or []]
    rec["peticoes"] = [_normalize_peticao(p) for p in rec.get("peticoes") or []]
    rec["recursos"] = [_normalize_recurso(r) for r in rec.get("recursos") or []]
    rec["sessao_virtual"] = [_normalize_sessao(s) for s in rec.get("sessao_virtual") or []]
    rec["outcome"] = _promote_outcome(rec.get("outcome"), rec)
    # v7: publicacoes_dje is a fresh-scrape-only field; renormalizer seeds
    # an empty list so downstream code can assume the key exists.
    rec["publicacoes_dje"] = rec.get("publicacoes_dje") or []
    # Re-derive primeiro_autor so AUTHOR_PARTY_TIPOS edits propagate to
    # corpus-on-disk. Fall back to whatever the record already carried
    # when partes can't surface an author (empty list or no matching tipo).
    derived = extract_primeiro_autor(rec.get("partes") or [])
    if derived is not None:
        rec["primeiro_autor"] = derived
    elif "primeiro_autor" not in rec:
        rec["primeiro_autor"] = None
    return rec


# ----- _meta slot ----------------------------------------------------------

def _migrate_meta(rec: dict) -> dict:
    existing = rec.get("_meta")
    if isinstance(existing, dict) and existing.get("schema_version") == SCHEMA_VERSION:
        # Already v6; still strip any legacy top-level provenance keys
        # in case of a half-migrated file.
        for k in ("schema_version", "status_http", "extraido"):
            rec.pop(k, None)
        return rec

    extraido = rec.pop("extraido", None) or (existing or {}).get("extraido")
    if not extraido:
        extraido = datetime.now().isoformat()
    status_http = rec.pop("status_http", None) or (existing or {}).get("status_http") or 200
    rec.pop("schema_version", None)
    rec["_meta"] = {
        "schema_version": SCHEMA_VERSION,
        "status_http": int(status_http),
        "extraido": str(extraido),
    }
    return rec


# ----- date conversion -----------------------------------------------------

def _pop_with_iso(rec: dict, key: str) -> Optional[str]:
    """Read `<key>` and `<key>_iso`, prefer the ISO sibling if present.
    Drops the `_iso` companion either way.
    """
    iso = rec.pop(f"{key}_iso", None)
    plain = rec.get(key)
    return iso or plain


def _date_to_iso(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str) or not value:
        return value if value is None else None
    if _looks_iso_date(value):
        return value
    m = _DDMMYYYY.match(value)
    if m:
        d, mth, y = m.groups()
        return f"{y}-{mth}-{d}"
    return None  # unrecognised format → drop rather than emit garbage


def _datetime_to_iso(value: Optional[str]) -> Optional[str]:
    """Handle 'DD/MM/YYYY HH:MM:SS' → 'YYYY-MM-DDTHH:MM:SS'."""
    if not isinstance(value, str) or not value:
        return value if value is None else None
    if "T" in value and _looks_iso_date(value):
        return value
    m = _DDMMYYYY_HHMMSS.match(value)
    if m:
        d, mth, y, time_part = m.groups()
        return f"{y}-{mth}-{d}T{time_part}"
    iso_day = _date_to_iso(value)
    return iso_day


def _looks_iso_date(s: str) -> bool:
    return len(s) >= 10 and s[4] == "-" and s[7] == "-" and s[:4].isdigit()


# ----- per-record normalizers ----------------------------------------------

def _normalize_andamento(raw: dict) -> dict:
    a = dict(raw)
    a["index"] = _pop_index(a)
    a["data"] = _date_to_iso(_pop_with_iso(a, "data"))
    a["link"] = _normalize_link(a.pop("link", None), a.pop("link_descricao", None))
    return {
        "index": a["index"],
        "data": a["data"],
        "nome": a.get("nome", ""),
        "complemento": a.get("complemento"),
        "julgador": a.get("julgador"),
        "link": a["link"],
    }


def _normalize_pauta(raw: dict) -> dict:
    p = dict(raw)
    return {
        "index": _pop_index(p),
        "data": _date_to_iso(_pop_with_iso(p, "data")),
        "nome": p.get("nome", ""),
        "complemento": p.get("complemento"),
        "julgador": p.get("julgador"),
    }


def _normalize_deslocamento(raw: dict) -> dict:
    d = dict(raw)
    return {
        "index": _pop_index(d),
        "guia": d.get("guia", ""),
        "recebido_por": d.get("recebido_por"),
        "data_recebido": _date_to_iso(_pop_with_iso(d, "data_recebido")),
        "enviado_por": d.get("enviado_por"),
        "data_enviado": _date_to_iso(_pop_with_iso(d, "data_enviado")),
    }


def _normalize_peticao(raw: dict) -> dict:
    p = dict(raw)
    # `recebido_data` carries time precision in the plain key; the
    # legacy `_iso` companion was date-only and would lose HH:MM:SS.
    # Prefer the plain key, then drop the companion.
    recebido_plain = p.get("recebido_data")
    p.pop("recebido_data_iso", None)
    return {
        "index": _pop_index(p),
        "id": p.get("id"),
        "data": _date_to_iso(_pop_with_iso(p, "data")),
        "recebido_data": _datetime_to_iso(recebido_plain),
        "recebido_por": p.get("recebido_por"),
    }


def _normalize_recurso(raw: dict) -> dict:
    r = dict(raw)
    # `Recurso.data` was always a label, never a date — historical misnaming.
    tipo = r.get("tipo") if "tipo" in r else r.get("data")
    return {
        "index": _pop_index(r),
        "tipo": tipo,
    }


def _normalize_sessao(raw: dict) -> dict:
    s = dict(raw)
    md = dict(s.get("metadata") or {})
    for old, new in _SESSAO_METADATA_RENAMES.items():
        if old in md and new not in md:
            md[new] = md.pop(old)
        elif old in md:
            md.pop(old)
    md["data_inicio"] = _date_to_iso(_pop_with_iso(md, "data_inicio"))
    md["data_fim_prevista"] = _date_to_iso(_pop_with_iso(md, "data_fim_prevista"))
    s["metadata"] = md
    s["documentos"] = [_normalize_documento(d) for d in s.get("documentos") or []]
    return s


def _normalize_documento(raw: Any) -> dict:
    if isinstance(raw, dict):
        return {
            "tipo": raw.get("tipo"),
            "url": raw.get("url"),
            "text": raw.get("text"),
            "extractor": raw.get("extractor"),
        }
    # Legacy bare-string variant; treat the string as the type label.
    if isinstance(raw, str):
        return {"tipo": raw, "url": None, "text": None, "extractor": None}
    return {"tipo": None, "url": None, "text": None, "extractor": None}


# ----- helpers -------------------------------------------------------------

def _pop_index(d: dict) -> int:
    """Coerce to v6 `index`, accepting v1/v2 `index_num` and v3 recurso `id`."""
    for k in ("index", "index_num", "id"):
        v = d.pop(k, None) if k != "index" else d.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
    return 0


def _normalize_link(link: Any, link_descricao: Optional[str]) -> Optional[dict]:
    if link is None and link_descricao is None:
        return None
    url, text, extractor = None, None, None
    if isinstance(link, dict):
        url = link.get("url")
        text = link.get("text")
        extractor = link.get("extractor")
        # v5/v6 link already carries `tipo`; honour it if `link_descricao`
        # sibling is absent (which it should be after migration).
        if link_descricao is None and "tipo" in link:
            link_descricao = link.get("tipo")
    elif isinstance(link, str):
        url = link
    return {
        "tipo": link_descricao,
        "url": url,
        "text": text,
        "extractor": extractor,
    }


# ----- outcome promotion ---------------------------------------------------

def _promote_outcome(value: Any, rec: dict) -> Optional[dict]:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        # Try the canonical extractor against in-memory andamentos +
        # sessao_virtual (already normalized by the time we get here).
        derived = derive_outcome({
            "sessao_virtual": rec.get("sessao_virtual") or [],
            "andamentos": rec.get("andamentos") or [],
        })
        if isinstance(derived, dict):
            return dict(derived)
        # Fall back to the bare verdict label with sentinel provenance.
        return {
            "verdict": value,
            "source": "andamentos",
            "source_index": -1,
            "date_iso": None,
        }
    return None
