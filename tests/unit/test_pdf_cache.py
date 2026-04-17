"""URL-keyed cache for extracted PDF text.

The cache lets repeated scrapes skip re-downloading PDFs that STF
serves from the repgeral endpoint. Keyed by sha1(url) so the on-disk
layout stays flat.
"""

from __future__ import annotations

from src.utils import pdf_cache


def test_read_miss_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pdf_cache, "CACHE_ROOT", tmp_path)

    assert pdf_cache.read("https://example.test/a.pdf") is None


def test_read_after_write_returns_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pdf_cache, "CACHE_ROOT", tmp_path)

    pdf_cache.write("https://example.test/a.pdf", "hello world")

    assert pdf_cache.read("https://example.test/a.pdf") == "hello world"


def test_different_urls_stored_separately(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pdf_cache, "CACHE_ROOT", tmp_path)

    pdf_cache.write("https://example.test/a.pdf", "A")
    pdf_cache.write("https://example.test/b.pdf", "B")

    assert pdf_cache.read("https://example.test/a.pdf") == "A"
    assert pdf_cache.read("https://example.test/b.pdf") == "B"


def test_write_overwrites(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pdf_cache, "CACHE_ROOT", tmp_path)

    pdf_cache.write("https://example.test/a.pdf", "old")
    pdf_cache.write("https://example.test/a.pdf", "new")

    assert pdf_cache.read("https://example.test/a.pdf") == "new"


# ----- Parallel elements-cache (structured OCR output) ---------------------


def test_read_elements_miss_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pdf_cache, "CACHE_ROOT", tmp_path)

    assert pdf_cache.read_elements("https://example.test/a.pdf") is None


def test_write_and_read_elements_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pdf_cache, "CACHE_ROOT", tmp_path)

    elements = [
        {"type": "Title", "text": "HABEAS CORPUS 135041"},
        {"type": "NarrativeText", "text": "Relatório e Voto.",
         "metadata": {"page_number": 1}},
        {"type": "Header", "text": "Supremo Tribunal Federal"},
    ]
    pdf_cache.write_elements("https://example.test/a.pdf", elements)

    got = pdf_cache.read_elements("https://example.test/a.pdf")
    assert got == elements


def test_elements_cache_is_separate_from_text_cache(tmp_path, monkeypatch) -> None:
    """Writing elements doesn't populate the text cache and vice versa."""
    monkeypatch.setattr(pdf_cache, "CACHE_ROOT", tmp_path)

    pdf_cache.write("https://example.test/a.pdf", "flat text")
    assert pdf_cache.read_elements("https://example.test/a.pdf") is None

    pdf_cache.write_elements(
        "https://example.test/b.pdf", [{"type": "Title", "text": "x"}],
    )
    assert pdf_cache.read("https://example.test/b.pdf") is None


def test_elements_file_is_gzipped_json(tmp_path, monkeypatch) -> None:
    """Written file is `.elements.json.gz`, decompresses to valid JSON."""
    import gzip
    import json

    monkeypatch.setattr(pdf_cache, "CACHE_ROOT", tmp_path)

    pdf_cache.write_elements(
        "https://example.test/a.pdf", [{"type": "Title", "text": "hi"}],
    )
    files = list(tmp_path.glob("*.elements.json.gz"))
    assert len(files) == 1
    raw = gzip.decompress(files[0].read_bytes())
    parsed = json.loads(raw)
    assert parsed == [{"type": "Title", "text": "hi"}]
