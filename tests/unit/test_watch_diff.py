"""Watch-set diff: two StfItem dicts → WatchChange describing what differs.

Pins down: no-change empty result, scalar-field diff recorded as (old, new)
pairs, list-field additions recorded item-by-item, _meta/status_http
noise skipped, and the "first-time scrape" (old=None) case labelled as new.
"""

from __future__ import annotations

from judex.reports.watch_diff import WatchChange, diff_watched


def _case(**overrides: object) -> dict:
    base: dict = {
        "_meta": {"schema_version": 8},
        "classe": "HC",
        "processo_id": 158802,
        "incidente": 100,
        "relator": "Min. X",
        "outcome": None,
        "andamentos": [{"index": 0, "nome": "Distribuído", "data": "2026-01-01"}],
        "peticoes": [],
        "recursos": [],
        "deslocamentos": [],
        "publicacoes_dje": [],
        "sessao_virtual": [],
        "partes": [],
        "assuntos": [],
        "badges": [],
    }
    base.update(overrides)
    return base


def test_identical_cases_produce_no_change() -> None:
    old = _case()
    new = _case()

    change = diff_watched(old, new)

    assert change.has_changes is False
    assert change.fields_changed == {}
    assert change.items_added == {}


def test_scalar_field_change_is_recorded() -> None:
    old = _case(relator=None)
    new = _case(relator="Min. Y")

    change = diff_watched(old, new)

    assert change.has_changes is True
    assert change.fields_changed == {"relator": (None, "Min. Y")}


def test_new_andamento_is_recorded_as_item_added() -> None:
    old = _case()
    new_row = {"index": 1, "nome": "Decisão monocrática", "data": "2026-04-19"}
    new = _case(andamentos=[_case()["andamentos"][0], new_row])

    change = diff_watched(old, new)

    assert change.has_changes is True
    assert change.items_added.get("andamentos") == [new_row]


def test_new_dje_publication_is_recorded() -> None:
    old = _case()
    pub = {"numero": "77", "data": "2026-04-19", "titulo": "Decisão Monocrática"}
    new = _case(publicacoes_dje=[pub])

    change = diff_watched(old, new)

    assert change.items_added.get("publicacoes_dje") == [pub]


def test_meta_field_change_is_ignored_as_noise() -> None:
    """Scrape metadata (_meta, status_http) flips on every run; don't notify."""
    old = _case(_meta={"schema_version": 8, "extraido": "2026-04-18T00:00:00Z"})
    new = _case(_meta={"schema_version": 8, "extraido": "2026-04-19T00:00:00Z"})

    change = diff_watched(old, new)

    assert change.has_changes is False


def test_first_time_scrape_is_labelled_new() -> None:
    """old=None means we've never scraped this watched case before."""
    change = diff_watched(None, _case())

    assert change.is_new is True
    assert change.has_changes is True


def test_outcome_change_is_notable() -> None:
    """outcome is deliberately NOT skipped for watch-set (unlike diff_harness)."""
    old = _case(outcome=None)
    new = _case(outcome={"label": "PROVIDO", "method": "MONOCRATICA"})

    change = diff_watched(old, new)

    assert "outcome" in change.fields_changed
