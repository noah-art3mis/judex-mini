"""Tests for `judex/analysis/lawyer_canonical.py`.

Pin behavior of the lawyer-name canonicalizer + classifier used by
the volume / win / network notebooks. Four jobs:

1. Strip OAB parentheticals → return them as a tuple of codes.
2. Drop the "E OUTRO(A/S)" co-impetração tail (singular and plural).
3. Filter portal sentinels ("O MESMO" and variants) — these mean
   "same as previous IMPTE row" in the source HTML, not real parties,
   and inflate per-lawyer counts if left in.
4. Classify into LawyerKind categories — accent-insensitive for
   institutional matching, catches OAB codes outside parentheticals.
"""

from judex.analysis.lawyer_canonical import (
    LawyerKind,
    canonical_lawyer,
    classify,
)


# ----- 1. OAB parenthetical extraction --------------------------------

def test_extracts_single_oab_code():
    key, codes = canonical_lawyer("Alberto Zacharias Toron (12345/SP)")
    assert key == "ALBERTO ZACHARIAS TORON"
    assert codes == ("12345/SP",)


def test_extracts_multiple_oab_codes_from_one_paren():
    key, codes = canonical_lawyer("Fulano (12345/SP, 67890/RJ)")
    assert key == "FULANO"
    assert codes == ("12345/SP", "67890/RJ")


def test_no_oab_returns_empty_tuple():
    key, codes = canonical_lawyer("Defensoria Pública da União")
    assert key == "DEFENSORIA PÚBLICA DA UNIÃO"
    assert codes == ()


# ----- 2. "E OUTRO(A/S)" tail stripping --------------------------------

def test_strips_e_outro_singular():
    key, _ = canonical_lawyer("Fulano (12345/SP) E OUTRO")
    assert key == "FULANO"


def test_strips_e_outros_plural():
    """STF emits both singular and plural; the regex must catch both."""
    key, _ = canonical_lawyer("Fulano (12345/SP) E OUTROS")
    assert key == "FULANO"


def test_strips_e_outro_a_s_with_paren_form():
    """The original portal form is 'E OUTRO(A/S)' — the paren is
    stripped by the OAB regex, leaving 'E OUTRO' for the tail regex."""
    key, _ = canonical_lawyer("Fulano (12345/SP) E OUTRO(A/S)")
    assert key == "FULANO"


# ----- 3. Sentinel filtering ------------------------------------------
#
# When the canonicalized name is a portal sentinel meaning "same
# party as previous row," return ("", ()) so the caller's `if not key`
# guard drops the row.

def test_sentinel_o_mesmo():
    assert canonical_lawyer("O MESMO") == ("", ())


def test_sentinel_os_mesmos():
    assert canonical_lawyer("OS MESMOS") == ("", ())


def test_sentinel_a_mesma():
    assert canonical_lawyer("A MESMA") == ("", ())


def test_sentinel_o_mesm0_zero_typo():
    """Observed in 10 STF rows — zero substituted for capital O."""
    assert canonical_lawyer("O MESM0") == ("", ())


def test_sentinel_io_mesmo_typo():
    """Observed once in the corpus — leading 'I' typo on 'O MESMO'."""
    assert canonical_lawyer("IO MESMO") == ("", ())


def test_sentinel_with_internal_comma():
    """STF formatter occasionally inserts a stray comma: 'O ,MESMO'."""
    assert canonical_lawyer("O ,MESMO") == ("", ())


def test_sentinel_with_e_outro_tail():
    """Sentinel can carry the co-impetração tail: 'O MESMO E OUTRO'."""
    assert canonical_lawyer("O MESMO E OUTRO") == ("", ())


def test_sentinel_with_e_outros_tail_plural():
    assert canonical_lawyer("O MESMO E OUTROS") == ("", ())


# ----- 3b. Negative cases — names that LOOK sentinel-ish ---------------
#
# These pin against an over-eager filter. STF has real lawyers whose
# names contain MESMO-like or IDEM-like substrings; previous attempts
# at "filter by substring" have hit false positives.

def test_real_name_with_idem_substring_kept():
    """'SIDEMI' contains 'IDEM'; must not be filtered."""
    key, _ = canonical_lawyer("SIDEMI DOS SANTOS DUARTE")
    assert key == "SIDEMI DOS SANTOS DUARTE"


def test_real_name_with_idem_substring_in_compound():
    """'HEIDEMANN' contains 'IDEM'; must not be filtered."""
    key, codes = canonical_lawyer("Norbert Heidemann (00038347/PR)")
    assert key == "NORBERT HEIDEMANN"
    assert codes == ("00038347/PR",)


# ----- 4. classify() — LawyerKind buckets ------------------------------
#
# These pin behavior surfaced by a full-corpus stress test (all unique
# ADV + IMPTE names in the HC warehouse). Each case represents a real
# failure mode of the pre-classify era, when notebooks rolled their
# own prefix lists.

# --- SENTINEL (delegates to canonical_lawyer) ---

def test_classify_sentinel_o_mesmo():
    entry = classify("O MESMO")
    assert entry.kind == LawyerKind.SENTINEL
    assert entry.key == ""
    assert entry.oab_codes == ()


# --- PLACEHOLDER ---

def test_classify_placeholder_sem_representacao():
    entry = classify("SEM REPRESENTAÇÃO NOS AUTOS")
    assert entry.kind == LawyerKind.PLACEHOLDER


def test_classify_placeholder_accentless():
    """Catches the missing-accent variant."""
    entry = classify("SEM REPRESENTACAO NOS AUTOS")
    assert entry.kind == LawyerKind.PLACEHOLDER


# --- PRO_SE ---

def test_classify_pro_se():
    entry = classify("EM CAUSA PROPRIA")
    assert entry.kind == LawyerKind.PRO_SE


def test_classify_pro_se_with_accent():
    entry = classify("EM CAUSA PRÓPRIA")
    assert entry.kind == LawyerKind.PRO_SE


# --- INSTITUTIONAL — the main point of adding classify() ---

def test_classify_institutional_accented():
    entry = classify("DEFENSOR PÚBLICO-GERAL FEDERAL")
    assert entry.kind == LawyerKind.INSTITUTIONAL
    assert entry.key == "DEFENSOR PÚBLICO-GERAL FEDERAL"


def test_classify_institutional_accentless_variant():
    """STF data-entry often drops acutes; 4.7k rows in the HC corpus
    read 'DEFENSORIA PUBLICA DA UNIAO' without accents. Must be
    classified as institutional, not as a bare lawyer name."""
    entry = classify("DEFENSORIA PUBLICA DA UNIAO")
    assert entry.kind == LawyerKind.INSTITUTIONAL


def test_classify_institutional_agu():
    entry = classify("ADVOGADO-GERAL DA UNIÃO")
    assert entry.kind == LawyerKind.INSTITUTIONAL


def test_classify_institutional_pgr():
    entry = classify("PROCURADOR-GERAL DA REPÚBLICA")
    assert entry.kind == LawyerKind.INSTITUTIONAL


# --- JURIDICAL (law firm / union / federation / institute) ---

def test_classify_juridical_law_firm():
    entry = classify("ARAGÃO E TOMAZ ADVOGADOS ASSOCIADOS")
    assert entry.kind == LawyerKind.JURIDICAL


def test_classify_juridical_sindicato():
    entry = classify("SINDICATO DOS TRABALHADORES DA JUSTIÇA DO TRABALHO")
    assert entry.kind == LawyerKind.JURIDICAL


def test_classify_juridical_federacao():
    entry = classify("FEDERAÇÃO NACIONAL DOS TRABALHADORES")
    assert entry.kind == LawyerKind.JURIDICAL


def test_classify_juridical_advocacia_suffix():
    entry = classify("JORGE E OLIVEIRA ADVOCACIA")
    assert entry.kind == LawyerKind.JURIDICAL


# --- COURT — judicial authority as party ---

def test_classify_court_juizo():
    entry = classify("JUÍZO DE DIREITO DA 2ª VARA CRIMINAL DE MOGI DAS CRUZES/SP")
    assert entry.kind == LawyerKind.COURT


def test_classify_court_relator():
    entry = classify("RELATOR DO RHC Nº 50520 DO SUPERIOR TRIBUNAL DE JUSTIÇA")
    assert entry.kind == LawyerKind.COURT


# --- WITH_OAB — parenthetical (delegated to canonical_lawyer) + others ---

def test_classify_with_oab_parenthetical():
    entry = classify("Alberto Zacharias Toron (12345/SP)")
    assert entry.kind == LawyerKind.WITH_OAB
    assert "12345/SP" in entry.oab_codes


def test_classify_with_oab_non_parenthetical_slash_form():
    """Non-parenthetical OAB: 'NOME, OAB/SP 148022' — real in corpus."""
    entry = classify("WILLEY LOPES SUCASAS, OAB/SP 148022")
    assert entry.kind == LawyerKind.WITH_OAB
    assert any(c.endswith("/SP") for c in entry.oab_codes)


def test_classify_with_oab_non_parenthetical_dash_form():
    """'OAB-PE 48215' form — dash separator, no slash in code."""
    entry = classify("MÁRIO JOSÉ DE AQUINO NETO OAB-PE 48215")
    assert entry.kind == LawyerKind.WITH_OAB
    assert any(c.endswith("/PE") for c in entry.oab_codes)


def test_classify_with_oab_thousands_dot_stripped():
    """'OAB/SP 394.151' — thousands-dot in the number; strip it."""
    entry = classify("SOLANGELA MARINS PIERANI OAB/SP 394.151")
    assert entry.kind == LawyerKind.WITH_OAB
    assert "394151/SP" in entry.oab_codes


# --- BARE — real lawyer but OAB not in data ---

def test_classify_bare_real_lawyer():
    """Observed in corpus — real private lawyer, no OAB captured."""
    entry = classify("ALBERTO MACHADO CASCAIS MELEIRO")
    assert entry.kind == LawyerKind.BARE
    assert entry.key == "ALBERTO MACHADO CASCAIS MELEIRO"


# --- Regression: institutional substring does NOT false-positive ---

def test_classify_real_name_containing_sindicato_substring_not_juridical():
    """Prefix match must be anchored at start. A (hypothetical) lawyer
    whose name happens to contain 'SINDICATO' mid-string should not
    be classified as JURIDICAL."""
    entry = classify("JOÃO DA SILVA SINDICATO")
    assert entry.kind != LawyerKind.JURIDICAL
