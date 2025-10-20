from dataclasses import dataclass
from typing import Optional


@dataclass
class StfItem:
    # Basic process identification
    incidente: int
    classe: str
    processo_id: int
    numero_unico: Optional[str]

    # Process classification
    meio: str  # "FISICO" or "ELETRONICO"
    publicidade: str  # "PUBLICO" or "SIGILOSO"
    badges: list[str]

    # Process content
    assuntos: list[str]
    data_protocolo: str
    orgao_origem: str
    origem: str
    numero_origem: list[int]

    # Document counts
    volumes: int
    folhas: int
    apensos: int

    # People and parties
    relator: Optional[str]
    primeiro_autor: Optional[str]
    partes: list

    # Process steps and activities
    andamentos: list
    sessao_virtual: list
    deslocamentos: list
    peticoes: list
    recursos: list
    pautas: list

    # Metadata
    status: int
    extraido: str
    html: str


# @dataclass
# class Parte:
#     """Represents a party in the legal process"""

#     index: int
#     tipo: str
#     nome: str


# @dataclass
# class Andamento:
#     """Represents a procedural step in the legal process"""

#     index_num: int
#     data: str
#     nome: str
#     complemento: Optional[str]
#     link_descricao: Optional[str]
#     link: Optional[str]
#     julgador: Optional[str]


# @dataclass
# class SessaoVirtual:
#     """Represents a virtual session"""

#     data: Optional[str]
#     tipo: Optional[str]
#     numero: Optional[str]
#     relator: Optional[str]
#     status: Optional[str]
#     participantes: list[str]


# @dataclass
# class Deslocamento:
#     """Represents a document transfer in the legal process"""

#     index_num: int
#     guia: Optional[str]
#     recebido_por: Optional[str]
#     data_recebido: Optional[str]
#     enviado_por: Optional[str]
#     data_enviado: Optional[str]
