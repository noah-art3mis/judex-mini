"""HTTP port of sessao_virtual.

The STF `abaSessao.asp` fragment is a thin JavaScript template; all the
actual data lives in two JSON endpoints on sistemas.stf.jus.br/repgeral.
The Selenium path clicked through nested Bootstrap collapses to trigger
the template and read the rendered DOM. Here we skip the browser and
call the JSON endpoints directly, then assemble the list shape consumed
by StfItem (schema v4).

Two endpoints are relevant:

  - ?oi=<incidente>            → list of {objetoIncidente.id, ...}
                                  (the process + its recursos)
  - ?sessaoVirtual=<id>        → listasJulgamento for one objeto-incidente
  - ?tema=<N>                  → Tema/Repercussão Geral data
                                  (only for processes carrying a tema)

The `documentos` field holds a list of
`{"tipo": str, "url": str, "text": None, "extractor": None}` entries.
Order follows STF's JSON order and duplicate `tipo` values are
preserved verbatim — the v3 dict shape silently deduplicated them,
which dropped second votes from the same session. Consumers that want
unique-by-tipo should group after the fact.

Pass a `pdf_fetcher` callable to `extract_sessao_virtual_from_json`
to fill in `text` + `extractor` from OCR/pypdf; without it, both
stay None and the entry can be enriched later by running
`resolve_documentos` separately.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Iterable, Optional

from bs4 import BeautifulSoup

from src.scraping.extraction._shared import to_iso

# tipoVoto.codigo → vote category in the final `votes` dict.
# Mirrors what the Selenium extractor ends up collecting from the
# rendered DOM (which comes out of listasJulgamento.js). Codes not
# listed (suspeito/impedido/ressalva) intentionally drop out for parity.
_VOTE_CATEGORY = {
    "7": "diverge_relator",
    "8": "acompanha_divergencia",
    "9": "acompanha_relator",
}

_METADATA_KEYS = (
    "relator",
    "orgao_julgador",
    "lista",
    "processo",
    "data_inicio",
    "data_fim_prevista",
)


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _strip_html(raw: str) -> str:
    # STF's `cabecalho` can be an HTML fragment or plain text with entities;
    # BeautifulSoup handles both (parses tags, resolves &nbsp;/&ccedil;/…).
    return _normalize_spaces(BeautifulSoup(raw, "lxml").get_text(" ", strip=True))


def parse_oi_listing(response: str) -> list[dict]:
    """Flatten the `?oi=<id>` response into a list of objeto-incidente dicts."""
    data = json.loads(response)
    out: list[dict] = []
    for entry in data:
        oi = entry.get("objetoIncidente") or {}
        if oi.get("id") is not None:
            out.append(
                {
                    "id": oi["id"],
                    "identificacao": oi.get("identificacao", ""),
                    "identificacaoCompleta": oi.get("identificacaoCompleta", ""),
                }
            )
    return out


def _build_metadata(lista: dict, processo_identificacao: str) -> dict[str, Optional[str]]:
    """v6: ASCII snake_case keys; dates normalized to ISO 8601.

    STF's JSON emits dates as DD/MM/YYYY strings — we convert at
    extraction time so downstream code (e.g. `outcome.py`) doesn't
    need both-shape fallbacks.
    """
    sessao = lista.get("sessao") or {}
    colegiado = sessao.get("colegiado") or {}
    relator = lista.get("ministroRelator") or {}
    return {
        "relator": relator.get("descricao", ""),
        "orgao_julgador": colegiado.get("descricao", ""),
        "lista": lista.get("nomeLista", ""),
        "processo": processo_identificacao,
        "data_inicio": to_iso(sessao.get("dataInicio")),
        "data_fim_prevista": to_iso(sessao.get("dataPrevistaFim")),
    }


def _build_votes(lista: dict) -> dict[str, list[str]]:
    votes: dict[str, list[str]] = {
        "relator": [],
        "acompanha_relator": [],
        "diverge_relator": [],
        "acompanha_divergencia": [],
        "pedido_vista": [],
    }
    relator = lista.get("ministroRelator") or {}
    if relator.get("descricao"):
        votes["relator"].append(relator["descricao"])

    for voto in lista.get("votos") or []:
        codigo = str((voto.get("tipoVoto") or {}).get("codigo", ""))
        category = _VOTE_CATEGORY.get(codigo)
        if category is None:
            continue
        ministro = (voto.get("ministro") or {}).get("descricao")
        if ministro:
            votes[category].append(ministro)

    vista = lista.get("ministroVista") or {}
    if vista.get("descricao"):
        votes["pedido_vista"].append(vista["descricao"])

    return votes


def _build_documentos(lista: dict) -> list[dict[str, Optional[str]]]:
    """Collect PDF links from relator, vista, and each voto with textos.

    Each entry is `{"tipo": <label>, "url": <pdf url>, "text": None,
    "extractor": None}`. `text` and `extractor` are populated later by
    `resolve_documentos(fetcher)` once the PDF is extracted; leaving them
    None here means the scraper output is structurally complete without
    blocking on PDF downloads.

    Returns a list (schema v4): duplicate `tipo` values are preserved in
    STF order. The v3 dict shape silently dedup'd on `tipo`, which ate
    second-vote entries from the same session.
    """
    docs: list[dict[str, Optional[str]]] = []

    def add(tipo: str, url: Optional[str]) -> None:
        if url:
            docs.append({"tipo": tipo, "url": url, "text": None, "extractor": None})

    relatorio = lista.get("relatorioRelator") or {}
    if isinstance(relatorio, dict):
        add("Relatório", relatorio.get("link"))
    voto = lista.get("votoRelator") or {}
    if isinstance(voto, dict):
        add(voto.get("descricao") or "Voto", voto.get("link"))

    vista = lista.get("ministroVista") or {}
    if isinstance(vista, dict):
        for texto in vista.get("textos") or []:
            if isinstance(texto, dict):
                add("Voto Vista", texto.get("link"))

    for voto_ in lista.get("votos") or []:
        for texto in voto_.get("textos") or []:
            if isinstance(texto, dict):
                tipo = texto.get("descricao") or "Voto"
                add(tipo, texto.get("link"))

    return docs


def parse_sessao_virtual(response: str) -> list[dict]:
    """Parse `?sessaoVirtual=<id>` JSON into ADI-shape session entries.

    Returns one entry per listaJulgamento (a process can appear in many
    sessions). `julgamento_item_titulo` is set to objetoIncidente's
    `identificacaoCompleta` so orchestrators don't have to re-attribute.
    """
    data = json.loads(response)
    out: list[dict] = []
    for entry in data:
        objeto = entry.get("objetoIncidente") or {}
        processo_id = objeto.get("identificacao", "")
        titulo = objeto.get("identificacaoCompleta", "")
        for lista in entry.get("listasJulgamento") or []:
            cabecalho_raw = lista.get("cabecalho") or ""
            out.append(
                {
                    "metadata": _build_metadata(lista, processo_id),
                    "voto_relator": _strip_html(cabecalho_raw),
                    "votes": _build_votes(lista),
                    "documentos": _build_documentos(lista),
                    "julgamento_item_titulo": titulo,
                }
            )
    return out


def parse_tema(response: str) -> list[dict]:
    """Parse `?tema=<N>` JSON (repercussão geral) into Tema-shape entries."""
    data = json.loads(response)
    pacote = (data or {}).get("package") or {}
    rep = pacote.get("repercussaoGeral") or {}
    processos = rep.get("processoLeadingCase")
    if processos is None:
        return []
    if not isinstance(processos, list):
        processos = [processos]

    out: list[dict] = []
    for proc in processos:
        ministros = ((proc.get("placar") or {}).get("ministro")) or []
        if not isinstance(ministros, list):
            ministros = [ministros]
        out.append(
            {
                "tipo": "tema",
                "tema": proc.get("numeroTema"),
                "titulo": proc.get("tituloTema"),
                "data_inicio": to_iso(proc.get("dataInicioJulgamento")),
                "data_fim_prevista": to_iso(proc.get("dataFimPrevistaJulgamento")),
                "classe": proc.get("siglaClasse"),
                "numero": proc.get("numeroProcesso"),
                "relator": proc.get("relator"),
                "votos": [
                    {
                        "ministro": m.get("nomeMinistro"),
                        "QC": m.get("votoQC"),
                        "RG": m.get("votoRG"),
                        "RJ": m.get("votoRJ"),
                    }
                    for m in ministros
                ],
                "julgamento_item_titulo": (
                    f"Tema {proc.get('numeroTema')}"
                    + (f" - {proc.get('tituloTema')}" if proc.get("tituloTema") else "")
                ),
            }
        )
    return out


Fetcher = Callable[[str, int], str]
PdfFetcher = Callable[[str], tuple[Optional[str], Optional[str]]]
"""Given a PDF URL, return `(text, extractor_label)`.

`extractor_label` is a member of the open set documented on
`StfItem` / `Documento.extractor` ("rtf", "pypdf_plain",
"pypdf_layout", "unstructured", "mistral", "chandra") or None when
extraction failed.
"""


def resolve_documentos(
    docs: list[dict[str, Optional[str]]], *, fetcher: PdfFetcher
) -> list[dict[str, Optional[str]]]:
    """Fill `text` + `extractor` on each documento using `fetcher(url)`.

    Each entry is a `{"tipo", "url", "text", "extractor"}` dict. Tipo +
    URL are preserved; text and extractor are only overwritten when
    currently None. Entries whose text is already non-None pass through
    untouched — rerunning enrich on an already-enriched list is free.
    If `fetcher` returns `(None, _)` the entry is kept as-is so a
    future re-run can retry.
    """
    out: list[dict[str, Optional[str]]] = []
    for entry in docs:
        tipo = entry.get("tipo")
        url = entry.get("url")
        text = entry.get("text")
        extractor = entry.get("extractor")
        if text is None and url:
            fetched_text, fetched_extractor = fetcher(url)
            out.append({
                "tipo": tipo,
                "url": url,
                "text": fetched_text,
                "extractor": fetched_extractor,
            })
        else:
            out.append({
                "tipo": tipo,
                "url": url,
                "text": text,
                "extractor": extractor,
            })
    return out


def extract_sessao_virtual_from_json(
    *,
    incidente: int,
    tema: Optional[int],
    fetcher: Fetcher,
    pdf_fetcher: Optional[PdfFetcher] = None,
) -> list[dict]:
    """Assemble sessao_virtual from the two/three JSON endpoints.

    `fetcher(param, value)` is called with `param` in {'oi', 'sessaoVirtual',
    'tema'} and `value` the integer — it returns the raw JSON text.
    Exists as an injection seam so the orchestrator can layer caching
    and retries without this function caring how the bytes arrive.

    When `pdf_fetcher` is provided, each entry's `documentos` list is
    enriched with extracted text + extractor label (see
    `resolve_documentos`).
    """
    entries: list[dict] = []

    if tema is not None:
        try:
            entries.extend(parse_tema(fetcher("tema", tema)))
        except Exception as e:
            logging.warning(f"tema {tema}: parse failed ({type(e).__name__}: {e})")

    try:
        oi_list = parse_oi_listing(fetcher("oi", incidente))
    except Exception as e:
        logging.warning(f"oi {incidente}: parse failed ({type(e).__name__}: {e})")
        oi_list = []

    for oi in oi_list:
        try:
            entries.extend(parse_sessao_virtual(fetcher("sessaoVirtual", oi["id"])))
        except Exception as e:
            logging.warning(
                f"sessaoVirtual {oi['id']}: parse failed ({type(e).__name__}: {e})"
            )

    if pdf_fetcher is not None:
        for entry in entries:
            docs = entry.get("documentos")
            if isinstance(docs, list):
                entry["documentos"] = resolve_documentos(docs, fetcher=pdf_fetcher)

    return entries
