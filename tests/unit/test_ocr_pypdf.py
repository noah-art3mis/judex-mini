"""Behavior tests for the pypdf provider (the free/fast first tier)."""

from __future__ import annotations

from src.scraping.ocr import OCRConfig, ExtractResult
from src.scraping.ocr import pypdf as p


class _FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakeReader:
    def __init__(self, pages: list[str]) -> None:
        self.pages = [_FakePage(t) for t in pages]


def test_extract_joins_pages_and_labels_provider(monkeypatch) -> None:
    """Concatenates page text across a multi-page PDF, tags provider=pypdf.

    This is the contract the download/extract split relies on: the
    extract driver calls `extract_pdf(bytes, config=OCRConfig(provider="pypdf"))`
    and writes `result.text` + extractor="pypdf" to the cache.
    """
    monkeypatch.setattr(
        p, "PdfReader", lambda _buf: _FakeReader(["Page one.", "Page two."])
    )
    cfg = OCRConfig(provider="pypdf", api_key="")

    out = p.extract(b"%PDF-1.4 fake bytes", config=cfg)

    assert isinstance(out, ExtractResult)
    assert out.text == "Page one.\nPage two."
    assert out.elements is None
    assert out.pages_processed == 2
    assert out.provider == "pypdf"


def test_extract_empty_pages_returns_empty_text(monkeypatch) -> None:
    """A PDF whose text layer returns nothing yields text="" (not raise).

    The driver interprets empty text as status=empty and skips the
    cache write. Raising here would mask that distinction as an error.
    """
    monkeypatch.setattr(p, "PdfReader", lambda _buf: _FakeReader(["", ""]))
    cfg = OCRConfig(provider="pypdf", api_key="")

    out = p.extract(b"%PDF-1.4 empty", config=cfg)

    assert out.text == ""
    assert out.pages_processed == 2
    assert out.provider == "pypdf"


def test_dispatcher_routes_pypdf_provider(monkeypatch) -> None:
    """`extract_pdf(bytes, config(provider='pypdf'))` reaches the new module.

    Guards the registry wiring: if someone registers pypdf under a
    different key (e.g. "pypdf_plain"), the CLI surface breaks silently.
    """
    from src.scraping.ocr import dispatch, extract_pdf

    assert "pypdf" in dispatch._REGISTRY  # positive assertion, not just routing

    monkeypatch.setattr(p, "PdfReader", lambda _buf: _FakeReader(["routed"]))
    out = extract_pdf(b"%PDF-1.4", config=OCRConfig(provider="pypdf", api_key=""))
    assert out.text == "routed"
    assert out.provider == "pypdf"
