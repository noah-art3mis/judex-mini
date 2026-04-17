"""Unit tests for the Unstructured-API re-extraction helpers."""

from scripts.reextract_unstructured import _concat_elements


def test_concat_elements_joins_text_fields_in_order():
    elements = [
        {"type": "Title", "text": "HABEAS CORPUS 12345"},
        {"type": "NarrativeText", "text": "O Ministro Relator..."},
        {"type": "ListItem", "text": "(a) fundamento primeiro"},
    ]
    assert _concat_elements(elements) == (
        "HABEAS CORPUS 12345\nO Ministro Relator...\n(a) fundamento primeiro"
    )


def test_concat_elements_skips_empty_and_missing_text():
    elements = [
        {"type": "Title", "text": "   "},
        {"type": "NarrativeText"},
        {"type": "NarrativeText", "text": "Kept"},
    ]
    assert _concat_elements(elements) == "Kept"


def test_concat_elements_tolerates_non_dict_rows():
    elements = [None, "stringy-row", {"text": "Kept"}]
    assert _concat_elements(elements) == "Kept"


def test_concat_elements_empty_input():
    assert _concat_elements([]) == ""
    assert _concat_elements(None) == ""
