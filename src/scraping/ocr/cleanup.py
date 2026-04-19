"""Postprocess pypdf's text-layer extractions.

pypdf reads the PDF text layer glyph-by-glyph. STF's document headers
use letter-spacing/kerning which pypdf interprets as word boundaries,
emitting things like ``S ÃO PAULO``, ``H C N º 632.905``, and
``S UPERIOR TRIBUNAL``. This module rejoins those artifacts without
damaging legitimate prose.

Strategy — two tiers:
- **Per-line: aggressive rejoin only if the line is all-caps.** A line
  with ≥ 80 % uppercase letters is treated as a header and any ``X YY+``
  pattern (single cap + ≥ 2 caps) is rejoined into ``XYY+``. Mixed-case
  prose lines are left alone — so Portuguese articles ``A``, ``E``, ``O``
  followed by a word survive.
- **Global: safe token-level fixes.** A short whitelist of known STF
  class/number fragments (``N º``, ``H C``, ``A R E``, ``H C Nº``) are
  rejoined regardless of line context — these are never legitimate
  Portuguese bigrams.

Idempotent by construction: the regex patterns only match pre-cleanup
shapes, so running the function twice equals running it once.
"""

from __future__ import annotations

import re


_SPLIT_CAP_WORD = re.compile(
    r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇÀ]) ([A-ZÁÉÍÓÚÂÊÔÃÕÇÀ]{2,})\b"
)

# Portuguese single-letter words that can appear in all-caps headers without
# being part of a split cap-word. Preserves "TORON E OUTRO" and "A TODOS".
_PT_SINGLETON_CAPS = frozenset({"A", "E", "O", "À"})


def _merge_cap_split(match: "re.Match[str]") -> str:
    """Callback for _SPLIT_CAP_WORD: merges unless the single-letter side
    is a Portuguese conjunction/preposition/article that legitimately
    appears in all-caps party-list headers.
    """
    first, rest = match.group(1), match.group(2)
    if first in _PT_SINGLETON_CAPS:
        return match.group(0)
    return first + rest

# Token-level fixes that are safe in any context: these bigrams never
# appear legitimately in Portuguese (they're always split case codes).
_SAFE_TOKEN_FIXES = [
    (re.compile(r"\bN º\b"), "Nº"),
    (re.compile(r"\bN °\b"), "Nº"),
    (re.compile(r"\bH C\b"), "HC"),
    (re.compile(r"\bA R E\b"), "ARE"),
    (re.compile(r"\bR E\b"), "RE"),
    (re.compile(r"\bA D I\b"), "ADI"),
    (re.compile(r"\bA D P F\b"), "ADPF"),
    (re.compile(r"\bR H C\b"), "RHC"),
]

_MULTI_SPACE = re.compile(r"  +")
_MULTI_BLANK_LINE = re.compile(r"\n{3,}")


def _is_allcaps_line(line: str, min_letters: int = 5, threshold: float = 0.8) -> bool:
    """True when the line is predominantly uppercase — a header, not prose.

    Short lines (<``min_letters`` letters) don't qualify since a handful
    of all-caps letters in a numeric header (e.g. a case number line with
    a single short label) would over-trigger.
    """
    letters = [c for c in line if c.isalpha()]
    if len(letters) < min_letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) > threshold


def clean_pdf_text(text: str) -> str:
    """Apply pypdf-artifact cleanup. Pure, idempotent.

    See module docstring for the two-tier strategy and rationale.
    """
    out_lines: list[str] = []
    for line in text.split("\n"):
        if _is_allcaps_line(line):
            line = _SPLIT_CAP_WORD.sub(_merge_cap_split, line)
        for pat, repl in _SAFE_TOKEN_FIXES:
            line = pat.sub(repl, line)
        line = _MULTI_SPACE.sub(" ", line)
        out_lines.append(line)
    result = "\n".join(out_lines)
    result = _MULTI_BLANK_LINE.sub("\n\n", result)
    return result
