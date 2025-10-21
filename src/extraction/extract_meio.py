"""
Extract meio from process data
"""

from bs4 import BeautifulSoup

from .base import track_extraction_timing
from .extract_tipo_processo import extract_tipo_processo


@track_extraction_timing
def extract_meio(soup: BeautifulSoup) -> str | None:
    """Return 'FISICO' or 'ELETRONICO' based on badges to match ground-truth 'meio'."""
    tipo = extract_tipo_processo(soup)
    if not tipo:
        return None
    if "Físico" in tipo:
        return "FISICO"
    if "Eletrônico" in tipo:
        return "ELETRONICO"
    return None
