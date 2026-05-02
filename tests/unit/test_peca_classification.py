"""Behavior tests for the tier-C substantive filter."""

from __future__ import annotations

from judex.sweeps.peca_classification import (
    TIER_C_DOC_TYPES,
    filter_substantive,
    summarize_tipos,
)
from judex.sweeps.peca_targets import PecaTarget


def _target(
    doc_type: str | None,
    url: str = "https://example/x",
    *,
    surface: str | None = None,
) -> PecaTarget:
    return PecaTarget(
        url=url, classe="HC", processo_id=1, doc_type=doc_type, surface=surface,
    )


def test_filter_drops_tier_c_tipos():
    targets = [
        _target("DECISÃO MONOCRÁTICA",            "u1"),   # tier A → keep
        _target("INTEIRO TEOR DO ACÓRDÃO",        "u2"),   # tier A → keep
        _target("MANIFESTAÇÃO DA PGR",            "u3"),   # tier A → keep
        _target("DESPACHO",                        "u4"),  # tier B → keep (no length pre-download)
        _target("DECISÃO DE JULGAMENTO",           "u5"),  # tier B → keep (panel-result stub)
        _target("CERTIDÃO DE TRÂNSITO EM JULGADO", "u6"),  # tier C → drop
        _target("CERTIDÃO",                        "u7"),  # tier C → drop
        _target("VISTA À PGR",                     "u8"),  # tier C → drop
    ]

    kept = filter_substantive(targets)
    kept_urls = {t.url for t in kept}

    assert kept_urls == {"u1", "u2", "u3", "u4", "u5"}


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


def test_filter_keeps_all_sessao_virtual_documentos():
    # ADR-0001 step 2 resolves the "open question" on surface-aware
    # filtering: sessao_virtual[].documentos[] only ever carries
    # substantive content (Relatório, Voto, Voto Vista) — there is
    # no procedural noise on this surface to strip. The TIER_C
    # filter's existing fail-open behaviour is therefore the correct
    # behaviour for surface=sessao_virtual targets, not a placeholder.
    targets = [
        _target("Relatório",   "u_relatorio",   surface="sessao_virtual"),
        _target("Voto",        "u_voto",        surface="sessao_virtual"),
        _target("Voto Vista",  "u_voto_vista",  surface="sessao_virtual"),
    ]
    kept = filter_substantive(targets)
    assert {t.url for t in kept} == {"u_relatorio", "u_voto", "u_voto_vista"}


def test_filter_keeps_all_dje_decisoes():
    # Surface 3 (publicacoes_dje[].decisoes[].rtf) only emits
    # `kind ∈ {"decisao", "ementa"}` — both substantive. Same
    # rationale as sessao_virtual: fail-open is the right semantics,
    # not a deferred decision (resolves ADR-0001 § Consequences
    # bullet 3).
    targets = [
        _target("decisao",  "u_dec",  surface="dje"),
        _target("ementa",   "u_em",   surface="dje"),
    ]
    kept = filter_substantive(targets)
    assert {t.url for t in kept} == {"u_dec", "u_em"}


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


def test_summarize_tipos_does_not_flag_sessao_virtual_tier_a_tipos():
    # Surface-2 (sessao_virtual) tipos are first-class Tier A entries
    # since ADR-0001. They must not surface in the unseen-tipo warning,
    # otherwise every HC sweep prints noise for tipos we've explicitly
    # classified as substantive.
    targets = [
        _target("Relatório",  "u_relatorio",  surface="sessao_virtual"),
        _target("Voto",       "u_voto",       surface="sessao_virtual"),
        _target("Voto Vogal", "u_voto_vogal", surface="sessao_virtual"),
        _target("Voto Vista", "u_voto_vista", surface="sessao_virtual"),
    ]
    _top, unseen = summarize_tipos(targets)
    assert unseen == {}, unseen


def test_tier_c_includes_the_high_volume_stubs():
    # Sanity: the stubs observed as >1k HC rows each are in the set.
    must_contain = {
        "CERTIDÃO DE TRÂNSITO EM JULGADO",
        "CERTIDÃO",
        "COMUNICAÇÃO ASSINADA",
        "CERTIDÃO DE JULGAMENTO",
        "TERMO DE REMESSA",
        "VISTA À PGR",
        "TERMO DE BAIXA",
    }
    assert must_contain.issubset(TIER_C_DOC_TYPES)
