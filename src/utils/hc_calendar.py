"""HC processo_id ↔ filing-date calendar.

Piecewise-linear interpolation between anchor points scraped from cache.
Use this when planning stratified sweeps without probing STF upfront.

Anchor file: `src/utils/hc_id_to_date.json` — extend by scraping more
HCs and re-running the collector at the bottom of this module.

    from src.utils.hc_calendar import id_to_date, year_to_id_range
    id_to_date(230000)          # → datetime.date(2023, 5, 11)
    year_to_id_range(2022)      # → (lo, hi) HC ids estimated for 2022
"""

from __future__ import annotations

import bisect
import json
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

_ANCHOR_PATH = Path(__file__).parent / "hc_id_to_date.json"


def _load_anchors() -> list[tuple[int, date]]:
    data = json.loads(_ANCHOR_PATH.read_text())
    out: list[tuple[int, date]] = []
    for a in data["anchors"]:
        out.append((int(a["id"]), date.fromisoformat(a["date"])))
    return sorted(set(out))


_ANCHORS: list[tuple[int, date]] = _load_anchors()
_IDS: list[int] = [i for i, _ in _ANCHORS]


def _ordinal(d: date) -> int:
    return d.toordinal()


def id_to_date(hc_id: int) -> date:
    """Estimate filing date for a given HC id by linear interp between neighbors."""
    i = bisect.bisect_left(_IDS, hc_id)
    if i < len(_IDS) and _IDS[i] == hc_id:
        return _ANCHORS[i][1]
    if i == 0:
        # extrapolate using the first two anchors
        (id_a, d_a), (id_b, d_b) = _ANCHORS[0], _ANCHORS[1]
    elif i == len(_IDS):
        # extrapolate using the last two anchors
        (id_a, d_a), (id_b, d_b) = _ANCHORS[-2], _ANCHORS[-1]
    else:
        (id_a, d_a), (id_b, d_b) = _ANCHORS[i - 1], _ANCHORS[i]
    if id_b == id_a:
        return d_a
    frac = (hc_id - id_a) / (id_b - id_a)
    ord_est = _ordinal(d_a) + frac * (_ordinal(d_b) - _ordinal(d_a))
    return date.fromordinal(int(round(ord_est)))


def year_to_id_range(year: int) -> tuple[int, int]:
    """Estimate (lo, hi) HC id bounds for a calendar year via inverse interp."""
    lo = _invert(date(year, 1, 1))
    hi = _invert(date(year, 12, 31))
    return lo, hi


def _invert(target: date) -> int:
    """Find the HC id whose estimated date is `target`."""
    target_ord = _ordinal(target)
    # find the anchor pair that brackets target_ord in date space
    for (id_a, d_a), (id_b, d_b) in zip(_ANCHORS, _ANCHORS[1:]):
        if _ordinal(d_a) <= target_ord <= _ordinal(d_b):
            if _ordinal(d_b) == _ordinal(d_a):
                return id_a
            frac = (target_ord - _ordinal(d_a)) / (_ordinal(d_b) - _ordinal(d_a))
            return int(round(id_a + frac * (id_b - id_a)))
    # extrapolate from the nearest end
    if target_ord < _ordinal(_ANCHORS[0][1]):
        (id_a, d_a), (id_b, d_b) = _ANCHORS[0], _ANCHORS[1]
    else:
        (id_a, d_a), (id_b, d_b) = _ANCHORS[-2], _ANCHORS[-1]
    if _ordinal(d_b) == _ordinal(d_a):
        return id_a
    frac = (target_ord - _ordinal(d_a)) / (_ordinal(d_b) - _ordinal(d_a))
    return int(round(id_a + frac * (id_b - id_a)))


def anchors() -> Iterable[tuple[int, date]]:
    return list(_ANCHORS)


if __name__ == "__main__":
    print(f"{len(_ANCHORS)} anchors loaded")
    print(f"id range:  {_ANCHORS[0][0]}..{_ANCHORS[-1][0]}")
    print(f"date range: {_ANCHORS[0][1]}..{_ANCHORS[-1][1]}")
    print()
    print("Year → estimated HC id range:")
    for y in range(2010, 2027):
        lo, hi = year_to_id_range(y)
        print(f"  {y}: HC {lo:>6} .. {hi:>6}  (~{hi - lo + 1:>6} ids)")
