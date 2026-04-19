"""Discovery: probe upward from a high-water mark, stop on contiguous misses.

STF assigns per-class sequential `numeroProcesso` IDs. `discover_new_numeros`
probes numbers above a known high-water mark via an injected resolver and
returns those that exist. It stops when N contiguous resolver failures
signal we've passed the current live max.

Tests pin down: happy-path discovery, empty-day probe-then-stop, miss-counter
reset on mid-sequence gaps, and a safety cap on runaway probes.
"""

from __future__ import annotations

from src.scraping.scraper import NoIncidenteError
from src.sweeps.discovery import Discovered, discover_new_numeros


def _make_resolver(allocated: dict[int, int]):
    """Resolver that returns incidente for numbers in `allocated`, else raises."""

    def resolve(classe: str, numero: int) -> int:
        if numero in allocated:
            return allocated[numero]
        raise NoIncidenteError(http_status=302, location="/error.asp")

    return resolve


def test_returns_newly_allocated_numbers_above_start() -> None:
    resolver = _make_resolver({271140: 7567814, 271141: 7567820})

    result = discover_new_numeros(
        "HC", start=271139, resolver=resolver, stop_after_misses=5
    )

    assert result == [
        Discovered(classe="HC", numero=271140, incidente=7567814),
        Discovered(classe="HC", numero=271141, incidente=7567820),
    ]


def test_stops_after_contiguous_misses() -> None:
    """When no new cases exist, probe exactly `stop_after_misses` times then return []."""
    probed: list[int] = []

    def resolve(classe: str, numero: int) -> int:
        probed.append(numero)
        raise NoIncidenteError(http_status=302, location="/error.asp")

    result = discover_new_numeros(
        "HC", start=271139, resolver=resolve, stop_after_misses=3
    )

    assert result == []
    assert probed == [271140, 271141, 271142]


def test_gap_resets_miss_counter() -> None:
    """An allocated number in the middle of misses must reset the stop counter.

    STF's numbering has legitimate gaps (cancelled filings, admin skips). A
    single miss between two live numbers must not terminate discovery early.
    """
    resolver = _make_resolver({271140: 100, 271143: 200})

    result = discover_new_numeros(
        "HC", start=271139, resolver=resolver, stop_after_misses=3
    )

    assert result == [
        Discovered(classe="HC", numero=271140, incidente=100),
        Discovered(classe="HC", numero=271143, incidente=200),
    ]


def test_max_probes_safety_cap() -> None:
    """Resolver that always succeeds must still halt when max_probes is reached."""

    def always_hits(classe: str, numero: int) -> int:
        return numero * 10

    result = discover_new_numeros(
        "HC",
        start=0,
        resolver=always_hits,
        stop_after_misses=100,
        max_probes=5,
    )

    assert len(result) == 5
    assert [d.numero for d in result] == [1, 2, 3, 4, 5]
