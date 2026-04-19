"""run_extract_sweep — end-to-end with mocked OCR dispatcher.

Exercises the sidecar-match truth table from the 2026-04-19 spec:

    sidecar equals --provedor  + not --forcar  → skip, status=cached
    sidecar differs             → run + overwrite
    sidecar missing             → run + write
    no local bytes              → status=no_bytes, skip (no dispatcher call)

Plus the cross-cutting behaviors: --forcar bypasses sidecar-match,
empty text is `status=empty` and not written, elements are cached
when present, RTF bytes bypass the OCR provider entirely, `--retomar`
wins over sidecar-match.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.scraping.ocr import ExtractResult, OCRConfig
from src.sweeps import shared as _shared
from src.sweeps.extract_driver import run_extract_sweep
from src.sweeps.peca_store import PecaStore
from src.sweeps.peca_targets import PecaTarget
from src.utils import peca_cache


@pytest.fixture(autouse=True)
def _isolated_pdf_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.utils.peca_cache.CACHE_ROOT", tmp_path / "peca_cache",
    )


@pytest.fixture(autouse=True)
def _reset_shutdown() -> None:
    _shared._reset_shutdown_for_tests()


def _target(url: str, **kw) -> PecaTarget:
    return PecaTarget(url=url, **kw)


def _kwargs(out_dir: Path, **overrides) -> dict:
    defaults = dict(
        out_dir=out_dir,
        provedor="mistral",
        ocr_config=OCRConfig(provider="mistral", api_key="k"),
        install_signal_handlers=False,
    )
    defaults.update(overrides)
    return defaults


def test_no_local_bytes_records_no_bytes(tmp_path: Path) -> None:
    """Target without cached bytes → status=no_bytes, dispatcher never called."""
    calls: list[str] = []
    def dispatcher(body, cfg):
        calls.append("hit")
        return ExtractResult(text="x", provider="mistral")

    extracted, cached, no_bytes, failed = run_extract_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(tmp_path / "sweep", dispatcher=dispatcher),
    )

    assert calls == []
    assert (extracted, cached, no_bytes, failed) == (0, 0, 1, 0)
    snap = PecaStore(tmp_path / "sweep").snapshot()["https://x.test/a.pdf"]
    assert snap["status"] == "no_bytes"


def test_sidecar_match_skips_dispatcher(tmp_path: Path) -> None:
    """Bytes cached, text cached, sidecar matches --provedor → status=cached."""
    peca_cache.write_bytes("https://x.test/a.pdf", b"%PDF-1.4 fake")
    peca_cache.write("https://x.test/a.pdf", "prior text", extractor="mistral")

    calls: list[str] = []
    def dispatcher(body, cfg):
        calls.append("hit")
        return ExtractResult(text="fresh", provider="mistral")

    extracted, cached, no_bytes, failed = run_extract_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(tmp_path / "sweep", dispatcher=dispatcher),
    )

    assert calls == []
    assert (extracted, cached, no_bytes, failed) == (0, 1, 0, 0)
    assert peca_cache.read("https://x.test/a.pdf") == "prior text"


def test_sidecar_mismatch_runs_dispatcher_and_overwrites(tmp_path: Path) -> None:
    """Bytes cached, text cached by a different provider → re-extract."""
    peca_cache.write_bytes("https://x.test/a.pdf", b"%PDF-1.4 fake")
    peca_cache.write("https://x.test/a.pdf", "old text", extractor="pypdf")

    def dispatcher(body, cfg):
        return ExtractResult(text="fresh mistral text", provider="mistral")

    extracted, cached, no_bytes, failed = run_extract_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(tmp_path / "sweep", dispatcher=dispatcher),
    )

    assert (extracted, cached, no_bytes, failed) == (1, 0, 0, 0)
    assert peca_cache.read("https://x.test/a.pdf") == "fresh mistral text"
    assert peca_cache.read_extractor("https://x.test/a.pdf") == "mistral"


def test_forcar_bypasses_sidecar_match(tmp_path: Path) -> None:
    """--forcar re-runs even when sidecar matches --provedor."""
    peca_cache.write_bytes("https://x.test/a.pdf", b"%PDF-1.4 fake")
    peca_cache.write("https://x.test/a.pdf", "old", extractor="mistral")

    def dispatcher(body, cfg):
        return ExtractResult(text="new", provider="mistral")

    extracted, cached, no_bytes, failed = run_extract_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(tmp_path / "sweep", dispatcher=dispatcher, forcar=True),
    )

    assert (extracted, cached, no_bytes, failed) == (1, 0, 0, 0)
    assert peca_cache.read("https://x.test/a.pdf") == "new"


def test_missing_sidecar_runs_dispatcher(tmp_path: Path) -> None:
    """Bytes cached but no sidecar (pre-v4 entry or fresh download) → extract."""
    peca_cache.write_bytes("https://x.test/a.pdf", b"%PDF-1.4 fake")

    def dispatcher(body, cfg):
        return ExtractResult(text="first pass", provider="mistral")

    extracted, *_ = run_extract_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(tmp_path / "sweep", dispatcher=dispatcher),
    )
    assert extracted == 1
    assert peca_cache.read_extractor("https://x.test/a.pdf") == "mistral"


def test_empty_text_records_empty_and_skips_write(tmp_path: Path) -> None:
    """Dispatcher returns empty text → status=empty, text cache not touched."""
    peca_cache.write_bytes("https://x.test/a.pdf", b"%PDF-1.4 blank")

    def dispatcher(body, cfg):
        return ExtractResult(text="", provider="mistral")

    _, _, _, failed = run_extract_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(tmp_path / "sweep", dispatcher=dispatcher),
    )

    assert failed == 1
    assert peca_cache.read("https://x.test/a.pdf") is None
    snap = PecaStore(tmp_path / "sweep").snapshot()["https://x.test/a.pdf"]
    assert snap["status"] == "empty"


def test_elements_written_when_provider_returns_them(tmp_path: Path) -> None:
    """`.elements.json.gz` is populated alongside the text for providers
    that emit element lists (Unstructured, Chandra chunks, Mistral pages).
    Losing this silently disables downstream structure-aware consumers.
    """
    peca_cache.write_bytes("https://x.test/a.pdf", b"%PDF-1.4 fake")

    elements = [{"type": "Title", "text": "HC"}, {"type": "NarrativeText", "text": "body"}]
    def dispatcher(body, cfg):
        return ExtractResult(text="HC\nbody", elements=elements, provider="mistral")

    run_extract_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(tmp_path / "sweep", dispatcher=dispatcher),
    )
    assert peca_cache.read_elements("https://x.test/a.pdf") == elements


def test_rtf_bytes_bypass_ocr_provider(tmp_path: Path) -> None:
    """RTF-prefix bytes are extracted via striprtf and tagged extractor=rtf,
    regardless of what --provedor was requested. This preserves today's
    behavior where `_default_fetcher` auto-routed RTF.
    """
    peca_cache.write_bytes(
        "https://x.test/a.rtf",
        rb"{\rtf1\ansi Hello RTF World.}",
    )

    calls: list[str] = []
    def dispatcher(body, cfg):
        calls.append("hit")
        return ExtractResult(text="should not be called", provider="mistral")

    extracted, *_ = run_extract_sweep(
        [_target("https://x.test/a.rtf")],
        **_kwargs(tmp_path / "sweep", dispatcher=dispatcher),
    )

    assert calls == []
    assert extracted == 1
    assert peca_cache.read_extractor("https://x.test/a.rtf") == "rtf"
    assert "Hello RTF World" in (peca_cache.read("https://x.test/a.rtf") or "")


def test_unknown_bytes_type_records_unknown_type(tmp_path: Path) -> None:
    """Bytes that are neither PDF nor RTF → status=unknown_type, no dispatch."""
    peca_cache.write_bytes("https://x.test/a.pdf", b"<html>not a pdf</html>")

    def dispatcher(body, cfg):
        return ExtractResult(text="unreachable", provider="mistral")

    _, _, _, failed = run_extract_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(tmp_path / "sweep", dispatcher=dispatcher),
    )
    assert failed == 1
    snap = PecaStore(tmp_path / "sweep").snapshot()["https://x.test/a.pdf"]
    assert snap["status"] == "unknown_type"


def test_retomar_wins_over_sidecar_match(tmp_path: Path) -> None:
    """When state already says status=ok for a URL, --retomar skips it
    regardless of the sidecar. --retomar is evaluated first.
    """
    sweep_dir = tmp_path / "sweep"
    peca_cache.write_bytes("https://x.test/a.pdf", b"%PDF-1.4 fake")

    # First run records status=ok.
    def dispatcher_one(body, cfg):
        return ExtractResult(text="text", provider="mistral")
    run_extract_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(sweep_dir, dispatcher=dispatcher_one),
    )

    # Second run with --retomar and --forcar; both should be skipped.
    calls: list[str] = []
    def dispatcher_two(body, cfg):
        calls.append("hit")
        return ExtractResult(text="new", provider="mistral")
    run_extract_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(sweep_dir, dispatcher=dispatcher_two, resume=True, forcar=True),
    )
    assert calls == []


def test_provider_error_recorded_as_provider_error(tmp_path: Path) -> None:
    """Dispatcher raises → status=provider_error (not http_error — extract
    driver has no HTTP path); goes into pdfs.errors.jsonl retryable."""
    peca_cache.write_bytes("https://x.test/a.pdf", b"%PDF-1.4 fake")

    def dispatcher(body, cfg):
        raise RuntimeError("mistral 503")

    _, _, _, failed = run_extract_sweep(
        [_target("https://x.test/a.pdf")],
        **_kwargs(tmp_path / "sweep", dispatcher=dispatcher),
    )
    assert failed == 1
    snap = PecaStore(tmp_path / "sweep").snapshot()["https://x.test/a.pdf"]
    assert snap["status"] == "provider_error"
    assert snap["error_type"] == "RuntimeError"
    assert "mistral 503" in snap["error"]
