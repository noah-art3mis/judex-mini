from typing import List, Literal, Optional, TypedDict


class StfItem(TypedDict):
    incidente: Optional[int]
    classe: str
    processo_id: int
    numero_unico: Optional[str]

    meio: Optional[Literal["FISICO", "ELETRONICO"]]
    publicidade: Optional[Literal["PUBLICO", "SIGILOSO"]]
    badges: List[str]

    assuntos: List[str]
    data_protocolo: Optional[str]
    orgao_origem: Optional[str]
    origem: Optional[str]
    numero_origem: Optional[List[str]]

    volumes: Optional[int]
    folhas: Optional[int]
    apensos: Optional[int]

    relator: Optional[str]
    primeiro_autor: Optional[str]
    partes: List

    andamentos: List
    sessao_virtual: List
    deslocamentos: List
    peticoes: List
    recursos: List
    pautas: Optional[List]

    outcome: Optional[str]

    status: int
    extraido: str


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
# class Deslocamento:
#     """Represents a document transfer in the legal process"""

#     index_num: int
#     guia: Optional[str]
#     recebido_por: Optional[str]
#     data_recebido: Optional[str]
#     enviado_por: Optional[str]
#     data_enviado: Optional[str]
