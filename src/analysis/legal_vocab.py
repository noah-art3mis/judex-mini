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


# ----- FGV IV Relatório Supremo em Números (2015) §b rule ------------
#
# Success-rate partition adopted by Falcão, Moraes & Hartmann in the
# IV Relatório Supremo em Números — O Supremo e o Ministério Público
# (FGV DIREITO RIO, 2015), §b "A Taxa de Sucesso do MP", p. 50:
#
#   "o levantamento é feito excluindo decisões interlocutórias e
#    liminares, e computando decisões que encerram um processo —
#    favoráveis ou desfavoráveis. São consideradas favoráveis decisões
#    de procedência parcial ou total, enquanto que todas as demais —
#    como improcedência ou negativa de admissão — são consideradas
#    desfavoráveis."
#
# `derive_outcome` already emits None for liminares / interlocutórias
# (they match no VERDICT_PATTERN), so the exclusion is handled upstream.
# At this layer the two sets exhaustively partition OUTCOME_VALUES.
#
# Adopted as the project-wide win/loss definition 2026-04-17 — see
# `docs/hc-who-wins.md` § "Research question" for the justification
# (comparability with FGV's published MP baselines; defensibility of a
# peer-reviewed rule; honest framing of *nao_conhecido* as a loss).
# Pass FGV_FAVORABLE_OUTCOMES to `grant_rate_table(..., win_labels=)`
# whenever the analysis reports a success rate.

FGV_FAVORABLE_OUTCOMES: frozenset[str] = frozenset({
    "concedido", "concedido_parcial",
    "provido", "provido_parcial",
    "procedente", "procedente_parcial",
})

FGV_UNFAVORABLE_OUTCOMES: frozenset[str] = OUTCOME_VALUES - FGV_FAVORABLE_OUTCOMES


# ----- Per-classe outcome universe ----------------------------------
#
# Which verdict labels can legitimately terminate a process of each
# STF classe. Three families (writ / appeal / action) plus the
# universal terminators every classe can end with:
#
#   writ    (HC/MS/MI/HD/Ext)              → concedido-family
#   appeal  (RE/ARE/AI/RHC/RMS/AgR/ED/EDv) → provido-family
#   action  (ADI/ADC/ADO/ADPF/ACO/AO/Rcl/
#            AP/Inq)                       → procedente-family
#
# Universal terminators: `nao_conhecido` (court refused to hear it),
# `prejudicado` (case became moot), `extinto` (procedural dismissal).
# These can end any classe regardless of family.
#
# Cross-reference: `docs/stf-taxonomy.md` §12. Invariants pinned by
# `tests/unit/test_classe_outcome_map.py`: every label in
# VERDICT_PATTERNS must appear in at least one classe (reachability),
# and every classe set must be ⊆ OUTCOME_VALUES.

_UNIVERSAL_TERMINATORS: frozenset[str] = frozenset({
    "nao_conhecido", "prejudicado", "extinto",
})

_WRIT_MERITS: frozenset[str] = frozenset({
    "concedido", "concedido_parcial", "denegado",
})

_APPEAL_MERITS: frozenset[str] = frozenset({
    "provido", "provido_parcial", "nao_provido",
})

_ACTION_MERITS: frozenset[str] = frozenset({
    "procedente", "procedente_parcial", "improcedente",
})

_WRIT_CLASSES: tuple[str, ...] = ("HC", "MS", "MI", "HD", "Ext")
_APPEAL_CLASSES: tuple[str, ...] = ("RE", "ARE", "AI", "RHC", "RMS", "AgR", "ED", "EDv")
_ACTION_CLASSES: tuple[str, ...] = ("ADI", "ADC", "ADO", "ADPF", "ACO", "AO", "Rcl", "AP", "Inq")

CLASSE_OUTCOME_MAP: dict[str, frozenset[str]] = {
    **{c: _WRIT_MERITS   | _UNIVERSAL_TERMINATORS for c in _WRIT_CLASSES},
    **{c: _APPEAL_MERITS | _UNIVERSAL_TERMINATORS for c in _APPEAL_CLASSES},
    **{c: _ACTION_MERITS | _UNIVERSAL_TERMINATORS for c in _ACTION_CLASSES},
}
