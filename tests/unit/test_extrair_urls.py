"""Tests for ``judex.sweeps.extrair_urls`` — URL-scoped re-extraction.

Pins the contract from .scratch/per-url-extract/PRD.md:

- Reads bytes from peca_cache (no fetch logic — errors cleanly if missing).
- Idempotent on extractor sidecar: skips URLs whose existing extractor
  matches ``--provedor`` unless ``--forcar``.
- Filters blank lines and ``#``-comments from the URL list.
- Writes text + extractor sidecar back to peca_cache.
- Result counts (ok / skipped / missing_bytes / fail) sum to len(urls).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from judex.scraping.ocr.base import ExtractResult


@pytest.fixture
def stub_cache(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace peca_cache + extract_pdf with in-memory stubs.

    Returns the bookkeeping dict the test can poke at:
    ``bytes`` (url → bytes), ``extractor`` (url → str|None),
    ``writes`` (list of (url, text, extractor)),
    ``extract_calls`` (list of pdf_bytes, kwargs).
    """
    from judex.sweeps import extrair_urls
    from judex.utils import peca_cache

    state: dict[str, Any] = {
        "bytes": {},
        "extractor": {},
        "writes": [],
        "extract_calls": [],
    }

    monkeypatch.setattr(
        peca_cache, "read_bytes", lambda url: state["bytes"].get(url)
    )
    monkeypatch.setattr(
        peca_cache, "read_extractor", lambda url: state["extractor"].get(url)
    )

    def fake_write(url: str, text: str, *, extractor: str | None = None) -> None:
        state["writes"].append((url, text, extractor))
        state["extractor"][url] = extractor

    monkeypatch.setattr(peca_cache, "write", fake_write)

    def fake_extract(pdf_bytes: bytes, *, config: Any) -> ExtractResult:
        state["extract_calls"].append({"bytes": pdf_bytes, "provider": config.provider})
        return ExtractResult(
            text=f"OCR-of-{len(pdf_bytes)}-bytes",
            elements=None,
            pages_processed=1,
            provider=config.provider,
        )

    monkeypatch.setattr(extrair_urls, "extract_pdf", fake_extract)
    return state


def _write_urls(tmp_path: Path, *urls: str) -> Path:
    p = tmp_path / "urls.txt"
    p.write_text("\n".join(urls) + "\n", encoding="utf-8")
    return p


def test_extrair_urls_happy_path(tmp_path: Path, stub_cache: dict[str, Any]) -> None:
    """Two URLs both have cached bytes → both get OCR'd and written."""
    from judex.sweeps.extrair_urls import run_extrair_urls

    stub_cache["bytes"]["https://stf/a.pdf"] = b"%PDF-1.4 a"
    stub_cache["bytes"]["https://stf/b.pdf"] = b"%PDF-1.4 b body"

    urls = _write_urls(tmp_path, "https://stf/a.pdf", "https://stf/b.pdf")
    result = run_extrair_urls(urls, provedor="tesseract", forcar=False)

    assert result.n_ok == 2
    assert result.n_skipped == 0
    assert result.n_missing_bytes == 0
    assert result.n_fail == 0
    assert len(stub_cache["writes"]) == 2
    written_urls = {w[0] for w in stub_cache["writes"]}
    assert written_urls == {"https://stf/a.pdf", "https://stf/b.pdf"}
    # Every write tags the extractor so future runs can idempotent-skip.
    assert all(w[2] == "tesseract" for w in stub_cache["writes"])


def test_extrair_urls_skips_when_extractor_sidecar_matches(
    tmp_path: Path, stub_cache: dict[str, Any]
) -> None:
    """If the URL's extractor sidecar already says the requested provedor,
    skip — peça was already extracted with this provider. ``--forcar``
    is the explicit override (next test).
    """
    from judex.sweeps.extrair_urls import run_extrair_urls

    stub_cache["bytes"]["https://stf/a.pdf"] = b"%PDF-1.4 a"
    stub_cache["extractor"]["https://stf/a.pdf"] = "tesseract"

    urls = _write_urls(tmp_path, "https://stf/a.pdf")
    result = run_extrair_urls(urls, provedor="tesseract", forcar=False)

    assert result.n_skipped == 1
    assert result.n_ok == 0
    assert stub_cache["extract_calls"] == []  # OCR never invoked
    assert stub_cache["writes"] == []


def test_extrair_urls_forcar_bypasses_sidecar(
    tmp_path: Path, stub_cache: dict[str, Any]
) -> None:
    """``--forcar`` re-extracts even when the sidecar matches — operator
    explicitly wants the work done (e.g. provider quality regression
    suspected, or the sidecar is stale).
    """
    from judex.sweeps.extrair_urls import run_extrair_urls

    stub_cache["bytes"]["https://stf/a.pdf"] = b"%PDF-1.4 a"
    stub_cache["extractor"]["https://stf/a.pdf"] = "tesseract"

    urls = _write_urls(tmp_path, "https://stf/a.pdf")
    result = run_extrair_urls(urls, provedor="tesseract", forcar=True)

    assert result.n_ok == 1
    assert result.n_skipped == 0
    assert len(stub_cache["extract_calls"]) == 1


def test_extrair_urls_different_provedor_does_not_skip(
    tmp_path: Path, stub_cache: dict[str, Any]
) -> None:
    """Sidecar match is *exact* on provedor name — switching providers
    must always re-extract (the whole point of the command)."""
    from judex.sweeps.extrair_urls import run_extrair_urls

    stub_cache["bytes"]["https://stf/a.pdf"] = b"%PDF-1.4 a"
    stub_cache["extractor"]["https://stf/a.pdf"] = "pypdf"

    urls = _write_urls(tmp_path, "https://stf/a.pdf")
    result = run_extrair_urls(urls, provedor="tesseract", forcar=False)

    assert result.n_ok == 1
    assert len(stub_cache["extract_calls"]) == 1
    assert stub_cache["extract_calls"][0]["provider"] == "tesseract"


def test_extrair_urls_missing_bytes_counts_as_missing_not_fail(
    tmp_path: Path, stub_cache: dict[str, Any]
) -> None:
    """A URL with no cached bytes errors gracefully — the command can't
    fetch (that's the unified pipeline's job). Distinct from a failure
    inside the OCR provider so operators can route each separately.
    """
    from judex.sweeps.extrair_urls import run_extrair_urls

    # No bytes for either URL.
    urls = _write_urls(tmp_path, "https://stf/missing.pdf")
    result = run_extrair_urls(urls, provedor="tesseract", forcar=False)

    assert result.n_missing_bytes == 1
    assert result.n_ok == 0
    assert result.n_fail == 0
    assert stub_cache["extract_calls"] == []


def test_extrair_urls_provider_exception_counts_as_fail(
    tmp_path: Path, stub_cache: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exception inside the provider counts toward ``n_fail`` — the
    rest of the URL list keeps processing (don't abort on first error).
    """
    from judex.sweeps import extrair_urls as mod
    from judex.sweeps.extrair_urls import run_extrair_urls

    stub_cache["bytes"]["https://stf/a.pdf"] = b"%PDF-1.4 a"
    stub_cache["bytes"]["https://stf/b.pdf"] = b"%PDF-1.4 b"

    def crashing_extract(pdf_bytes: bytes, *, config: Any) -> ExtractResult:
        if pdf_bytes == b"%PDF-1.4 a":
            raise RuntimeError("provider exploded")
        return ExtractResult(
            text="ok-b", elements=None, pages_processed=1,
            provider=config.provider,
        )

    monkeypatch.setattr(mod, "extract_pdf", crashing_extract)

    urls = _write_urls(tmp_path, "https://stf/a.pdf", "https://stf/b.pdf")
    result = run_extrair_urls(urls, provedor="tesseract", forcar=False)

    assert result.n_ok == 1   # b succeeded
    assert result.n_fail == 1  # a crashed
    # The successful URL was still written despite the prior crash.
    assert any(w[0] == "https://stf/b.pdf" for w in stub_cache["writes"])


def test_extrair_urls_ignores_blanks_and_comments(
    tmp_path: Path, stub_cache: dict[str, Any]
) -> None:
    """The URL file may carry blank lines and ``#``-comments for human
    annotation. Both are silently skipped — only URLs are processed.
    """
    from judex.sweeps.extrair_urls import run_extrair_urls

    stub_cache["bytes"]["https://stf/a.pdf"] = b"%PDF-1.4 a"

    p = tmp_path / "urls.txt"
    p.write_text(
        "# HC 2020 outliers\n"
        "\n"
        "https://stf/a.pdf\n"
        "   \n"  # whitespace-only
        "# more comments\n",
        encoding="utf-8",
    )
    result = run_extrair_urls(p, provedor="tesseract", forcar=False)

    assert result.n_ok == 1
    assert len(stub_cache["extract_calls"]) == 1


def test_extrair_urls_counts_sum_to_total(
    tmp_path: Path, stub_cache: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ok + skipped + missing_bytes + fail`` must equal len(urls).
    No row can be silently dropped from the accounting.
    """
    from judex.sweeps import extrair_urls as mod
    from judex.sweeps.extrair_urls import run_extrair_urls

    # 1 ok, 1 skipped, 1 missing, 1 fail = 4 total.
    stub_cache["bytes"]["https://stf/ok.pdf"] = b"%PDF-1.4 a"
    stub_cache["bytes"]["https://stf/fail.pdf"] = b"%PDF-1.4 b"
    stub_cache["extractor"]["https://stf/skip.pdf"] = "tesseract"
    stub_cache["bytes"]["https://stf/skip.pdf"] = b"x"  # bytes exist but skipped on sidecar

    def crashing_extract(pdf_bytes: bytes, *, config: Any) -> ExtractResult:
        if pdf_bytes == b"%PDF-1.4 b":
            raise RuntimeError("nope")
        return ExtractResult(text="t", elements=None, pages_processed=1,
                             provider=config.provider)
    monkeypatch.setattr(mod, "extract_pdf", crashing_extract)

    urls = _write_urls(
        tmp_path,
        "https://stf/ok.pdf",
        "https://stf/skip.pdf",
        "https://stf/missing.pdf",
        "https://stf/fail.pdf",
    )
    result = run_extrair_urls(urls, provedor="tesseract", forcar=False)

    total = result.n_ok + result.n_skipped + result.n_missing_bytes + result.n_fail
    assert total == 4
    assert result.n_ok == 1
    assert result.n_skipped == 1
    assert result.n_missing_bytes == 1
    assert result.n_fail == 1
