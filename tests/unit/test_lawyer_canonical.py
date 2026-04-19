"""Tests for `src/analysis/lawyer_canonical.py`.

Pin behavior of the lawyer-name canonicalizer used by the volume / win
notebooks. Three jobs:

1. Strip OAB parentheticals → return them as a tuple of codes.
2. Drop the "E OUTRO(A/S)" co-impetração tail (singular and plural).
3. Filter portal sentinels ("O MESMO" and variants) — these mean
   "same as previous IMPTE row" in the source HTML, not real parties,
   and inflate per-lawyer counts if left in.
"""

from judex.analysis.lawyer_canonical import canonical_lawyer


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
