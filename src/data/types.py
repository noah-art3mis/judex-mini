from typing import List, Literal, Optional, TypedDict


# Bump on every breaking change to StfItem or its nested shapes. See
# `docs/data-dictionary.md § Schema history` for the changelog. The
# renormalizer (`scripts/renormalize_cases.py`) dispatches on missing
# or lower-valued entries.
#
# v3 (2026-04-18) — list-valued fields promoted to TypedDicts
# (Parte/Andamento/Deslocamento/Peticao/Recurso). ISO-date companions
# added alongside every DD/MM/YYYY field (data_iso on andamentos,
# peticoes, recursos; data_recebido_iso + data_enviado_iso on
# deslocamentos; data_protocolo_iso at top level). Canonical `url`
# added. `status` (HTTP code) renamed to `status_http`. `outcome`
# became an OutcomeInfo dict {verdict, source, source_index, date_iso}
# with provenance, replacing the bare string.
# v2 (2026-04-18) — numero_origem became List[str]; badges keeps only
# .bg-danger; partes reads #todas-partes; andamentos[i].link and
# sessao_virtual[i].documentos values became {"url","text"} dicts;
# voto_relator HTML stripped; raw `html` field dropped.
# v1 — pre-2026-04-18; implicit default for files with no key.
SCHEMA_VERSION = 3


class AndamentoLink(TypedDict):
    url: str
    text: Optional[str]


class Parte(TypedDict):
    index: int
    tipo: str
    nome: str


class Andamento(TypedDict):
    index_num: int
    data: Optional[str]
    data_iso: Optional[str]
    nome: str
    complemento: Optional[str]
    julgador: Optional[str]
    link_descricao: Optional[str]
    link: Optional[AndamentoLink]


class Deslocamento(TypedDict):
    index_num: int
    guia: str
    recebido_por: Optional[str]
    data_recebido: Optional[str]
    data_recebido_iso: Optional[str]
    enviado_por: Optional[str]
    data_enviado: Optional[str]
    data_enviado_iso: Optional[str]


class Peticao(TypedDict):
    index: int
    id: Optional[str]
    data: Optional[str]
    data_iso: Optional[str]
    recebido_data: Optional[str]
    recebido_data_iso: Optional[str]
    recebido_por: Optional[str]


class Recurso(TypedDict):
    id: int
    # NB: `data` here is the recurso-type label (e.g. "AG.REG. NA
    # MEDIDA CAUTELAR NO HABEAS CORPUS"), not a date — historical
    # misnaming. No *_iso companion.
    data: Optional[str]


class OutcomeInfo(TypedDict):
    verdict: str
    source: Literal["sessao_virtual", "andamentos"]
    source_index: int
    date_iso: Optional[str]


class StfItem(TypedDict):
    schema_version: int
    incidente: Optional[int]
    classe: str
    processo_id: int
    url: Optional[str]
    numero_unico: Optional[str]

    meio: Optional[Literal["FISICO", "ELETRONICO"]]
    publicidade: Optional[Literal["PUBLICO", "SIGILOSO"]]
    badges: List[str]

    assuntos: List[str]
    data_protocolo: Optional[str]
    data_protocolo_iso: Optional[str]
    orgao_origem: Optional[str]
    origem: Optional[str]
    numero_origem: Optional[List[str]]

    volumes: Optional[int]
    folhas: Optional[int]
    apensos: Optional[int]

    relator: Optional[str]
    primeiro_autor: Optional[str]
    partes: List[Parte]

    andamentos: List[Andamento]
    # sessao_virtual carries three shapes across the ground-truth corpus
    # (see docs/stf-portal.md § "sessao_virtual"); leaving untyped here.
    sessao_virtual: List
    deslocamentos: List[Deslocamento]
    peticoes: List[Peticao]
    recursos: List[Recurso]
    pautas: Optional[List]

    outcome: Optional[OutcomeInfo]

    status_http: int
    extraido: str
