"""Canonicalize and classify lawyer-party names for cross-case aggregation.

The STF portal renders `partes` rows in a few inconvenient shapes:

- OAB inscription parentheticals: `"NOME (12345/SP)"`
- Co-impetração tail: `"NOME (12345/SP) E OUTRO(A/S)"` (singular or
  plural; the paren form is stripped first by `_OAB_RE`)
- "Same as previous row" sentinels: `"O MESMO"`, `"OS MESMOS"`,
  `"A MESMA"`, plus typos (`"O MESM0"` with a zero, `"IO MESMO"`,
  `"O ,MESMO"`). These are not parties — they're a portal-side
  shorthand. Left in, they account for ~3 k phantom IMPTE rows in
  the HC corpus and can take #1 in any volume ranking.

Two public entry points — use these from notebooks instead of rolling
your own regex:

- `canonical_lawyer(nome)` → `(key, oab_codes)`
    Pure normalization: uppercase, strip OAB parentheticals, drop
    "E OUTRO(S)" tail, filter sentinels. Returns `("", ())` for
    sentinels; caller filters with `if not key`.

- `classify(nome)` → `LawyerEntry(kind, key, oab_codes)`
    Everything `canonical_lawyer` does, plus a coarse type:
    SENTINEL / PLACEHOLDER / PRO_SE / INSTITUTIONAL / JURIDICAL /
    COURT / WITH_OAB / BARE. Accent-insensitive for institutional
    matching. Catches OAB codes outside the parenthetical form
    (`"OAB/SP 148022"`, `"OAB-PE 48215"`).
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import NamedTuple

_OAB_RE      = re.compile(r"\s*\(([^)]*)\)\s*")
_TAIL_RE     = re.compile(r"\s+E\s+OUTRO[AS]?S?\s*$", re.IGNORECASE)
_OAB_CODE_RE = re.compile(r"^\s*(\d+[A-Z]?/?[A-Z]{2})\s*$")

# Portal sentinel — anchored full-string match so real names whose
# substrings happen to look similar (e.g. "SIDEMI", "HEIDEMANN") are
# preserved. Tolerates: O/OS/A/IO prefix, optional internal comma, the
# zero-for-O typo (MESM0), and the singular/plural "E OUTRO(S)" tail
# when it slips past _TAIL_RE.
_SENTINEL_RE = re.compile(
    r"^I?[OA]S?\s*,?\s*MESM[OA0]S?(?:\s+E\s+OUTRO[AS]?S?)?$"
)

# OAB codes in non-parenthetical form, appearing anywhere in the
# raw name. Matches: "OAB/SP 148022", "OAB-PE 48215", "- OAB 450989/SP",
# "OAB/SP 394.151" (with thousands-dot). The "OAB" keyword is
# required to avoid false positives on dates like "25/09".
_OAB_ANYWHERE_RE = re.compile(
    r"\bOAB[\s/-]+"
    r"(?:(?P<uf1>[A-Z]{2})[\s/-]+(?P<num1>[\d.]+[A-Z]?)"
    r"|(?P<num2>[\d.]+[A-Z]?)[\s/-]*/[\s-]*(?P<uf2>[A-Z]{2}))"
)


class LawyerKind(Enum):
    """Coarse category for a `partes[].nome` entry.

    Ordered by specificity of match, not by frequency.
    """
    SENTINEL      = "sentinel"       # "O MESMO" family — placeholder meaning "same as above"
    PLACEHOLDER   = "placeholder"    # "SEM REPRESENTAÇÃO NOS AUTOS"
    PRO_SE        = "pro_se"         # "EM CAUSA PROPRIA" — patient represents self
    INSTITUTIONAL = "institutional"  # Defensoria Pública, AGU, PGR, MP
    JURIDICAL     = "juridical"      # Sindicato, instituto, federação, law firm
    COURT         = "court"          # Juízo, juiz, relator, desembargador as party
    WITH_OAB      = "with_oab"       # Real lawyer with OAB registered (any format)
    BARE          = "bare"           # Real lawyer name, no OAB in data


class LawyerEntry(NamedTuple):
    kind:      LawyerKind
    key:       str                  # canonical upper-case name; "" for SENTINEL
    oab_codes: tuple[str, ...]      # () when none detected


_PLACEHOLDER_KEYS = frozenset({
    "SEM REPRESENTAÇÃO NOS AUTOS",
    "SEM REPRESENTACAO NOS AUTOS",
})

_PRO_SE_KEYS = frozenset({
    "EM CAUSA PROPRIA",
    "EM CAUSA PROPRIA",
    "EM CAUSA PRÓPRIA",
})

# Accent-folded institutional prefixes. Matching is done against the
# folded form of the canonical key, so "DEFENSORIA PÚBLICA" and
# "DEFENSORIA PUBLICA" (missing-accent variant, 4.7k rows in the
# corpus) both land here.
_INSTITUTIONAL_PREFIXES_FOLDED = (
    "DEFENSOR PUBLICO",
    "DEFENSORIA PUBLICA",
    "ADVOGADO-GERAL DA UNIAO",
    "ADVOCACIA-GERAL DA UNIAO",
    "PROCURADOR-GERAL",
    "PROCURADORIA-GERAL",
    "MINISTERIO PUBLICO",
    "MINISTERIO PUBLICO FEDERAL",
)

# Juridical-person prefixes / suffixes (folded). Unions, institutes,
# federations, law firms — parties, but not individual lawyers.
_JURIDICAL_PREFIXES_FOLDED = (
    "SINDICATO",
    "FEDERACAO",
    "INSTITUTO",
    "CONFEDERACAO",
    "ASSOCIACAO",
    "CONSELHO REGIONAL",
    "CONSELHO FEDERAL",
    "ORDEM DOS ADVOGADOS DO BRASIL",
)
_JURIDICAL_SUFFIXES_FOLDED = (
    "ADVOGADOS ASSOCIADOS",
    "SOCIEDADE DE ADVOGADOS",
    "ADVOCACIA",
    "& ADVOGADOS",
)

# Court / judicial authority prefixes (folded). Typical shape in data
# is the coator (authority being challenged) accidentally routed into
# an ADV/IMPTE row.
_COURT_PREFIXES_FOLDED = (
    "JUIZO",
    "JUIZ DE DIREITO",
    "JUIZ FEDERAL",
    "DESEMBARGADOR",
    "RELATOR DO",
    "RELATORA DO",
    "TRIBUNAL",
    "SUPERIOR TRIBUNAL",
)


def _fold(s: str) -> str:
    """Strip diacritics for accent-insensitive prefix matching.

    NFD decomposition + filter combining marks. "PÚBLICA" → "PUBLICA",
    "ANTÔNIO" → "ANTONIO". Does NOT alter the returned canonical key —
    used only for classification decisions.
    """
    return "".join(
        ch for ch in unicodedata.normalize("NFD", s)
        if unicodedata.category(ch) != "Mn"
    )


def canonical_lawyer(nome: str) -> tuple[str, tuple[str, ...]]:
    """Canonicalize a `partes[].nome` string.

    Returns `(key, oab_codes)`:
    - `key` — uppercase, paren-stripped, tail-stripped name; `""` for
      sentinel rows ("O MESMO" and variants). Caller filters with
      `if not key`.
    - `oab_codes` — tuple of OAB codes found inside parentheticals,
      e.g. `("12345/SP",)`. Only parenthetical codes — for non-
      parenthetical forms (`"OAB/SP 148022"`) use `classify()`.
    """
    codes: list[str] = []
    for m in _OAB_RE.finditer(nome):
        for part in m.group(1).split(","):
            mm = _OAB_CODE_RE.match(part)
            if mm:
                codes.append(mm.group(1).upper())

    clean = _OAB_RE.sub(" ", nome).strip()
    clean = _TAIL_RE.sub("", clean).strip().rstrip(",").strip()
    key = clean.upper()

    if _SENTINEL_RE.match(key):
        return ("", ())

    return (key, tuple(codes))


def _extract_oab_anywhere(nome: str) -> tuple[str, ...]:
    """OAB codes in non-parenthetical form, anywhere in the raw name.

    Catches `"NOME, OAB/SP 148022"`, `"NOME OAB-PE 48215"`, etc.
    Returns a tuple of codes in `"NNNNN/UF"` form. Thousands-dot
    separators in the number are stripped.
    """
    codes: list[str] = []
    for m in _OAB_ANYWHERE_RE.finditer(nome.upper()):
        uf  = m.group("uf1")  or m.group("uf2")
        num = m.group("num1") or m.group("num2")
        if not uf or not num:
            continue
        num = num.replace(".", "")
        codes.append(f"{num}/{uf}")
    return tuple(codes)


def classify(nome: str) -> LawyerEntry:
    """Canonicalize + classify a `partes[].nome` string.

    Returns `LawyerEntry(kind, key, oab_codes)`. Classification is
    accent-insensitive: "DEFENSORIA PUBLICA DA UNIAO" (no accent,
    4.7k rows) is recognized as INSTITUTIONAL alongside the
    accent-ful form.

    Precedence (first match wins):
        SENTINEL → PLACEHOLDER → PRO_SE → INSTITUTIONAL → JURIDICAL
        → COURT → WITH_OAB → BARE
    """
    key, paren_codes = canonical_lawyer(nome)

    if not key:
        return LawyerEntry(LawyerKind.SENTINEL, "", ())

    if key in _PLACEHOLDER_KEYS:
        return LawyerEntry(LawyerKind.PLACEHOLDER, key, ())

    if key in _PRO_SE_KEYS:
        return LawyerEntry(LawyerKind.PRO_SE, key, ())

    folded = _fold(key)

    if folded.startswith(_INSTITUTIONAL_PREFIXES_FOLDED):
        return LawyerEntry(LawyerKind.INSTITUTIONAL, key, paren_codes)

    if folded.startswith(_JURIDICAL_PREFIXES_FOLDED) or any(
        suf in folded for suf in _JURIDICAL_SUFFIXES_FOLDED
    ):
        return LawyerEntry(LawyerKind.JURIDICAL, key, paren_codes)

    if folded.startswith(_COURT_PREFIXES_FOLDED):
        return LawyerEntry(LawyerKind.COURT, key, paren_codes)

    anywhere_codes = _extract_oab_anywhere(nome)
    all_codes = tuple(dict.fromkeys(paren_codes + anywhere_codes))

    if all_codes:
        return LawyerEntry(LawyerKind.WITH_OAB, key, all_codes)

    return LawyerEntry(LawyerKind.BARE, key, ())
