"""Behavior tests for the Unstructured OCR provider."""

from __future__ import annotations

from typing import Any

from src.scraping.ocr import OCRConfig, ExtractResult
from src.scraping.ocr import unstructured as u


def test_concat_elements_joins_text_fields_in_order():
    elements = [
        {"type": "Title", "text": "HABEAS CORPUS 12345"},
        {"type": "NarrativeText", "text": "O Ministro Relator..."},
        {"type": "ListItem", "text": "(a) fundamento primeiro"},
    ]
    assert u._concat_elements(elements) == (
        "HABEAS CORPUS 12345\nO Ministro Relator...\n(a) fundamento primeiro"
    )


def test_concat_elements_skips_empty_and_nondict():
    elements = [None, "stringy", {"text": "   "}, {"text": "Kept"}]
    assert u._concat_elements(elements) == "Kept"


def test_concat_elements_empty_input():
    assert u._concat_elements([]) == ""
    assert u._concat_elements(None) == ""


def test_extract_returns_text_and_raw_elements(monkeypatch):
    """The element list survives alongside the joined text — the
    `peca_cache.write_elements` consumer requires the raw list, not just
    text. Regressing this contract would silently disable the elements
    cache on every OCR'd document.
    """
    elements = [
        {"type": "Title", "text": "HC 999"},
        {"type": "NarrativeText", "text": "Body.", "metadata": {"page_number": 1}},
    ]

    class _Resp:
        def raise_for_status(self) -> None: pass
        def json(self) -> Any: return elements

    monkeypatch.setattr(u.requests, "post", lambda *a, **kw: _Resp())

    cfg = OCRConfig(provider="unstructured", api_key="k")
    out = u.extract(b"%PDF-1.4 fake", config=cfg)
    assert isinstance(out, ExtractResult)
    assert out.text == "HC 999\nBody."
    assert out.elements == elements
    assert out.provider == "unstructured"


def test_extract_handles_non_list_response(monkeypatch):
    """A 200-but-malformed response (string, dict, null) shouldn't crash —
    surface as empty result, let the caller's monotonic guard preserve
    the prior cached text.
    """
    class _Resp:
        def raise_for_status(self) -> None: pass
        def json(self) -> Any: return {"unexpected": "shape"}

    monkeypatch.setattr(u.requests, "post", lambda *a, **kw: _Resp())
    cfg = OCRConfig(provider="unstructured", api_key="k")
    out = u.extract(b"%PDF-1.4", config=cfg)
    assert out.text == ""
    assert out.elements == []
