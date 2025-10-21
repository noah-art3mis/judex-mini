"""
Extract numero_unico from process data
"""

from bs4 import BeautifulSoup

from .base import track_extraction_timing


@track_extraction_timing
def extract_numero_unico(soup: BeautifulSoup) -> str | None:
    """Extract numero_unico from .processo-rotulo element"""
    el = soup.select_one(".processo-rotulo")
    if not el:
        return None
    text = el.get_text(" ", strip=True)
    # Ex: "Número Único: 0004022-92.1988.0.01.0000"
    if "Número Único:" in text:
        value = text.split("Número Único:")[1].strip()
        # Normalize "Sem número único" to None per ground-truth schema
        if not value or value.lower().startswith("sem número único"):
            return None
        return value
    return None
