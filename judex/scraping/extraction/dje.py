"""DJe (Diário da Justiça) extractors.

Two fragments, two parsers:

- `parse_dje_listing(html)` → list of PublicacaoDJe with *listing-only*
  fields populated. Source: `/servicos/dje/listarDiarioJustica.asp`.
  Each entry carries the `detail_url` that the orchestrator follows next.

- `parse_dje_detail(html)` → dict with detail-page fields (classe,
  procedencia, relator, partes, materia, decisoes). Source:
  `/servicos/dje/verDiarioProcesso.asp`. Each block in `decisoes` is
  `DecisaoDJe`-shaped with `rtf.text`/`rtf.extractor` at None — the
  RTF resolver (reused from sessao_virtual) fills those in later.

Both parsers are pure: no HTTP, no caches, no globals. Orchestration
(merging listing + detail + RTF text into a single PublicacaoDJe)
lives in `src/scraping/scraper.py`.
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from judex.scraping.extraction._shared import to_iso

_DJE_DETAIL_BASE = "https://portal.stf.jus.br/servicos/dje/verDiarioProcesso.asp"

_DJ_HEADER_RE = re.compile(r"^\s*DJ Nr\.\s*(\d+)\s+do dia\s+(\d{2}/\d{2}/\d{4})\s*$")
_ONCLICK_RE = re.compile(
    r"abreDetalheDiarioProcesso\(\s*"
    r"(\d+)\s*,\s*'(\d{2}/\d{2}/\d{4})'\s*,\s*"
    r"(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)"
)


def _empty_detail_fields() -> dict:
    """Detail-side defaults — `parse_dje_detail` fills them in later."""
    return {
        "classe": None,
        "procedencia": None,
        "relator": None,
        "partes": [],
        "materia": [],
        "decisoes": [],
    }


def _build_detail_url(
    dj: str, data: str, incidente: str, capitulo: str, num_mat: str, cod_mat: str
) -> str:
    return (
        f"{_DJE_DETAIL_BASE}?"
        f"numDj={dj}&dataPublicacaoDj={data}&incidente={incidente}"
        f"&codCapitulo={capitulo}&numMateria={num_mat}&codMateria={cod_mat}"
    )


def parse_dje_listing(html: str) -> list[dict]:
    """Parse `listarDiarioJustica.asp` into PublicacaoDJe entries (listing fields only).

    The HTML is a flat stream of `<strong>` section-label tags + `<a>`
    entry links under one container. The shape per group is:

        <strong>DJ Nr. N do dia DD/MM/YYYY</strong>  ← DJ header
        <strong>  Secao</strong>                    ← 2 leading nbsp
        <strong>    Subsecao</strong>               ← 4 leading nbsp
        <a onclick="abreDetalheDiarioProcesso(...)">titulo</a>

    We walk `<strong>` / `<a>` in order, buffering the section strongs
    between DJ-header boundaries; each `<a>` with the expected onclick
    emits one entry using the most-recent DJ header + section buffer.
    """
    soup = BeautifulSoup(html, "lxml")
    entries: list[dict] = []

    current_numero: Optional[int] = None
    current_data_raw: Optional[str] = None
    section_buf: list[str] = []

    for el in soup.find_all(["strong", "a"]):
        if el.name == "strong":
            text = el.get_text(strip=True)
            m = _DJ_HEADER_RE.match(text)
            if m:
                current_numero = int(m.group(1))
                current_data_raw = m.group(2)
                section_buf = []
            else:
                section_buf.append(text)
            continue

        # <a>
        onclick = el.get("onclick") or ""
        m = _ONCLICK_RE.search(onclick)
        if not m or current_numero is None:
            continue
        dj, data, incidente, capitulo, num_mat, cod_mat = m.groups()

        entry = {
            "numero": current_numero,
            "data": to_iso(current_data_raw),
            "secao": section_buf[0] if len(section_buf) >= 1 else "",
            "subsecao": section_buf[1] if len(section_buf) >= 2 else "",
            "titulo": el.get_text(strip=True),
            "detail_url": _build_detail_url(dj, data, incidente, capitulo, num_mat, cod_mat),
            "incidente_linked": int(incidente),
        }
        entry.update(_empty_detail_fields())
        entries.append(entry)

    return entries


# ---------------------------------------------------------------------------
# Detail page
# ---------------------------------------------------------------------------

_DETAIL_LABELS = {
    "Classe:": "classe",
    "Procedência:": "procedencia",
    "Relator:": "relator",
    "Partes:": "partes",
    "Matéria:": "materia",
}


def _extract_dl_fields(soup: BeautifulSoup) -> dict:
    """Map the <dl> label/value pairs to our field names.

    Simple text scalars for Classe/Procedência/Relator; list-of-text
    for Partes/Matéria (rendered as `<ul><li>…</li></ul>` inside the dd).
    """
    out: dict = {}
    dl = soup.find("dl")
    if not dl:
        return out
    children = [c for c in dl.find_all(["dt", "dd"], recursive=False)]
    i = 0
    while i + 1 < len(children):
        dt, dd = children[i], children[i + 1]
        if dt.name != "dt" or dd.name != "dd":
            i += 1
            continue
        label = dt.get_text(strip=True)
        field = _DETAIL_LABELS.get(label)
        i += 2
        if not field:
            continue
        lis = dd.find_all("li")
        if lis:
            out[field] = [li.get_text(" ", strip=True) for li in lis]
        else:
            out[field] = dd.get_text(" ", strip=True) or None
    return out


def _extract_decisoes(soup: BeautifulSoup) -> list[dict]:
    """Pair text paragraphs with their sibling "Download do documento (RTF)" link.

    On the detail page the body is a `#andamentos` div containing
    alternating `<p>` blocks:

        <p>Decisão: …</p>                      ← text (or EMENTA)
        <p class="text-right mb-3"><a href=verDecisao.asp?…>…(RTF)</a></p>

    We walk the `<p>` children in order; whenever we hit a
    "text-right" paragraph carrying an anchor, we pair it with the
    most-recent non-empty text paragraph. `kind="ementa"` is detected
    by an "EMENTA:" prefix in the paired text (stripped of leading
    whitespace).
    """
    container = soup.find(id="andamentos") or soup
    decisoes: list[dict] = []
    pending_text: Optional[str] = None

    for p in container.find_all("p", recursive=True):
        classes = p.get("class") or []
        anchor = p.find("a", href=True)
        is_download = ("text-right" in classes) and anchor is not None

        if not is_download:
            text = _normalize_decisao_text(p.get_text("\n", strip=False))
            if text:
                pending_text = text
            continue

        if pending_text is None:
            continue
        href = anchor["href"].strip()
        kind = "ementa" if pending_text.lstrip().startswith("EMENTA:") else "decisao"
        decisoes.append({
            "kind": kind,
            "texto": pending_text,
            "rtf": {
                "tipo": "DJE",
                "url": href,
                "text": None,
                "extractor": None,
            },
        })
        pending_text = None

    return decisoes


def _normalize_decisao_text(raw: str) -> str:
    """Collapse STF's double/triple newlines while keeping paragraph breaks."""
    if not raw:
        return ""
    lines = [line.strip() for line in raw.splitlines()]
    stripped = [line for line in lines if line]
    return " ".join(stripped).strip()


def parse_dje_detail(html: str) -> dict:
    """Parse `verDiarioProcesso.asp` HTML into detail-side PublicacaoDJe fields.

    Returns a dict with `classe`, `procedencia`, `relator`, `partes`,
    `materia`, `decisoes`. Intended to be `.update()`'d into a
    listing-side entry produced by `parse_dje_listing`.
    """
    soup = BeautifulSoup(html, "lxml")
    out = _empty_detail_fields()
    out.update(_extract_dl_fields(soup))
    out["decisoes"] = _extract_decisoes(soup)
    # Ensure list-valued defaults are never None.
    out["partes"] = out.get("partes") or []
    out["materia"] = out.get("materia") or []
    return out
