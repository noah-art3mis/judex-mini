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
