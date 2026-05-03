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
