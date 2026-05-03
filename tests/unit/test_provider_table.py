"""Pin `judex providers` table renderer.

Tests the pure-function half (``provider_table`` returning data and
``render_provider_table`` returning a string). The Typer wiring is a
thin echo and not unit-tested separately.
"""

from __future__ import annotations

from judex.scraping.ocr.dispatch import (
    REGISTRY,
    provider_table,
    render_provider_table,
)


def test_provider_table_has_one_row_per_registered_provider() -> None:
    rows = provider_table()
    assert {r.name for r in rows} == set(REGISTRY)


def test_provider_table_sorted_by_cost_ascending_with_none_last() -> None:
    """Cost-ascending sort, with anchor-missing rows (cost=None) at the
    end. This is the ordering the CLI prints — the cheapest options
    sort to the top so the operator's eye lands there first."""
    rows = provider_table()
    seen_none = False
    last_cost = -1.0
    for r in rows:
        if r.cost_usd is None:
            seen_none = True
            continue
        assert not seen_none, (
            f"row {r.name} has cost {r.cost_usd} but a None-cost row "
            f"appeared earlier — sort order broken"
        )
        assert r.cost_usd >= last_cost, f"unsorted at {r.name}"
        last_cost = r.cost_usd


def test_pypdf_is_zero_dollars_at_default_scope() -> None:
    """pypdf is local text-layer extraction — never costs anything.
    Behavioural pin: if this changes, something is fundamentally
    wrong with the SPEC or the registry build."""
    rows = provider_table()
    by_name = {r.name: r for r in rows}
    assert by_name["pypdf"].cost_usd == 0.0


def test_render_includes_header_and_one_line_per_provider() -> None:
    out = render_provider_table()
    assert "provider" in out
    assert "batch?" in out
    # one header + one separator + one row per provider
    assert len(out.splitlines()) == 2 + len(REGISTRY)


def test_render_shows_dash_for_missing_wall_anchor() -> None:
    """Providers whose ``wall()`` raises NotImplementedError render as
    ``—`` in the minutes column, not a stale number or a crash."""
    rows = provider_table()
    out = render_provider_table()
    missing_wall_names = [r.name for r in rows if r.wall_seconds is None]
    if not missing_wall_names:
        # All providers have wall anchors — nothing to assert. This is
        # not a regression; future bakeoffs will fill the gaps.
        return
    for name in missing_wall_names:
        # The line for this provider should carry a `—` somewhere.
        line = next(l for l in out.splitlines() if l.startswith(name))
        assert "—" in line, (
            f"provider {name} has no wall anchor but its line {line!r} "
            f"didn't render '—'"
        )
