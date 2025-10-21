from typing import List, Literal, Optional, TypedDict


class StfItem(TypedDict):
    # Basic process identification
    incidente: int
    classe: str
    processo_id: int
    numero_unico: Optional[str]

    # Process classification
    meio: Literal["FISICO", "ELETRONICO"]
    publicidade: Literal["PUBLICO", "SIGILOSO"]
    badges: List[str]

    # Process content
    assuntos: List[str]
    data_protocolo: str
    orgao_origem: str
    origem: str
    numero_origem: List[int]

    # Document counts
    volumes: int
    folhas: int
    apensos: int

    # People and parties
    relator: Optional[str]
    primeiro_autor: Optional[str]
    partes: List

    # Process steps and activities
    andamentos: List
    sessao_virtual: List
    deslocamentos: List
    peticoes: List
    recursos: List
    pautas: List

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
