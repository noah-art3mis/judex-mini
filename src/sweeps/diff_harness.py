"""
Shared diff harness for comparing HTTP scraper output against Selenium
output or the ground-truth fixtures.

Callers pass two dicts and get back a list of human-readable diff lines.
Set allow_growth=True when comparing against older fixtures — reverse-
chronological lists (andamentos, peticoes, recursos, deslocamentos) can
have grown since the fixture was recorded; new items at the front of
the list are reported as drift rather than as a regression.
"""

from __future__ import annotations

from typing import Any

# Not diffable or known to differ by design.
# v6 groups scrape metadata under `_meta`; we skip that as a single
# key. The individual legacy keys remain in the set so diffs against
# pre-v6 fixtures still work.
SKIP_FIELDS = {
    "_meta",
    "extraido",
    "sessao_virtual",
    "status_http",
    "outcome",
    "schema_version",
}

# Lists that can grow over time as the process adds new events.
GROWING_LISTS = {"andamentos", "peticoes", "recursos", "deslocamentos"}


def _clip(v: Any, limit: int = 200) -> str:
    s = repr(v)
    return s if len(s) < limit else s[:limit] + "...[truncated]"


def _diff_growing_list(key: str, http_list: list, gt_list: list) -> list[str]:
    msgs: list[str] = []
    if len(http_list) < len(gt_list):
        msgs.append(
            f"  {key}: http has FEWER items ({len(http_list)}) than ground truth "
            f"({len(gt_list)}) — regression"
        )
        return msgs
    tail = http_list[-len(gt_list):] if gt_list else []
    if tail != gt_list:
        for i, (a, b) in enumerate(zip(tail, gt_list)):
            if a != b:
                msgs.append(f"  {key}[tail idx {i}]: http={_clip(a)} vs gt={_clip(b)}")
                if len(msgs) >= 3:
                    msgs.append(f"  {key}: (further diffs truncated)")
                    break
    added = len(http_list) - len(gt_list)
    if added > 0:
        msgs.append(
            f"  {key}: +{added} new item(s) since ground truth (expected drift, not a regression)"
        )
    return msgs


def diff_item(http: dict, other: dict, *, allow_growth: bool = False) -> list[str]:
    messages: list[str] = []
    for k in sorted(set(http) | set(other)):
        if k in SKIP_FIELDS:
            continue
        a = http.get(k)
        b = other.get(k)
        if a == b:
            continue
        if allow_growth and k in GROWING_LISTS and isinstance(a, list) and isinstance(b, list):
            messages.extend(_diff_growing_list(k, a, b))
        else:
            messages.append(f"  {k}: http={_clip(a)} vs other={_clip(b)}")
    return messages
