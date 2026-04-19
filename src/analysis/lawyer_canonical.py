"""Canonicalize lawyer-party names for cross-case aggregation.

The STF portal renders `partes` rows in a few inconvenient shapes:

- OAB inscription parentheticals: `"NOME (12345/SP)"`
- Co-impetração tail: `"NOME (12345/SP) E OUTRO(A/S)"` (singular or
  plural; the paren form is stripped first by `_OAB_RE`)
- "Same as previous row" sentinels: `"O MESMO"`, `"OS MESMOS"`,
  `"A MESMA"`, plus typos (`"O MESM0"` with a zero, `"IO MESMO"`,
  `"O ,MESMO"`). These are not parties — they're a portal-side
  shorthand. Left in, they account for ~3 k phantom IMPTE rows in
  the HC corpus and can take #1 in any volume ranking.

`canonical_lawyer(nome)` returns `(key, oab_codes)`:

- `key` — uppercase, OAB-stripped, tail-stripped name, or `""` for a
  sentinel (caller filters with `if not key`).
- `oab_codes` — tuple of inscription codes like `("12345/SP",)`.
"""

from __future__ import annotations

import re

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


def canonical_lawyer(nome: str) -> tuple[str, tuple[str, ...]]:
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
