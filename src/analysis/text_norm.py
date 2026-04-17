"""Brazilian legal name normalization.

Two helpers:
- `normalize_name(s)` — ASCII-fold, uppercase, collapse whitespace. Safe
  idempotent canonicalization for equality comparison.
- `surname_key(s)` — returns a group key based on the last meaningful
  token (Portuguese particles de / da / dos / do / das are dropped).

Used by analysis code to bucket repeat-player lawyers across spelling
variants. Under-merges compound surnames and short initials — that's
an accepted trade-off for a first-pass deep-dive.
"""

from __future__ import annotations

import re
import unicodedata

_PARTICLES: frozenset[str] = frozenset({"DE", "DA", "DO", "DAS", "DOS", "E"})
_WS_RE = re.compile(r"\s+")


def normalize_name(s: str) -> str:
    """Strip accents, uppercase, and collapse whitespace."""
    if not s:
        return ""
    # NFKD decomposes accented chars into base+combining mark, then
    # encode-ignore drops the combining marks.
    stripped = (
        unicodedata.normalize("NFKD", s)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return _WS_RE.sub(" ", stripped).strip().upper()


def surname_key(s: str) -> str:
    """Last non-particle token, normalized. Falls back to the name itself."""
    norm = normalize_name(s)
    if not norm:
        return ""
    tokens = [t for t in norm.split(" ") if t]
    # walk back from the end, skip particles
    for token in reversed(tokens):
        if token not in _PARTICLES:
            return token
    return tokens[-1] if tokens else ""
