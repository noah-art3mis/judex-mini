"""clean_pdf_text — postprocessing of pypdf extractions.

pypdf reads the PDF text layer glyph-by-glyph; when STF's headers use
letter-spacing/kerning, the extracted text comes out split:
``S ÃO PAULO``, ``H C N º 632.905``, ``S UPERIOR TRIBUNAL``. The
cleanup function rejoins these without damaging legitimate prose
(e.g. a Portuguese article ``A`` followed by a word must survive).

Behavior contract:
- Idempotent: running twice equals running once.
- Aggressive rejoin only in all-caps header lines (threshold ≥ 80%
  uppercase among letters).
- Safe token-level fixes everywhere: ``N º`` → ``Nº``, ``H C`` → ``HC``.
- Never merges legitimate Portuguese single-letter articles in
  mixed-case prose.
"""

from __future__ import annotations

from judex.scraping.ocr.cleanup import clean_pdf_text


def test_rejoins_split_caps_in_allcaps_header() -> None:
    src = "HABEAS CORPUS 195.830 S ÃO PAULO\nRELATOR : MIN. MARCO AURÉLIO\n"
    out = clean_pdf_text(src)
    assert "SÃO PAULO" in out
    assert "S ÃO" not in out


def test_rejoins_case_numero_token() -> None:
    src = "COATOR : RELATOR DO H C N º 632.905 DO STJ"
    out = clean_pdf_text(src)
    assert "HC" in out
    assert "Nº 632.905" in out
    assert "N º" not in out


def test_preserves_portuguese_article_in_prose() -> None:
    # 'A' as a definite article followed by a word in lowercase prose
    # must not be merged. The test line is majority lowercase → aggressive
    # rejoin must NOT fire.
    src = "O réu pediu A SE defender em juízo apresentando argumentos."
    out = clean_pdf_text(src)
    # ASE would be the bug; make sure the space is preserved
    assert "A SE" in out or "a se" in out.lower()
    assert "ASE" not in out


def test_rejoins_long_caps_word_spread_across_spaces() -> None:
    src = "PRIMEIRA TURMA\nS UPERIOR TRIBUNAL DE JUSTIÇA\n"
    out = clean_pdf_text(src)
    assert "SUPERIOR TRIBUNAL" in out
    assert "S UPERIOR" not in out


def test_is_idempotent() -> None:
    """Cleaning cleaned text produces the same text."""
    src = "H C N º 632.905 S ÃO PAULO\nS UPERIOR TRIBUNAL DE JUSTIÇA\n"
    once = clean_pdf_text(src)
    twice = clean_pdf_text(once)
    assert once == twice


def test_collapses_triple_blank_lines_to_double() -> None:
    src = "paragraph one\n\n\n\nparagraph two\n"
    out = clean_pdf_text(src)
    # Exactly two \n between paragraphs (one blank line)
    assert "paragraph one\n\nparagraph two" in out
    assert "\n\n\n" not in out


def test_preserves_e_conjunction_in_allcaps_header() -> None:
    """The Portuguese conjunction 'E' between all-caps names must not be
    merged with the following word. This is an STF party-list pattern:
    'ALBERTO ZACHARIAS TORON E OUTRO(A/S)' must stay 'TORON E OUTRO'.
    """
    src = "IMPTE.(S) :ALBERTO ZACHARIAS TORON E OUTRO(A/S)\n"
    out = clean_pdf_text(src)
    assert "TORON E OUTRO" in out
    assert "EOUTRO" not in out


def test_preserves_a_preposition_in_allcaps_header() -> None:
    """'A' as a Portuguese preposition/article in an all-caps header
    must not be merged with the following word.
    """
    src = "DESCUMPRIMENTO DE ORDEM A TODOS OS RÉUS\n"
    out = clean_pdf_text(src)
    assert "A TODOS" in out
    assert "ATODOS" not in out


def test_collapses_double_spaces_to_single() -> None:
    # STF headers sometimes have runs of spaces from column reconstruction
    src = "RELATOR  :  MIN. MARCO AURÉLIO"
    out = clean_pdf_text(src)
    assert "  " not in out
    assert "RELATOR : MIN. MARCO AURÉLIO" in out
