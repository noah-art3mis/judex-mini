from typing import List, Literal, Optional, TypedDict


# Bump on every breaking change to StfItem or its nested shapes. See
# `docs/data-dictionary.md § Schema history` for the changelog. The
# renormalizer (`scripts/renormalize_cases.py`) dispatches on missing
# or lower-valued entries.
#
# v6 (2026-04-18) — broad cleanup sweep. Dominant themes: reduce schema
# variance, strip legacy naming, push scrape metadata out of the domain
# payload.
#   - sessao_virtual is now typed (`SessaoVirtual`). Metadata keys are
#     ASCII snake_case: `relator`, `orgao_julgador`, `data_inicio`,
#     `data_fim_prevista` (was: accented/mixed-language keys, and
#     `relatora` regardless of minister gender).
#   - All `*_iso` date companions are gone. The plain key (`data`,
#     `data_recebido`, `data_enviado`, `data_protocolo`, `data_inicio`,
#     `data_fim_prevista`) now carries ISO-8601 directly. The raw
#     DD/MM/YYYY string from the source HTML/JSON is dropped.
#   - `Peticao.recebido_data` carries a full ISO-8601 timestamp
#     (`YYYY-MM-DDTHH:MM:SS`); previously truncated to date.
#   - Index field unified: `index_num` (Andamento/Deslocamento) and
#     `id` (Recurso) are renamed to plain `index`. Parte and Peticao
#     already used `index`.
#   - `Recurso.data` → `Recurso.tipo`. The value was always a
#     recurso-type label (e.g. "AG.REG. NA MEDIDA CAUTELAR NO HABEAS
#     CORPUS"), not a date — historical misnaming.
#   - Scrape metadata (`schema_version`, `status_http`, `extraido`)
#     moved under a top-level `_meta: ScrapeMeta` slot. StfItem is now
#     pure domain data at the top level.
#   - `incidente` is non-Optional: live scraping either resolves an
#     incidente or raises `NoIncidenteError`.
#   - `Pauta` is typed and populated; previously `pautas` was a bare
#     list with no extractor behind it.
# v5 (2026-04-19) — andamento link merged with Documento; `link.tipo`
# replaces the sibling `link_descricao`.
# v4 (2026-04-19) — `Documento.extractor` added; sessao_virtual
# documentos restructured from dict-keyed-by-tipo to list-of-Documento.
# v3 (2026-04-18) — list-valued fields promoted to TypedDicts; ISO-date
# companions introduced; `url` + `OutcomeInfo` added; `status` renamed
# to `status_http`.
# v2 (2026-04-18) — numero_origem → List[str]; badges filtered to
# `.bg-danger`; partes reads `#todas-partes`; `link`/`documentos` became
# `{url, text}` dicts.
# v1 — pre-2026-04-18; implicit default for files with no key.
SCHEMA_VERSION = 6


class Documento(TypedDict):
    """Unified document reference — an `Andamento.link` or a session document.

    `text` and `extractor` are **lazily populated** and are None on a
    fresh scrape. They are filled in by `resolve_documentos` (when the
    caller provides a `pdf_fetcher`) or during warehouse build. Source
    of truth for extracted PDF text lives at
    `data/cache/pdf/<sha1(url)>.txt.gz`; this struct is a pointer, not
    a payload.

    `url` may be None when the source anchor had visible text but no
    href (STF occasionally renders broken anchors). In that case
    `tipo` still carries the anchor label, so the signal is preserved.
    """
    tipo: Optional[str]
    url: Optional[str]
    text: Optional[str]
    extractor: Optional[str]


class Parte(TypedDict):
    index: int
    tipo: str
    nome: str


class Andamento(TypedDict):
    index: int
    data: Optional[str]              # ISO 8601 date (YYYY-MM-DD).
    nome: str
    complemento: Optional[str]
    julgador: Optional[str]
    link: Optional[Documento]


class Pauta(TypedDict):
    """One row from the `abaPautas.asp` fragment.

    Shape mirrors `Andamento` (same HTML structure) minus `link` —
    pauta rows don't carry PDF anchors.
    """
    index: int
    data: Optional[str]              # ISO 8601 date (YYYY-MM-DD).
    nome: str
    complemento: Optional[str]
    julgador: Optional[str]


class Deslocamento(TypedDict):
    index: int
    guia: str
    recebido_por: Optional[str]
    data_recebido: Optional[str]     # ISO 8601 date.
    enviado_por: Optional[str]
    data_enviado: Optional[str]      # ISO 8601 date.


class Peticao(TypedDict):
    index: int
    id: Optional[str]
    data: Optional[str]              # ISO 8601 date (protocol date).
    recebido_data: Optional[str]     # ISO 8601 datetime (YYYY-MM-DDTHH:MM:SS).
    recebido_por: Optional[str]


class Recurso(TypedDict):
    index: int
    tipo: Optional[str]              # Recurso-type label; not a date.


class SessaoVirtualMetadata(TypedDict):
    relator: str
    orgao_julgador: str
    lista: str
    processo: str
    data_inicio: Optional[str]       # ISO 8601 date.
    data_fim_prevista: Optional[str] # ISO 8601 date.


class SessaoVirtualVotes(TypedDict):
    relator: List[str]
    acompanha_relator: List[str]
    diverge_relator: List[str]
    acompanha_divergencia: List[str]
    pedido_vista: List[str]


class SessaoVirtual(TypedDict):
    metadata: SessaoVirtualMetadata
    voto_relator: Optional[str]
    votes: SessaoVirtualVotes
    documentos: List[Documento]
    julgamento_item_titulo: Optional[str]


class OutcomeInfo(TypedDict):
    verdict: str
    source: Literal["sessao_virtual", "andamentos"]
    source_index: int
    date_iso: Optional[str]


class ScrapeMeta(TypedDict):
    """Scrape-provenance slot. Kept separate from domain data so
    consumers can ignore it uniformly (exports, diffs, warehouse)."""
    schema_version: int
    status_http: int
    extraido: str                    # ISO 8601 datetime.


class StfItem(TypedDict):
    # Scrape metadata — not part of the case data itself.
    _meta: ScrapeMeta

    # Identity.
    incidente: int
    classe: str
    processo_id: int
    url: Optional[str]
    numero_unico: Optional[str]

    # Classification.
    meio: Optional[Literal["FISICO", "ELETRONICO"]]
    publicidade: Optional[Literal["PUBLICO", "SIGILOSO"]]
    badges: List[str]
    assuntos: List[str]

    # Origin.
    data_protocolo: Optional[str]    # ISO 8601 date.
    orgao_origem: Optional[str]
    origem: Optional[str]
    numero_origem: Optional[List[str]]

    # Volumetric metadata.
    volumes: Optional[int]
    folhas: Optional[int]
    apensos: Optional[int]

    # Parties.
    relator: Optional[str]
    primeiro_autor: Optional[str]
    partes: List[Parte]

    # Activity.
    andamentos: List[Andamento]
    sessao_virtual: List[SessaoVirtual]
    deslocamentos: List[Deslocamento]
    peticoes: List[Peticao]
    recursos: List[Recurso]
    pautas: List[Pauta]

    # Derived.
    outcome: Optional[OutcomeInfo]
