"""Invariants for `src.analysis.legal_vocab.CLASSE_OUTCOME_MAP`.

The map declares, per STF classe, which outcome labels can legitimately
terminate a process of that kind. It exists so that:

1. Validators can flag parser bugs like "this HC got labeled `provido`".
2. Analytics can compute success rates per classe-family without
   re-deriving which labels count as a "filer win" for that family.
3. Readers can see, in one place, which outcomes apply to which
   procedural form — today that information is scattered across four
   prose locations (`docs/stf-taxonomy.md` §12, three docstrings /
   comment blocks in `src/analysis/legal_vocab.py`).

Tests verify two real invariants (not ceremonial structure checks):
- *Reachability*: every VERDICT_PATTERNS label appears in at least one
  classe. Catches the bug where a new verdict label is added but never
  mapped → every classe's success-rate denominator is silently wrong.
- *Containment*: every classe's set is a subset of OUTCOME_VALUES.
  Catches typos ("concedida" vs "concedido") and stale references to
  deleted labels.
"""

from __future__ import annotations

from src.analysis.legal_vocab import (
    CLASSE_OUTCOME_MAP,
    OUTCOME_VALUES,
)


def test_every_verdict_label_is_reachable_from_some_classe():
    reachable: set[str] = set()
    for labels in CLASSE_OUTCOME_MAP.values():
        reachable |= labels
    assert reachable == OUTCOME_VALUES, (
        f"labels never mapped to any classe: {OUTCOME_VALUES - reachable}"
    )


def test_every_classe_set_is_subset_of_outcome_values():
    for classe, labels in CLASSE_OUTCOME_MAP.items():
        stray = labels - OUTCOME_VALUES
        assert not stray, f"classe {classe!r} has unknown labels: {stray}"


def test_hc_has_writ_style_labels():
    # HC terminates with the ordem concedida/denegada family, never
    # with appeal (provido) or action (procedente) verbs.
    hc = CLASSE_OUTCOME_MAP["HC"]
    assert {"concedido", "concedido_parcial", "denegado"} <= hc
    assert hc.isdisjoint({"provido", "provido_parcial", "nao_provido"})
    assert hc.isdisjoint({"procedente", "procedente_parcial", "improcedente"})


def test_re_has_appeal_style_labels():
    re_ = CLASSE_OUTCOME_MAP["RE"]
    assert {"provido", "provido_parcial", "nao_provido"} <= re_
    assert re_.isdisjoint({"concedido", "denegado"})
    assert re_.isdisjoint({"procedente", "improcedente"})


def test_adi_has_action_style_labels():
    adi = CLASSE_OUTCOME_MAP["ADI"]
    assert {"procedente", "procedente_parcial", "improcedente"} <= adi
    assert adi.isdisjoint({"concedido", "denegado"})
    assert adi.isdisjoint({"provido", "nao_provido"})


def test_every_classe_admits_universal_terminators():
    # Any process can end without a merits ruling — the court can
    # refuse to hear it (nao_conhecido), the case can become moot
    # (prejudicado), or it can be dismissed on procedural grounds
    # (extinto). These are universal across every classe.
    universals = {"nao_conhecido", "prejudicado", "extinto"}
    for classe, labels in CLASSE_OUTCOME_MAP.items():
        missing = universals - labels
        assert not missing, f"classe {classe!r} missing terminators: {missing}"
