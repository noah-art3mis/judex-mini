"""Discover newly-filed cases by probing above a high-water mark.

STF assigns per-class sequential `numeroProcesso` IDs. Given the
last-seen number for a class, `discover_new_numeros` probes upward via
an injected `resolver` (typically `src.scraping.scraper.resolve_incidente`
bound to a session) until it sees `stop_after_misses` contiguous
`NoIncidenteError` responses — STF's way of signalling the number is
unallocated — which means we've passed the current live high-water mark.

The function is pure w.r.t. the injected resolver: no HTTP here. The
orchestrator wires a real resolver in production, and tests pass a
dict-backed fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.scraping.scraper import NoIncidenteError

Resolver = Callable[[str, int], int]


@dataclass(frozen=True)
class Discovered:
    classe: str
    numero: int
    incidente: int


def discover_new_numeros(
    classe: str,
    start: int,
    *,
    resolver: Resolver,
    stop_after_misses: int = 20,
    max_probes: int = 1000,
) -> list[Discovered]:
    """Probe `(classe, start+1)`, `(classe, start+2)`, … returning live hits.

    Stops after `stop_after_misses` contiguous `NoIncidenteError`s or
    `max_probes` total probes (safety cap against a misbehaving resolver).
    A hit anywhere in the sequence resets the miss counter — STF numbering
    has legitimate single-probe gaps that must not terminate discovery.
    """
    found: list[Discovered] = []
    numero = start
    misses = 0
    probes = 0

    while misses < stop_after_misses and probes < max_probes:
        numero += 1
        probes += 1
        try:
            incidente = resolver(classe, numero)
        except NoIncidenteError:
            misses += 1
            continue
        misses = 0
        found.append(Discovered(classe=classe, numero=numero, incidente=incidente))

    return found
