"""Watch-set diff: compare two StfItem dicts and report what changed.

Distinct from ``judex.sweeps.diff_harness`` — that module is for parity
testing (scraper output vs. ground-truth fixtures) and deliberately
skips the fields that change over time (``publicacoes_dje``,
``sessao_virtual``, ``outcome``). Here we want the *opposite*: notify
on anything a human reader would care about, including those.

Noise fields (``_meta``, ``status_http``, ``extraido``) are skipped —
scrape metadata changes every run and drowns the signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_NOISE_FIELDS = {"_meta", "status_http", "extraido", "schema_version"}

_LIST_FIELDS = {
    "andamentos",
    "peticoes",
    "recursos",
    "deslocamentos",
    "publicacoes_dje",
    "sessao_virtual",
    "pautas",
    "partes",
    "assuntos",
    "badges",
    "numero_origem",
}


@dataclass(frozen=True)
class WatchChange:
    is_new: bool = False
    fields_changed: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    items_added: dict[str, list[Any]] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        return self.is_new or bool(self.fields_changed) or bool(self.items_added)


def _added_items(old: list, new: list) -> list:
    """Return items present in `new` but not in `old` (order-preserving, dup-safe)."""
    remaining = list(old)
    added: list = []
    for item in new:
        try:
            remaining.remove(item)
        except ValueError:
            added.append(item)
    return added


def diff_watched(old: dict | None, new: dict) -> WatchChange:
    """Diff two StfItem dicts; return a WatchChange describing what's new.

    `old=None` means first-time scrape — everything is "new" but we don't
    explode the whole item into the changeset; just flag ``is_new=True``
    and let the renderer handle presentation.
    """
    if old is None:
        return WatchChange(is_new=True)

    fields_changed: dict[str, tuple[Any, Any]] = {}
    items_added: dict[str, list[Any]] = {}

    for key in sorted(set(old) | set(new)):
        if key in _NOISE_FIELDS:
            continue
        a = old.get(key)
        b = new.get(key)
        if a == b:
            continue
        if key in _LIST_FIELDS and isinstance(a, list) and isinstance(b, list):
            added = _added_items(a, b)
            if added:
                items_added[key] = added
        else:
            fields_changed[key] = (a, b)

    return WatchChange(
        is_new=False,
        fields_changed=fields_changed,
        items_added=items_added,
    )
