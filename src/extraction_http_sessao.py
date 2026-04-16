"""HTTP port of sessao_virtual.

The STF `abaSessao.asp` fragment is a thin JavaScript template; all the
actual data lives in two JSON endpoints on sistemas.stf.jus.br/repgeral.
The Selenium path clicked through nested Bootstrap collapses to trigger
the template and read the rendered DOM. Here we skip the browser and
call the JSON endpoints directly, then assemble the same dict shape the
Selenium extractor emits.

Two endpoints are relevant:

  - ?oi=<incidente>            → list of {objetoIncidente.id, ...}
                                  (the process + its recursos)
  - ?sessaoVirtual=<id>        → listasJulgamento for one objeto-incidente
  - ?tema=<N>                  → Tema/Repercussão Geral data
                                  (only for processes carrying a tema)

The `documentos` field only carries the PDF URLs here, not the extracted
PDF text. The Selenium path used to download and OCR each PDF; skipping
that keeps this port fast and is acceptable given `sessao_virtual` is a
skipped field in the validator. Follow-up can add opt-in PDF fetching.
"""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any, Callable, Iterable, Optional

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
    "relatora",
    "órgão_julgador",
    "lista",
    "processo",
    "data_início",
    "data_prevista_fim",
)


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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


def _build_metadata(lista: dict, processo_identificacao: str) -> dict[str, str]:
    sessao = lista.get("sessao") or {}
    colegiado = sessao.get("colegiado") or {}
    relator = lista.get("ministroRelator") or {}
    return {
        "relatora": relator.get("descricao", ""),
        "órgão_julgador": colegiado.get("descricao", ""),
        "lista": lista.get("nomeLista", ""),
        "processo": processo_identificacao,
        "data_início": sessao.get("dataInicio", ""),
        "data_prevista_fim": sessao.get("dataPrevistaFim", ""),
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


def _build_documentos(lista: dict) -> dict[str, str]:
    """Collect PDF links from relator, vista, and each voto with textos."""
    docs: dict[str, str] = {}
    relatorio = lista.get("relatorioRelator") or {}
    if isinstance(relatorio, dict) and relatorio.get("link"):
        docs["Relatório"] = relatorio["link"]
    voto = lista.get("votoRelator") or {}
    if isinstance(voto, dict) and voto.get("link"):
        docs.setdefault(voto.get("descricao") or "Voto", voto["link"])

    vista = lista.get("ministroVista") or {}
    for texto in (vista.get("textos") or []) if isinstance(vista, dict) else []:
        if isinstance(texto, dict) and texto.get("link"):
            docs.setdefault("Voto Vista", texto["link"])

    for voto_ in lista.get("votos") or []:
        for texto in voto_.get("textos") or []:
            if isinstance(texto, dict) and texto.get("link"):
                key = texto.get("descricao") or "Voto"
                docs.setdefault(key, texto["link"])

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
                    "voto_relator": _normalize_spaces(html.unescape(cabecalho_raw)),
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
                "data_inicio": proc.get("dataInicioJulgamento"),
                "data_fim_prevista": proc.get("dataFimPrevistaJulgamento"),
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
PdfFetcher = Callable[[str], Optional[str]]


def resolve_documentos(
    docs: dict[str, str], *, fetcher: PdfFetcher
) -> dict[str, str]:
    """Replace URL values in a documentos dict with text from `fetcher(url)`.

    Values that aren't URLs (already-extracted text, or empty strings)
    pass through unchanged so re-running enrich on already-enriched
    output is a no-op. If `fetcher` returns None the URL is preserved
    so a re-run can retry.
    """
    out: dict[str, str] = {}
    for key, value in docs.items():
        if isinstance(value, str) and value.startswith("https://"):
            text = fetcher(value)
            out[key] = text if text is not None else value
        else:
            out[key] = value
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

    When `pdf_fetcher` is provided, each entry's `documentos` dict has
    its URL values swapped for extracted text (see resolve_documentos).
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
            if isinstance(docs, dict):
                entry["documentos"] = resolve_documentos(docs, fetcher=pdf_fetcher)

    return entries
