"""
Shared helpers used by both the Selenium extractors (src/scraping/extraction/)
and the HTTP extractors (src/scraping/extraction/http.py).

These are pure functions/constants that operate on BeautifulSoup trees
or raw HTML strings — no driver dependency.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from bs4 import BeautifulSoup, Tag

from src.utils.text_utils import normalize_spaces


_DDMMYYYY = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_DDMMYYYY_HHMMSS = re.compile(
    r"\b(\d{2})/(\d{2})/(\d{4})(?:[ T]|,?\s+às\s+)(\d{2}):(\d{2})(?::(\d{2}))?"
)


def to_iso(br_date: Optional[str]) -> Optional[str]:
    """Extract the first DD/MM/YYYY in a string and return YYYY-MM-DD.

    Tolerant of trailing time (``"17/08/2020 às 11:51"``,
    ``"20/08/2020 11:51:26"``) and leading boilerplate. Returns None
    when no DD/MM/YYYY is present or the date is not a valid calendar
    day. Designed to be called on the already-extracted display fields
    (``andamento.data``, ``peticao.recebido_data``, etc.).
    """
    if not br_date:
        return None
    m = _DDMMYYYY.search(br_date)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def to_iso_datetime(br_timestamp: Optional[str]) -> Optional[str]:
    """Extract a DD/MM/YYYY[ HH:MM[:SS]] timestamp → ISO 8601 datetime.

    Falls back to `to_iso` (date-only) when no time component is
    present. Used for ``peticao.recebido_data`` where STF emits
    ``"20/08/2020 11:51:26"`` — v6 preserves the time rather than
    truncating to date.
    """
    if not br_timestamp:
        return None
    m = _DDMMYYYY_HHMMSS.search(br_timestamp)
    if not m:
        return to_iso(br_timestamp)
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh, mm = int(m.group(4)), int(m.group(5))
    ss = int(m.group(6)) if m.group(6) else 0
    if not (1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100):
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}T{hh:02d}:{mm:02d}:{ss:02d}"


_GUIA_SUFFIX = re.compile(r",\s*GUIA\s*N[ºOo0]?[^,]*$", re.IGNORECASE)


def clean_nome(nome: str) -> str:
    nome = normalize_spaces(nome)
    if nome:
        nome = _GUIA_SUFFIX.sub("", nome).strip()
    return nome


P_DETAIL_BOLD = re.compile(r'processo-detalhes-bold">([^<]+)')
P_DETAIL_BASIC = re.compile(r'"processo-detalhes">([^<]+)')
P_DETAIL_INFO = re.compile(r'processo-detalhes bg-font-info">([^<]+)')
P_DETAIL_SUCCESS = re.compile(r'processo-detalhes bg-font-success">([^<]+)')
P_GUIA_CELL = re.compile(r'text-right">\s*<span class="processo-detalhes">([^<]+)')
P_EM_DATE = re.compile(r"em (\d{2}/\d{2}/\d{4})")
P_RECEBIDO_EM = re.compile(r"Recebido em ([^<]+)")


def strip_actor_boiler(text: str, prefix: str) -> str:
    """Remove 'Enviado por '/'Recebido por ' prefix and trailing ' em DD/MM/YYYY'."""
    t = re.sub(rf"^{prefix} ", "", text)
    t = re.sub(r" em \d{2}/\d{2}/\d{4}$", "", t)
    return t.strip()


def iter_lista_dados(html: str) -> Iterable[tuple[int, Tag]]:
    """
    Yield (reverse_index, row_tag) for each .lista-dados row in a tab
    fragment. Reverse index matches the ordering the Selenium extractors
    produce (newest item gets the highest number).
    """
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select(".lista-dados")
    total = len(rows)
    for i, row in enumerate(rows):
        yield total - i, row


