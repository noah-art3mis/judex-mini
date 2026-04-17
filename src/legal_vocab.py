"""Brazilian legal vocabulary — centralized lookup tables.

Holds the party-type prefixes, verdict regex patterns, and other domain
vocabulary shared across extractors. Keep this file production-only:
session-specific reference data (e.g. current class ceilings) lives in
the script that uses it.

If you edit this file, re-run `uv run pytest tests/unit/` and
`PYTHONPATH=. uv run python scripts/validate_ground_truth.py` to catch
downstream effects.
"""

from __future__ import annotations

import re
from re import Pattern


# ----- Party types that represent "the filer / primary author" ------
#
# `extract_primeiro_autor` scans `partes` in order and returns the name
# of the first party whose `tipo` starts with any of these prefixes.
# Because HCs list PACTE (paciente) before IMPTE (impetrante), this
# naturally surfaces the pacient as primeiro_autor for HCs, which is
# what the deep-dive wants.

AUTHOR_PARTY_TIPOS: tuple[str, ...] = (
    "AUTOR",    # ACO and other generic-author filings
    "REQTE",    # ADI/ADC/ADPF/ADO/petições — requerente
    "RECTE",    # RE/ARE/ED — recorrente
    "AGTE",     # AI/AG — agravante
    "PACTE",    # HC — paciente (subject of habeas corpus)
    "IMPTE",    # MS/MI/HC — impetrante (fallback after PACTE for HCs)
    "RECLTE",   # RCL — reclamante
    "EMBTE",    # embargos — embargante
)


# ----- Outcome verdict patterns --------------------------------------
#
# Each entry is (compiled regex, outcome label). Patterns are tried in
# order and the first match wins. Keep more specific patterns earlier
# (e.g. "CONCESSÃO PARCIAL" before "CONCEDO").
#
# Recognized labels:
#   concedido            HC/MS/MI: ordem concedida (pacient wins)
#   concedido_parcial    HC/MS/MI: ordem concedida em parte
#   denegado             HC/MS/MI: ordem denegada (pacient loses on merits)
#   nao_conhecido        petition not admitted (procedural rejection)
#   prejudicado          moot / lost its object
#   extinto              extinguished without judgement of merits
#   provido              RE/AI: appeal granted
#   provido_parcial      RE/AI: provimento parcial
#   nao_provido          RE/AI: appeal denied
#   procedente           ADI/ADC: direct action granted
#   improcedente         ADI/ADC: direct action denied
#   procedente_parcial   ADI/ADC: parcialmente procedente

VERDICT_PATTERNS: list[tuple[Pattern[str], str]] = [
    # ---- parcial variants first (they're more specific than the base)
    (re.compile(r"concess[ãa]o\s+parcial|concedo\s+parcialmente\s+a\s+ordem|ordem\s+parcialmente\s+concedida|concedo\s+em\s+parte\s+a\s+ordem", re.I), "concedido_parcial"),
    (re.compile(r"provimento\s+parcial|dou\s+parcial\s+provimento|parcial(?:mente)?\s+provido", re.I), "provido_parcial"),
    (re.compile(r"parcialmente\s+procedente|procedente\s+em\s+parte", re.I), "procedente_parcial"),

    # ---- not-admitted / procedural rejections.
    # "nego seguimento" is the monocratic procedural denial under RISTF
    # art. 21 §1 — functionally the same as "não conheço" for a deep
    # dive; lump both under nao_conhecido.
    (re.compile(r"n[ãa]o\s+conhe[çc]o|n[ãa]o\s+conhecid[oa]\s+(?:do|o|a)\s|\bnego\s+seguimento\b|\bnegado\s+seguimento\b", re.I), "nao_conhecido"),

    # ---- main verdict verbs. Negatives first so they win on overlap.
    # HC/MS/MI
    (re.compile(r"denego\s+(?:a\s+)?ordem|ordem\s+denegada|denegad[oa]\s+a?\s*ordem", re.I), "denegado"),
    (re.compile(r"concedo\s+(?:a\s+)?ordem|ordem\s+concedida|concess[ãa]o\s+da\s+ordem|concedid[oa]\s+a?\s*ordem", re.I), "concedido"),
    # appeals
    (re.compile(r"nego\s+provimento|recurso\s+n[ãa]o\s+provido", re.I), "nao_provido"),
    (re.compile(r"dou\s+provimento|recurso\s+provido|provimento\s+ao\s+recurso", re.I), "provido"),
    # direct action (ADI/ADC/ADPF)
    (re.compile(r"julgo\s+procedente\s+a\s+a[çc][ãa]o|a[çc][ãa]o\s+julgada\s+procedente|\bjulgo\s+procedente\b", re.I), "procedente"),
    (re.compile(r"julgo\s+improcedente|a[çc][ãa]o\s+julgada\s+improcedente", re.I), "improcedente"),

    # ---- last-resort procedural outcomes: only match if none of the
    # main-verdict patterns above fire. "prejudicado" in a side-clause
    # ("restando prejudicado o agravo regimental") must not beat the
    # primary verbo.
    (re.compile(r"\bprejudicad[oa]\b|perda\s+de\s+objeto", re.I), "prejudicado"),
    (re.compile(r"extin[çc][ãa]o\s+sem\s+resolu[çc][ãa]o|extinto\s+sem\s+resolu[çc][ãa]o", re.I), "extinto"),
]


OUTCOME_VALUES: frozenset[str] = frozenset(
    label for _, label in VERDICT_PATTERNS
)
