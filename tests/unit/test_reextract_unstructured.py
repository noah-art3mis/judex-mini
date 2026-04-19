"""Unit tests for the generic OCR re-extraction script.

The provider plumbing itself is tested in `tests/unit/test_ocr_*`; here
we focus on the script's own concerns: the `_concat_elements` helper,
the candidate classifier, and the monotonic-vs-force behavior of
`_make_fetcher`.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.reextract_unstructured import (
    _concat_elements,
    _classify_candidates,
    _make_fetcher,
)
from src.scraping.ocr.base import ExtractResult, OCRConfig
from src.sweeps.pdf_targets import PdfTarget
from src.utils import pdf_cache


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


# ----- Candidate classifier ------------------------------------------------


def _fake_response(body: bytes):
    class _Resp:
        content = body

        def raise_for_status(self) -> None:
            pass
    return _Resp()


def test_classify_candidates_splits_by_cache_length(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_cache, "CACHE_ROOT", tmp_path)
    pdf_cache.write("https://x/short.pdf", "x" * 50)
    pdf_cache.write("https://x/long.pdf",  "x" * 5000)
    targets = [
        PdfTarget(url="https://x/no-cache.pdf"),
        PdfTarget(url="https://x/short.pdf"),
        PdfTarget(url="https://x/long.pdf"),
    ]
    cands, cached_ok, no_cache = _classify_candidates(
        targets, min_chars=1000, force=False,
    )
    urls = [t.url for t, _ in cands]
    assert urls == ["https://x/no-cache.pdf", "https://x/short.pdf"]
    assert cached_ok == 1  # long.pdf
    assert no_cache == 1   # no-cache.pdf


def test_classify_candidates_force_includes_long_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_cache, "CACHE_ROOT", tmp_path)
    pdf_cache.write("https://x/long.pdf", "x" * 5000)
    targets = [PdfTarget(url="https://x/long.pdf")]
    cands, cached_ok, no_cache = _classify_candidates(
        targets, min_chars=1000, force=True,
    )
    assert [t.url for t, _ in cands] == ["https://x/long.pdf"]
    assert cached_ok == 0


# ----- Monotonic guard vs --force -----------------------------------------


def _ocr_cfg(provider: str = "mistral") -> OCRConfig:
    return OCRConfig(provider=provider, api_key="k")


@pytest.fixture
def patched_session_and_extract(monkeypatch):
    """Patch `_http_get_with_retry` + `extract_pdf` with controllable doubles."""
    calls: dict[str, Any] = {"extract_pdf_result": None}

    def fake_get(session, url, *, config=None, timeout=90):
        return _fake_response(b"%PDF-1.4 fake body")

    def fake_extract(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
        return calls["extract_pdf_result"]

    monkeypatch.setattr(
        "scripts.reextract_unstructured._http_get_with_retry", fake_get,
    )
    monkeypatch.setattr(
        "scripts.reextract_unstructured.extract_pdf", fake_extract,
    )
    return calls


def test_monotonic_guard_rejects_shorter_output(patched_session_and_extract):
    """Default behavior: new text shorter than cached -> status=unchanged,
    driver-side cache write skipped (text=None returned)."""
    patched_session_and_extract["extract_pdf_result"] = ExtractResult(
        text="short", elements=[{"text": "short"}], provider="mistral",
    )
    f = _make_fetcher(
        ocr_config=_ocr_cfg(),
        old_len_by_url={"https://x/a.pdf": 1000},
        force=False,
    )
    text, extractor, status = f(object(), PdfTarget(url="https://x/a.pdf"), None)
    assert status == "unchanged"
    assert text is None          # driver will skip pdf_cache.write
    assert extractor == "mistral"


def test_force_bypasses_monotonic_guard(patched_session_and_extract):
    """Under --force, shorter new text still wins — driver writes it."""
    patched_session_and_extract["extract_pdf_result"] = ExtractResult(
        text="short", elements=[{"text": "short"}], provider="mistral",
    )
    f = _make_fetcher(
        ocr_config=_ocr_cfg(),
        old_len_by_url={"https://x/a.pdf": 1000},
        force=True,
    )
    text, extractor, status = f(object(), PdfTarget(url="https://x/a.pdf"), None)
    assert status == "ok"
    assert text == "short"        # driver will pdf_cache.write(text, extractor=...)
    assert extractor == "mistral"


def test_longer_output_always_wins_even_without_force(patched_session_and_extract):
    patched_session_and_extract["extract_pdf_result"] = ExtractResult(
        text="a much longer extraction", elements=None, provider="mistral",
    )
    f = _make_fetcher(
        ocr_config=_ocr_cfg(),
        old_len_by_url={"https://x/a.pdf": 5},
        force=False,
    )
    text, extractor, status = f(object(), PdfTarget(url="https://x/a.pdf"), None)
    assert status == "ok"
    assert text == "a much longer extraction"


def test_empty_output_under_force_is_empty_not_ok(patched_session_and_extract):
    """Force doesn't mean writing garbage. Empty text still = empty."""
    patched_session_and_extract["extract_pdf_result"] = ExtractResult(
        text="", elements=None, provider="mistral",
    )
    f = _make_fetcher(
        ocr_config=_ocr_cfg(),
        old_len_by_url={"https://x/a.pdf": 100},
        force=True,
    )
    text, extractor, status = f(object(), PdfTarget(url="https://x/a.pdf"), None)
    assert status == "empty"
    assert text is None
