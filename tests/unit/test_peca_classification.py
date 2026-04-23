"""Behavior tests for the tier-C substantive filter."""

from __future__ import annotations

from judex.sweeps.peca_classification import (
    TIER_C_DOC_TYPES,
    filter_substantive,
    summarize_tipos,
)
from judex.sweeps.peca_targets import PecaTarget


def _target(doc_type: str | None, url: str = "https://example/x") -> PecaTarget:
    return PecaTarget(url=url, classe="HC", processo_id=1, doc_type=doc_type)


def test_filter_drops_tier_c_tipos():
    targets = [
        _target("DECISÃO MONOCRÁTICA",            "u1"),   # tier A → keep
        _target("INTEIRO TEOR DO ACÓRDÃO",        "u2"),   # tier A → keep
        _target("MANIFESTAÇÃO DA PGR",            "u3"),   # tier A → keep
        _target("DESPACHO",                        "u4"),  # tier B → keep (no length pre-download)
        _target("CERTIDÃO DE TRÂNSITO EM JULGADO", "u5"),  # tier C → drop
        _target("CERTIDÃO",                        "u6"),  # tier C → drop
        _target("DECISÃO DE JULGAMENTO",           "u7"),  # tier C → drop
        _target("VISTA À PGR",                     "u8"),  # tier C → drop
    ]

    kept = filter_substantive(targets)
    kept_urls = {t.url for t in kept}

    assert kept_urls == {"u1", "u2", "u3", "u4"}


def test_filter_keeps_unknown_doc_type():
    # None can't be classified pre-download; err on inclusion.
    targets = [_target(None, "u_unknown"), _target("CERTIDÃO", "u_known_c")]
    kept = filter_substantive(targets)

    assert {t.url for t in kept} == {"u_unknown"}


def test_filter_is_accent_and_case_insensitive():
    # Labeling drift — accent/case variants of known tier-C tipos must
    # still match, so a future STF convention change doesn't silently
    # re-enable the filter for those tipos.
    targets = [
        _target("certidão",                       "u_lower_accent"),  # drop
        _target("CERTIDAO",                       "u_upper_noacc"),   # drop
        _target("Certidão",                       "u_titlecase"),     # drop
        _target("VISTA A PGR",                    "u_noacc"),         # drop
        _target("  CERTIDÃO  ",                   "u_padded"),        # drop (strip)
    ]
    kept = filter_substantive(targets)
    assert kept == [], f"expected all dropped, got {[t.url for t in kept]}"


def test_filter_is_fail_open_on_genuinely_new_tipos():
    # A tipo that doesn't fold to any classified entry must pass
    # through. This is the safety net against silent data loss when
    # STF introduces a new label we've never seen.
    targets = [
        _target("NOTA DE SANEAMENTO",  "u_new"),
        _target("OFÍCIO DE EXTENSÃO",  "u_brand_new"),
    ]
    kept = filter_substantive(targets)
    assert {t.url for t in kept} == {"u_new", "u_brand_new"}


def test_summarize_tipos_returns_top_and_unseen():
    # Mix of classified + unclassified; top-N reporting + unseen-detection.
    targets = (
        [_target("DECISÃO MONOCRÁTICA", f"u_dm_{i}") for i in range(3)]
        + [_target("DESPACHO", f"u_dp_{i}") for i in range(2)]
        + [_target("NOTA DE SANEAMENTO", "u_new_1"),
           _target("NOTA DE SANEAMENTO", "u_new_2"),
           _target(None, "u_null")]
    )

    top, unseen = summarize_tipos(targets, top_n=3)

    top_map = dict(top)
    assert top_map["DECISÃO MONOCRÁTICA"] == 3
    assert top_map["DESPACHO"] == 2
    assert unseen == {"NOTA DE SANEAMENTO": 2}, unseen


def test_summarize_tipos_accent_variant_not_flagged_as_unseen():
    # A folded-match of a known tipo shouldn't show up as "unseen",
    # because we consider it a case/accent drift of a classified tipo.
    targets = [_target("certidao", "u_folded"), _target("CERTIDÃO", "u_canonical")]
    _top, unseen = summarize_tipos(targets)
    assert unseen == {}, unseen


def test_tier_c_includes_the_high_volume_stubs():
    # Sanity: the stubs observed as >1k HC rows each are in the set.
    must_contain = {
        "CERTIDÃO DE TRÂNSITO EM JULGADO",
        "CERTIDÃO",
        "DECISÃO DE JULGAMENTO",
        "COMUNICAÇÃO ASSINADA",
        "CERTIDÃO DE JULGAMENTO",
        "TERMO DE REMESSA",
        "VISTA À PGR",
        "TERMO DE BAIXA",
    }
    assert must_contain.issubset(TIER_C_DOC_TYPES)
