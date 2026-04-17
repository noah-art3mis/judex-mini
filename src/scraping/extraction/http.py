"""Fragment-based extractors for the HTTP scraper path — facade module.

Re-exports the per-fragment submodules so orchestrators can keep doing
`from src.scraping.extraction import http as ex` and then call
`ex.extract_*(...)`. Splitting the implementations by concern keeps
each file small; this module preserves the one-stop-shop API.

Routing summary (which fragment each reads):
    detalhe.asp       → incidente, numero_unico, classe, relator, meio,
                        publicidade, badges                   [detalhe.py]
    abaInformacoes    → assuntos, data_protocolo, orgao_origem,
                        numero_origem, origem, volumes, folhas,
                        apensos                               [info.py]
    abaPartes         → partes, primeiro_autor                [partes.py]
    abaAndamentos     → andamentos                            [tables.py]
    abaDeslocamentos  → deslocamentos                         [tables.py]
    abaPeticoes       → peticoes                              [tables.py]
    abaRecursos       → recursos                              [tables.py]

derive_outcome reads the assembled item (not a fragment) — see
`outcome.py`. sessao_virtual lives in `sessao.py`; its tab fragment is
a JS template, so orchestration (not just parsing) is needed.
"""

from __future__ import annotations

from src.scraping.extraction.classe import extract_classe
from src.scraping.extraction.detalhe import extract_badges, extract_incidente
from src.scraping.extraction.info import (
    extract_apensos,
    extract_assuntos,
    extract_data_protocolo,
    extract_folhas,
    extract_numero_origem,
    extract_orgao_origem,
    extract_origem,
    extract_volumes,
)
from src.scraping.extraction.meio import extract_meio
from src.scraping.extraction.numero_unico import extract_numero_unico
from src.scraping.extraction.outcome import derive_outcome
from src.scraping.extraction.partes import (
    extract_partes,
    extract_primeiro_autor,
)
from src.scraping.extraction.publicidade import extract_publicidade
from src.scraping.extraction.relator import extract_relator
from src.scraping.extraction.tables import (
    extract_andamentos,
    extract_deslocamentos,
    extract_peticoes,
    extract_recursos,
)

__all__ = [
    "extract_incidente",
    "extract_numero_unico",
    "extract_classe",
    "extract_relator",
    "extract_meio",
    "extract_publicidade",
    "extract_badges",
    "extract_assuntos",
    "extract_data_protocolo",
    "extract_orgao_origem",
    "extract_origem",
    "extract_numero_origem",
    "extract_volumes",
    "extract_folhas",
    "extract_apensos",
    "extract_partes",
    "extract_primeiro_autor",
    "extract_andamentos",
    "extract_deslocamentos",
    "extract_peticoes",
    "extract_recursos",
    "derive_outcome",
]
