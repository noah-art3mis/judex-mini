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


def test_extract_with_unstructured_returns_text_and_raw_elements(monkeypatch):
    """The element list survives alongside the joined text.

    Downstream consumers (the structure-aware elements cache) depend
    on the raw list, not just the concatenated text. Regressing this
    return contract would silently disable `pdf_cache.write_elements`.
    """
    import types
    from scripts import reextract_unstructured as r

    elements = [
        {"type": "Title", "text": "HC 999"},
        {"type": "NarrativeText", "text": "Body.", "metadata": {"page_number": 1}},
    ]

    class _Resp:
        status_code = 200
        def raise_for_status(self) -> None: pass
        def json(self): return elements

    monkeypatch.setattr(r.requests, "post", lambda *a, **kw: _Resp())

    text, got = r._extract_with_unstructured(
        b"%PDF-1.4 fake", api_url="https://x", api_key="k",
    )
    assert text == "HC 999\nBody."
    assert got == elements  # raw list round-trips
