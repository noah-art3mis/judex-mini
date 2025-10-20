"""
Extraction functions module
Each extraction function is in its own file for better modularity
"""

from .base import handle_extraction_errors, normalize_spaces, track_extraction_timing
from .extract_andamentos import extract_andamentos
from .extract_assuntos import extract_assuntos
from .extract_data_protocolo import extract_data_protocolo
from .extract_deslocamentos import extract_deslocamentos
from .extract_incidente import extract_incidente
from .extract_liminar import extract_liminar
from .extract_orgao_origem import extract_orgao_origem
from .extract_origem import extract_origem
from .extract_partes import extract_partes
from .extract_primeiro_autor import extract_primeiro_autor
from .extract_relator import extract_relator
from .extract_tipo_processo import extract_tipo_processo

__all__ = [
    "normalize_spaces",
    "track_extraction_timing",
    "handle_extraction_errors",
    "extract_incidente",
    "extract_relator",
    "extract_tipo_processo",
    "extract_origem",
    "extract_partes",
    "extract_primeiro_autor",
    "extract_data_protocolo",
    "extract_orgao_origem",
    "extract_assuntos",
    "extract_andamentos",
    "extract_deslocamentos",
    "extract_liminar",
]
