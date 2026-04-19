"""Unit tests for src.analysis.text_norm.

Normalizes Brazilian legal names for grouping. Strips accents, folds
case, collapses whitespace, and produces a surname-based group key so
"JOÃO DA SILVA" and "Joao Silva" land in the same bucket.
"""

from __future__ import annotations

from judex.analysis.text_norm import normalize_name, surname_key


def test_normalize_strips_accents():
    assert normalize_name("João Silva") == "JOAO SILVA"


def test_normalize_uppercases():
    assert normalize_name("joao silva") == "JOAO SILVA"


def test_normalize_collapses_whitespace():
    assert normalize_name("  João    Silva  ") == "JOAO SILVA"


def test_normalize_handles_special_chars():
    assert normalize_name("José Ramón d'Ávila") == "JOSE RAMON D'AVILA"


def test_normalize_passes_empty():
    assert normalize_name("") == ""
    assert normalize_name("   ") == ""


def test_surname_key_drops_particles():
    # "de", "da", "dos", "do", "das" are Portuguese particles, not
    # surnames. Last meaningful token wins.
    assert surname_key("João da Silva") == "SILVA"
    assert surname_key("Maria dos Santos") == "SANTOS"
    assert surname_key("Pedro de Oliveira") == "OLIVEIRA"


def test_surname_key_handles_compound_surnames():
    # "Silva Santos" — we take the LAST token as the group key. Simple
    # rule, known to under-merge compound surnames (e.g. Santos Cruz vs
    # Pereira Cruz both land in "CRUZ").
    assert surname_key("João Silva Santos") == "SANTOS"


def test_surname_key_single_token():
    assert surname_key("Madonna") == "MADONNA"


def test_surname_key_is_idempotent_over_normalize():
    # Accent-normalized input must produce the same key.
    assert surname_key("João Silva") == surname_key("Joao Silva")
    assert surname_key("José Ramón") == surname_key("Jose Ramon")


def test_surname_key_ignores_trailing_particle():
    # Edge case: name ending in particle (shouldn't happen, but be
    # defensive).
    assert surname_key("João da") == "JOAO"
