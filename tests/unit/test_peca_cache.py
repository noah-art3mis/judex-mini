"""URL-keyed cache for extracted PDF text.

The cache lets repeated scrapes skip re-downloading PDFs that STF
serves from the repgeral endpoint. Keyed by sha1(url) so the on-disk
layout stays flat.
"""

from __future__ import annotations

from judex.utils import peca_cache


def test_read_miss_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    assert peca_cache.read("https://example.test/a.pdf") is None


def test_read_after_write_returns_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    peca_cache.write("https://example.test/a.pdf", "hello world")

    assert peca_cache.read("https://example.test/a.pdf") == "hello world"


def test_different_urls_stored_separately(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    peca_cache.write("https://example.test/a.pdf", "A")
    peca_cache.write("https://example.test/b.pdf", "B")

    assert peca_cache.read("https://example.test/a.pdf") == "A"
    assert peca_cache.read("https://example.test/b.pdf") == "B"


def test_write_overwrites(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    peca_cache.write("https://example.test/a.pdf", "old")
    peca_cache.write("https://example.test/a.pdf", "new")

    assert peca_cache.read("https://example.test/a.pdf") == "new"


# ----- Parallel elements-cache (structured OCR output) ---------------------


def test_read_elements_miss_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    assert peca_cache.read_elements("https://example.test/a.pdf") is None


def test_write_and_read_elements_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    elements = [
        {"type": "Title", "text": "HABEAS CORPUS 135041"},
        {"type": "NarrativeText", "text": "Relatório e Voto.",
         "metadata": {"page_number": 1}},
        {"type": "Header", "text": "Supremo Tribunal Federal"},
    ]
    peca_cache.write_elements("https://example.test/a.pdf", elements)

    got = peca_cache.read_elements("https://example.test/a.pdf")
    assert got == elements


def test_elements_cache_is_separate_from_text_cache(tmp_path, monkeypatch) -> None:
    """Writing elements doesn't populate the text cache and vice versa."""
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    peca_cache.write("https://example.test/a.pdf", "flat text")
    assert peca_cache.read_elements("https://example.test/a.pdf") is None

    peca_cache.write_elements(
        "https://example.test/b.pdf", [{"type": "Title", "text": "x"}],
    )
    assert peca_cache.read("https://example.test/b.pdf") is None


def test_elements_file_is_gzipped_json(tmp_path, monkeypatch) -> None:
    """Written file is `.elements.json.gz`, decompresses to valid JSON."""
    import gzip
    import json

    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    peca_cache.write_elements(
        "https://example.test/a.pdf", [{"type": "Title", "text": "hi"}],
    )
    files = list(tmp_path.glob("*.elements.json.gz"))
    assert len(files) == 1
    raw = gzip.decompress(files[0].read_bytes())
    parsed = json.loads(raw)
    assert parsed == [{"type": "Title", "text": "hi"}]


# ----- Extractor sidecar (v4) ----------------------------------------------


def test_read_extractor_miss_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    assert peca_cache.read_extractor("https://example.test/a.pdf") is None


def test_write_with_extractor_persists_sidecar(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    peca_cache.write("https://example.test/a.pdf", "hello", extractor="pypdf_plain")

    assert peca_cache.read("https://example.test/a.pdf") == "hello"
    assert peca_cache.read_extractor("https://example.test/a.pdf") == "pypdf_plain"


def test_write_without_extractor_leaves_sidecar_untouched(tmp_path, monkeypatch) -> None:
    """Prior provenance must survive a text-only rewrite.

    The agreed contract is: passing `extractor=None` means "caller does
    not know" — not "wipe the known label". That way legacy writers
    (pre-v4 scripts) can overwrite cached text without destroying a
    label that an OCR pass previously recorded.
    """
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    peca_cache.write("https://example.test/a.pdf", "v1", extractor="unstructured")
    peca_cache.write("https://example.test/a.pdf", "v2")  # no extractor

    assert peca_cache.read("https://example.test/a.pdf") == "v2"
    assert peca_cache.read_extractor("https://example.test/a.pdf") == "unstructured"


def test_write_overwrites_extractor_sidecar_when_provided(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    peca_cache.write("https://example.test/a.pdf", "A", extractor="pypdf_plain")
    peca_cache.write("https://example.test/a.pdf", "B", extractor="unstructured")

    assert peca_cache.read_extractor("https://example.test/a.pdf") == "unstructured"


# ----- Text presence check (v8: cheap "was this URL extracted?") ----------


def test_has_text_false_when_missing(tmp_path, monkeypatch) -> None:
    """has_text is an O(1) file-stat — no read, no decompress."""
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    assert peca_cache.has_text("https://example.test/a.pdf") is False


def test_has_text_true_after_write(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)
    peca_cache.write("https://example.test/a.pdf", "body")

    assert peca_cache.has_text("https://example.test/a.pdf") is True


def test_has_text_independent_of_bytes_cache(tmp_path, monkeypatch) -> None:
    """The text + bytes caches are independent — `has_text` must only
    react to `.txt.gz`, not to `.pdf.gz` presence. This matters because
    the `baixar-pecas` / `extrair-pecas` split writes them at different
    stages (bytes first, text later)."""
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)
    peca_cache.write_bytes("https://example.test/a.pdf", b"%PDF-1.4\n...")

    # Bytes are there, but nothing was extracted yet.
    assert peca_cache.has_bytes("https://example.test/a.pdf") is True
    assert peca_cache.has_text("https://example.test/a.pdf") is False


# ----- Bytes cache (raw PDF storage for the download/extract split) --------


def test_has_bytes_false_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    assert peca_cache.has_bytes("https://example.test/a.pdf") is False


def test_read_bytes_miss_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    assert peca_cache.read_bytes("https://example.test/a.pdf") is None


def test_read_bytes_after_write_round_trips(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    body = b"%PDF-1.4\n...fake bytes...\n%%EOF"
    peca_cache.write_bytes("https://example.test/a.pdf", body)

    assert peca_cache.has_bytes("https://example.test/a.pdf") is True
    assert peca_cache.read_bytes("https://example.test/a.pdf") == body


def test_write_bytes_overwrites(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    peca_cache.write_bytes("https://example.test/a.pdf", b"v1")
    peca_cache.write_bytes("https://example.test/a.pdf", b"v2")

    assert peca_cache.read_bytes("https://example.test/a.pdf") == b"v2"


def test_bytes_file_is_gzipped_on_disk(tmp_path, monkeypatch) -> None:
    """Written file is `.pdf.gz` and decompresses to the original bytes."""
    import gzip

    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    body = b"%PDF-1.4\nraw pdf contents\n%%EOF"
    peca_cache.write_bytes("https://example.test/a.pdf", body)

    files = list(tmp_path.glob("*.pdf.gz"))
    assert len(files) == 1
    assert gzip.decompress(files[0].read_bytes()) == body


def test_bytes_cache_is_independent_from_text_cache(tmp_path, monkeypatch) -> None:
    """Writing bytes doesn't populate the text cache and vice versa."""
    monkeypatch.setattr(peca_cache, "PECAS_ROOT", tmp_path)
    monkeypatch.setattr(peca_cache, "TEXTO_ROOT", tmp_path)

    peca_cache.write_bytes("https://example.test/a.pdf", b"%PDF-1.4")
    assert peca_cache.read("https://example.test/a.pdf") is None
    assert peca_cache.read_extractor("https://example.test/a.pdf") is None

    peca_cache.write("https://example.test/b.pdf", "extracted text")
    assert peca_cache.has_bytes("https://example.test/b.pdf") is False
