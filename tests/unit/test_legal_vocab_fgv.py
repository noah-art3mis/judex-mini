"""FGV IV Relatório Supremo em Números (2015) §b, p.50 outcome rule.

The report defines the success-rate denominator as every decision that
terminates a process, excluding interlocutórias and liminares; it then
partitions those decisions into favorável (procedência parcial ou total)
and desfavorável (all else, explicitly including "negativa de admissão").

`derive_outcome` already emits None for liminares/interlocutórias, so at
this layer the partition must cover every member of `OUTCOME_VALUES`
exactly once. These tests pin the invariant: if a future contributor
adds a new verdict label, they must classify it under the FGV rule or
the tests fail loudly.
"""

from __future__ import annotations

from src.analysis.legal_vocab import (
    FGV_FAVORABLE_OUTCOMES,
    FGV_UNFAVORABLE_OUTCOMES,
    OUTCOME_VALUES,
)


def test_fgv_partition_is_exhaustive():
    assert FGV_FAVORABLE_OUTCOMES | FGV_UNFAVORABLE_OUTCOMES == OUTCOME_VALUES


def test_fgv_partition_is_disjoint():
    assert FGV_FAVORABLE_OUTCOMES & FGV_UNFAVORABLE_OUTCOMES == frozenset()


def test_fgv_favorable_contains_the_filer_win_labels():
    # HC/MS ordem concedida, appeal provido, ADI/ADC procedente —
    # FGV §b: "procedência parcial ou total" for the filer.
    assert {
        "concedido", "concedido_parcial",
        "provido", "provido_parcial",
        "procedente", "procedente_parcial",
    } <= FGV_FAVORABLE_OUTCOMES


def test_fgv_unfavorable_includes_negativa_de_admissao():
    # Explicit in FGV §b: "negativa de admissão" is desfavorável,
    # not excluded. This is where judex-mini's default hc-who-wins
    # spec diverges (it treats nao_conhecido as "procedural/neither").
    assert "nao_conhecido" in FGV_UNFAVORABLE_OUTCOMES
