"""Real-handler tests for the unified pipeline.

Most pipeline tests use mocked handlers (cheap, no STF / no OCR). The
ones in this file pin the *real* ``make_handlers`` factory's per-task
behaviour where it intersects with content-type semantics — i.e. the
parts that are not interchangeable with a synthetic stub.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from judex.pipeline.handlers import make_handlers
from judex.pipeline.models import Task
from judex.pipeline.state import PipelineState


_MINIMAL_RTF = b"{\\rtf1\\ansi hello world}"


def test_handle_extract_text_uses_rtf_path_for_rtf_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RTF bytes (``{\\rtf...``) must NOT be sent to the PDF provider —
    they're structured text, parseable instantly with striprtf. The
    legacy ``extract_driver`` magic-byte-sniffs and routes RTF through
    ``extract_rtf_text`` (extractor tag = "rtf"); the unified pipeline
    must do the same. Otherwise pypdf chokes on ``b'{\\rtf'`` and the
    URL ends up as ``provider_error``, even though the data is fine.

    The 100-case Layer-2 receipts (HC 250000-250099) showed this gap:
    32/187 text URLs failed as ``provider_error`` — every one an RTF
    surface from DJe.
    """
    state = PipelineState.load(tmp_path / "s.json")

    captured_writes: dict[str, tuple[str, str | None]] = {}

    def fake_read_bytes(url: str) -> bytes:
        return _MINIMAL_RTF

    def fake_write(url: str, text: str, *, extractor: str | None = None) -> None:
        captured_writes[url] = (text, extractor)

    from judex.utils import peca_cache

    monkeypatch.setattr(peca_cache, "read_bytes", fake_read_bytes)
    monkeypatch.setattr(peca_cache, "write", fake_write)

    handlers = make_handlers(state, provedor="pypdf")
    task = Task(
        kind="extract_text",
        pool="ocr",
        case_key=("HC", 250000),
        payload={"url": "https://portal.stf.jus.br/processos/downloadTexto.asp?id=1&ext=RTF"},
    )

    successors = handlers["extract_text"](task)

    assert successors == []
    # Status is ok and the extractor tag is "rtf" — NOT the configured
    # provedor ("pypdf"). Pinning the tag matters because downstream
    # cache hygiene (sidecar file ``<sha1>.extractor``) and
    # ``--forcar`` semantics rely on the provider label being honest
    # about how the text was produced.
    assert state.text_status(task.case_key, url=task.payload["url"]) == "ok"
    assert state.is_text_complete(
        task.case_key, url=task.payload["url"], required_extractor="rtf"
    )
    # The text actually written to cache is the striprtf output.
    assert task.payload["url"] in captured_writes
    written_text, written_extractor = captured_writes[task.payload["url"]]
    assert written_extractor == "rtf"
    assert "hello world" in written_text.lower()


def test_handle_extract_text_records_no_bytes_for_empty_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defensive: a cache miss (empty body) is recorded as ``no_bytes``
    with no provider invocation, so resume can pick it up after a
    bytes-side retry.
    """
    state = PipelineState.load(tmp_path / "s.json")

    from judex.utils import peca_cache

    monkeypatch.setattr(peca_cache, "read_bytes", lambda url: b"")

    handlers = make_handlers(state, provedor="pypdf")
    task = Task(
        kind="extract_text",
        pool="ocr",
        case_key=("HC", 1),
        payload={"url": "https://example/cache-miss.pdf"},
    )

    successors = handlers["extract_text"](task)

    assert successors == []
    assert state.text_status(task.case_key, url=task.payload["url"]) == "no_bytes"


# ---------------------------------------------------------------------------
# `--provedor auto` per-target router (parity with extrair-pecas).
# ---------------------------------------------------------------------------


def _stub_extract_pdf_capture(monkeypatch: pytest.MonkeyPatch) -> list:
    """Patch ocr_dispatch.extract_pdf to capture each OCRConfig it
    receives, returning a stub success result so the handler proceeds
    to the state-write path."""
    captured: list = []

    def fake_extract_pdf(pdf_bytes: bytes, config) -> object:
        captured.append(config)
        from judex.scraping.ocr import ExtractResult
        return ExtractResult(
            text="stub text", elements=None,
            pages_processed=1, provider=config.provider,
        )

    monkeypatch.setattr(
        "judex.scraping.ocr.dispatch.extract_pdf", fake_extract_pdf
    )
    return captured


def test_handle_extract_text_auto_routes_acordao_to_tesseract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--provedor auto`` + a doc_type of INTEIRO TEOR DO ACÓRDÃO must
    dispatch to the tesseract sub-provider (per legacy ``pick_provider``).
    The default sub-provider is local ``tesseract``; ``JUDEX_AUTO_TESSERACT_PROVIDER``
    overrides it (e.g. ``tesseract_fly`` for billed scale-out)."""
    state = PipelineState.load(tmp_path / "s.json")
    monkeypatch.delenv("JUDEX_AUTO_TESSERACT_PROVIDER", raising=False)

    from judex.utils import peca_cache
    monkeypatch.setattr(peca_cache, "read_bytes", lambda url: b"%PDF-1.4 dummy")
    monkeypatch.setattr(peca_cache, "write", lambda url, text, *, extractor=None: None)
    monkeypatch.setattr(peca_cache, "write_elements", lambda url, els: None)

    captured = _stub_extract_pdf_capture(monkeypatch)

    handlers = make_handlers(state, provedor="auto")
    task = Task(
        kind="extract_text", pool="ocr", case_key=("HC", 1),
        payload={"url": "https://x/acordao.pdf",
                 "doc_type": "INTEIRO TEOR DO ACÓRDÃO"},
    )
    handlers["extract_text"](task)

    assert len(captured) == 1
    assert captured[0].provider == "tesseract"
    # Sidecar is tagged with the EFFECTIVE provider, not "auto".
    assert state.is_text_complete(
        task.case_key, url=task.payload["url"], required_extractor="tesseract"
    )


def test_handle_extract_text_auto_routes_non_acordao_to_pypdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--provedor auto`` + a non-ACÓRDÃO doc_type uses pypdf — the
    cheap path. This is the bulk of HC peças (decisão monocrática,
    petições, certidões)."""
    state = PipelineState.load(tmp_path / "s.json")

    from judex.utils import peca_cache
    monkeypatch.setattr(peca_cache, "read_bytes", lambda url: b"%PDF-1.4 dummy")
    monkeypatch.setattr(peca_cache, "write", lambda url, text, *, extractor=None: None)
    monkeypatch.setattr(peca_cache, "write_elements", lambda url, els: None)

    captured = _stub_extract_pdf_capture(monkeypatch)

    handlers = make_handlers(state, provedor="auto")
    task = Task(
        kind="extract_text", pool="ocr", case_key=("HC", 1),
        payload={"url": "https://x/decisao.pdf",
                 "doc_type": "DECISÃO MONOCRÁTICA"},
    )
    handlers["extract_text"](task)

    assert len(captured) == 1
    assert captured[0].provider == "pypdf"
    assert state.is_text_complete(
        task.case_key, url=task.payload["url"], required_extractor="pypdf"
    )


def test_handle_extract_text_auto_honors_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``JUDEX_AUTO_TESSERACT_PROVIDER`` redirects the auto-router's
    ACÓRDÃO branch to a different tesseract venue (Fly / Modal). This
    is how legacy ``coletar`` runs Fly OCR under auto mode without a
    code change."""
    state = PipelineState.load(tmp_path / "s.json")
    monkeypatch.setenv("JUDEX_AUTO_TESSERACT_PROVIDER", "tesseract_fly")

    from judex.utils import peca_cache
    monkeypatch.setattr(peca_cache, "read_bytes", lambda url: b"%PDF-1.4 dummy")
    monkeypatch.setattr(peca_cache, "write", lambda url, text, *, extractor=None: None)
    monkeypatch.setattr(peca_cache, "write_elements", lambda url, els: None)

    captured = _stub_extract_pdf_capture(monkeypatch)

    handlers = make_handlers(state, provedor="auto")
    task = Task(
        kind="extract_text", pool="ocr", case_key=("HC", 1),
        payload={"url": "https://x/acordao.pdf",
                 "doc_type": "INTEIRO TEOR DO ACÓRDÃO"},
    )
    handlers["extract_text"](task)

    assert captured[0].provider == "tesseract_fly"


def test_handle_fetch_meta_skips_scrape_when_case_json_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Storage-level idempotence on the portal Pool: when the case JSON
    is already on disk (e.g. from a --retomar against state stale at
    the 5 s snapshot interval, or from a prior legacy varrer-processos
    sweep over the same range), ``handle_fetch_meta`` MUST read the
    cached JSON and record meta=ok without calling STF.

    Without this guard, hard-kill resume re-hits ``portal.stf.jus.br``
    for every case whose JSON was written but whose state outcome
    wasn't snapshotted before SIGKILL — see
    ``docs/adr/0005-unified-pipeline.md`` § Open issues. The portal
    Pool is the WAF-hottest, so suppressing the redundant call
    matters disproportionately.

    Symmetric with the cache-hit guards in ``handle_fetch_bytes``
    (``peca_cache.has_bytes``) and ``handle_extract_text``
    (``peca_cache.has_text``).
    """
    import json as _json

    state = PipelineState.load(tmp_path / "s.json")

    # Pre-write a minimal case JSON at the path the handler computes
    # internally. ``items_root`` is the source_dir kwarg; under that we
    # land at ``<classe>/judex-mini_<classe>_<n>-<n>.json``.
    classe, processo = "HC", 250000
    out_dir = tmp_path / classe
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"judex-mini_{classe}_{processo}-{processo}.json"
    # Minimal item with no peça surfaces — keeps the test focused on
    # the idempotence skip rather than on follow-up task emission.
    out_path.write_text(
        _json.dumps({"classe": classe, "processo_id": processo, "andamentos": []}),
        encoding="utf-8",
    )

    # Tripwire: if the handler reaches the network path, the test fails
    # loudly rather than silently passing because of an unexpected mock.
    def _scraper_must_not_be_called(*args: object, **kwargs: object) -> object:
        raise AssertionError(
            "scrape_processo_http called despite cached case JSON on disk"
        )

    monkeypatch.setattr(
        "judex.scraping.scraper.scrape_processo_http",
        _scraper_must_not_be_called,
    )

    handlers = make_handlers(state, provedor="pypdf", source_dir=tmp_path)
    task = Task(kind="fetch_meta", pool="portal", case_key=(classe, processo))

    successors = handlers["fetch_meta"](task)

    # Empty successors because the cached item carries zero peça URLs;
    # the load-bearing assertion is the next one (state recorded ok
    # without the scraper running).
    assert successors == []
    assert state.meta_status((classe, processo)) == "ok"


def test_handle_fetch_meta_falls_through_to_scrape_on_malformed_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defensive: if the on-disk case JSON exists but is malformed
    (truncated write from a prior crash, manual edit gone wrong), the
    handler must fall through to a fresh scrape rather than silently
    emit zero successors against a half-written JSON. Empty/zero
    successors on a real case would silently break warehouse rebuild
    and downstream analysis with no error trail.
    """
    state = PipelineState.load(tmp_path / "s.json")

    classe, processo = "HC", 250001
    out_dir = tmp_path / classe
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"judex-mini_{classe}_{processo}-{processo}.json").write_text(
        "{ this is not valid json", encoding="utf-8",
    )

    scrape_called: list[tuple[str, int]] = []

    def _fake_scrape(classe_arg: str, processo_arg: int, **kwargs: object) -> dict:
        scrape_called.append((classe_arg, processo_arg))
        return {"classe": classe_arg, "processo_id": processo_arg, "andamentos": []}

    monkeypatch.setattr(
        "judex.scraping.scraper.scrape_processo_http", _fake_scrape
    )

    handlers = make_handlers(state, provedor="pypdf", source_dir=tmp_path)
    task = Task(kind="fetch_meta", pool="portal", case_key=(classe, processo))
    handlers["fetch_meta"](task)

    assert scrape_called == [(classe, processo)]
    assert state.meta_status((classe, processo)) == "ok"


def test_handle_extract_text_auto_falls_back_to_pypdf_when_doc_type_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resume without payload-side doc_type (e.g. legacy state file
    pre-doc-type-tracking) must NOT crash. Router defaults to pypdf
    on a missing doc_type — the cheap fallback. ACÓRDÃO branch only
    triggers on an explicit positive match."""
    state = PipelineState.load(tmp_path / "s.json")

    from judex.utils import peca_cache
    monkeypatch.setattr(peca_cache, "read_bytes", lambda url: b"%PDF-1.4 dummy")
    monkeypatch.setattr(peca_cache, "write", lambda url, text, *, extractor=None: None)
    monkeypatch.setattr(peca_cache, "write_elements", lambda url, els: None)

    captured = _stub_extract_pdf_capture(monkeypatch)

    handlers = make_handlers(state, provedor="auto")
    task = Task(
        kind="extract_text", pool="ocr", case_key=("HC", 1),
        payload={"url": "https://x/no-doctype.pdf"},  # no doc_type
    )
    handlers["extract_text"](task)

    assert captured[0].provider == "pypdf"
