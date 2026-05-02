from typing import List, Literal, Optional, TypedDict


# Bump on every breaking change to StfItem or its nested shapes. See
# `docs/data-dictionary.md § Schema history` for the changelog. The
# renormalizer (`scripts/renormalize_cases.py`) dispatches on missing
# or lower-valued entries.
#
# v8 (2026-04-19) — Documento.text / Documento.extractor stripped from
# JSON; `data/derived/pecas-texto/<sha1(url)>.{txt.gz,extractor}` is now
# the single source of truth. Fetchers still populate the cache during
# scrape; consumers (warehouse builder, notebooks) resolve text from
# the cache at read time via `peca_cache.read(url)` +
# `peca_cache.read_extractor(url)`. The TypedDict keys stay (`text`,
# `extractor` are still `Optional[str]`) but every Documento slot on
# disk carries `None` for both. Applies uniformly to
# `andamentos[].link`, `sessao_virtual[].documentos[]`, and
# `publicacoes_dje[].decisoes[].rtf`. `PublicacaoDJe.decisoes[].texto`
# (HTML-extracted, always present) is retained as the DJe fast-path;
# content-equal to the stripped RTF after whitespace normalization
# so no information is lost for DJe specifically.
# v7 (2026-04-19) — DJe publicações added. Each case now carries a
# `publicacoes_dje: List[PublicacaoDJe]` field sourced from two new
# endpoints (`listarDiarioJustica.asp` + `verDiarioProcesso.asp`).
# Each publicação bundles listing metadata (DJ number, date, secao,
# subsecao, titulo, linked incidente) with detail-page content
# (classe, procedencia, relator, partes, materia) plus a list of
# `DecisaoDJe` blocks. Each block has a `kind` tag ("decisao" or
# "ementa" — EMENTA renders as a decisao-shaped <p>+RTF on the
# Acórdão variant of the detail page), the HTML-extracted paragraph
# text, and an `rtf: Documento` with the `verDecisao.asp?...&texto=<id>`
# URL whose `.text` is populated from peca_cache via the existing
# RTF extractor. No backfill path — renormalizer seeds empty list;
# only a fresh scrape fills it.
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
SCHEMA_VERSION = 8


class Documento(TypedDict):
    """Unified document reference — an `Andamento.link` or a session document.

    A pure pointer: ``tipo`` (anchor label) + ``url`` (peça URL). The
    canonical extracted text + provider label live in
    ``data/derived/pecas-texto/<sha1(url)>.txt.gz`` and
    ``data/derived/pecas-texto/<sha1(url)>.extractor``. Resolve at read
    time via ``peca_cache.read(url)`` + ``peca_cache.read_extractor(url)``;
    never carry text on the dict itself.

    Pre-v8 files (v4–v7) carry ``text`` and ``extractor`` keys populated
    inline on each Documento; the warehouse builder reads them via
    ``dict.get("text")`` / ``dict.get("extractor")`` as legacy-tolerant
    fallbacks for cold checkouts of old backups (this works because
    Python TypedDicts don't reject extra keys at runtime). The
    renormalizer (``scripts/renormalize_cases.py``) strips those keys
    on v7→v8, and v8+ scrapes never re-emit them.

    ``url`` may be None when the source anchor had visible text but no
    href (STF occasionally renders broken anchors). In that case
    ``tipo`` still carries the anchor label, so the signal is preserved.
    """
    tipo: Optional[str]
    url: Optional[str]


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


class DecisaoDJe(TypedDict):
    """One decisao-shaped block from a DJe detail page (`verDiarioProcesso.asp`).

    Both proper session decisões and the acórdão's EMENTA render with
    the same `<p>` + `<a href=verDecisao.asp?...>` scaffolding on the
    page; the `kind` tag disambiguates ("EMENTA:" text prefix on the
    Acórdão variant maps to `kind="ementa"`, everything else is
    `kind="decisao"`). Keeping them in one list matches the source and
    avoids a downstream special case.
    """
    kind: Literal["decisao", "ementa"]
    texto: str
    rtf: Documento                   # verDecisao.asp?...&texto=<id>; .text from peca_cache


class PublicacaoDJe(TypedDict):
    """One DJe publication referencing the case.

    Two listing forms exist on `listarDiarioJustica.asp` since STF's
    2022-12-19 content-URL migration (see ADR-0003):

    - **Pre-migration / Distribuição** entries carry a clickable
      `abreDetalheDiarioProcesso(...)` JS callback. The parser extracts
      `numero`, `data`, `incidente_linked`, and `detail_url`
      (`verDiarioProcesso.asp?...`); detail-page fields are filled in
      by `parse_dje_detail`. `external_redirect` is None.
    - **Post-migration** entries carry only metadata (`numero`+`data`,
      or `data` alone) plus a plain redirect anchor pointing at
      `digital.stf.jus.br/publico/publicacoes`. `detail_url` and
      `incidente_linked` are None; `external_redirect` is the
      redirect URL. Detail-page fields stay at defaults — the content
      lives on STF's new platform behind AWS WAF (Phase 2 of ADR-0003).

    `numero` may be None: STF emits "DJ do dia DD/MM/YYYY" without a
    DJ number for some publication types post-migration.

    `incidente_linked` is the 3rd `abreDetalheDiarioProcesso` arg and
    may differ from the parent case's incidente — STF often files
    related filings (AG.REG., EMB.DECL.) under their own incidentes.
    """
    # Listing fields.
    numero: Optional[int]            # None for "DJ do dia ..." entries (no DJ number).
    data: Optional[str]              # ISO 8601 date.
    secao: str                       # e.g. "Acórdãos", "Segunda Turma". "" for redirect entries.
    subsecao: str                    # e.g. "Acórdãos 2ª Turma", "Sessão Virtual". "" for redirect entries.
    titulo: str                      # anchor text from the listing. "" for redirect entries.
    detail_url: Optional[str]        # verDiarioProcesso.asp?... ; None for redirect entries.
    incidente_linked: Optional[int]  # None for redirect entries.
    external_redirect: Optional[str] # digital.stf.jus.br/... ; None for legacy entries.
    # Detail-page fields.
    classe: Optional[str]
    procedencia: Optional[str]
    relator: Optional[str]
    partes: List[str]                # raw "TIPO - NOME" strings as shown on the DJe.
    materia: List[str]               # "DIREITO X | Subtema | Ramo"-style pipeline strings.
    decisoes: List[DecisaoDJe]


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

    # DJe publications (new in v7).
    publicacoes_dje: List[PublicacaoDJe]

    # Derived.
    outcome: Optional[OutcomeInfo]
