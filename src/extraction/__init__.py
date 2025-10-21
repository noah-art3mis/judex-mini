"""
Extraction functions module
Each extraction function is in its own file for better modularity
"""

# Base utilities
from .base import track_extraction_timing

# Core extraction functions
from .extract_andamentos import extract_andamentos
from .extract_assuntos import extract_assuntos
from .extract_badges import extract_badges
from .extract_classe import extract_classe
from .extract_data_protocolo import extract_data_protocolo
from .extract_deslocamentos import extract_deslocamentos
from .extract_incidente import extract_incidente
from .extract_liminar import extract_liminar
from .extract_meio import extract_meio
from .extract_numero_origem import extract_numero_origem
from .extract_numero_unico import extract_numero_unico
from .extract_orgao_origem import extract_orgao_origem
from .extract_origem import extract_origem
from .extract_partes import extract_partes
from .extract_peticoes import extract_peticoes
from .extract_primeiro_autor import extract_primeiro_autor
from .extract_publicidade import extract_publicidade
from .extract_recursos import extract_recursos
from .extract_relator import extract_relator
from .extract_volumes_folhas_apensos import (
    extract_apensos,
    extract_folhas,
    extract_volumes,
)

# Export all functions
__all__ = [
    # Base utilities
    "track_extraction_timing",
    # Extraction functions
    "extract_andamentos",
    "extract_assuntos",
    "extract_badges",
    "extract_classe",
    "extract_data_protocolo",
    "extract_deslocamentos",
    "extract_incidente",
    "extract_liminar",
    "extract_meio",
    "extract_numero_origem",
    "extract_numero_unico",
    "extract_orgao_origem",
    "extract_origem",
    "extract_partes",
    "extract_peticoes",
    "extract_primeiro_autor",
    "extract_publicidade",
    "extract_recursos",
    "extract_relator",
    "extract_volumes",
    "extract_folhas",
    "extract_apensos",
]
