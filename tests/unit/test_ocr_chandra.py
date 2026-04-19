"""Behavior tests for the Datalab Chandra provider (submit + poll)."""

from __future__ import annotations

from typing import Any

import pytest

from src.scraping.ocr import OCRConfig, ExtractResult
from src.scraping.ocr import chandra as c


def test_parse_complete_payload_picks_markdown_field():
    payload = {
        "status": "complete",
        "markdown": "# HC 135041\n\nDecisão monocrática...",
        "page_count": 12,
    }
    out = c._parse_complete_payload(payload, output_format="markdown")
    assert out.text == "# HC 135041\n\nDecisão monocrática..."
    assert out.pages_processed == 12
    assert out.provider == "chandra"


def test_parse_complete_payload_picks_html_when_requested():
    payload = {"status": "complete", "html": "<h1>X</h1>", "markdown": "# X"}
    out = c._parse_complete_payload(payload, output_format="html")
    assert out.text == "<h1>X</h1>"


def test_parse_complete_payload_extracts_chunk_blocks_as_elements():
    payload = {
        "status": "complete",
        "markdown": "body",
        "chunks": {"blocks": [{"type": "Title", "text": "X"}, {"type": "Para", "text": "Y"}]},
    }
    out = c._parse_complete_payload(payload, output_format="markdown")
    assert out.elements == [{"type": "Title", "text": "X"}, {"type": "Para", "text": "Y"}]


def test_submit_returns_request_check_url(monkeypatch):
    captured: dict[str, Any] = {}

    class _Resp:
        def raise_for_status(self) -> None: pass
        def json(self) -> Any:
            return {
                "request_id": "req-123",
                "request_check_url": "https://www.datalab.to/api/v1/marker/req-123",
                "success": True,
            }

    def fake_post(url: str, **kwargs: Any) -> _Resp:
        captured["url"] = url
        captured["data"] = kwargs.get("data")
        captured["headers"] = kwargs.get("headers")
        return _Resp()

    monkeypatch.setattr(c.requests, "post", fake_post)

    cfg = OCRConfig(provider="chandra", api_key="K", mode="accurate", languages=("por",))
    check_url = c.submit(b"%PDF-1.4", config=cfg)
    assert check_url == "https://www.datalab.to/api/v1/marker/req-123"
    assert captured["url"].endswith("/api/v1/convert")
    assert captured["headers"]["X-API-Key"] == "K"
    assert captured["data"]["mode"] == "accurate"
    assert captured["data"]["langs"] == "por"
    assert captured["data"]["output_format"] == "markdown"


def test_submit_raises_when_no_check_url(monkeypatch):
    class _Resp:
        def raise_for_status(self) -> None: pass
        def json(self) -> Any: return {"error": "boom"}

    monkeypatch.setattr(c.requests, "post", lambda *a, **kw: _Resp())
    cfg = OCRConfig(provider="chandra", api_key="K")
    with pytest.raises(RuntimeError, match="no request_check_url"):
        c.submit(b"%PDF-1.4", config=cfg)


def test_poll_returns_extract_result_when_complete(monkeypatch):
    """Verifies the polling loop transitions through processing → complete
    and produces a normalized ExtractResult on the terminal payload.
    """
    sequence = iter([
        {"status": "processing"},
        {"status": "processing"},
        {"status": "complete", "markdown": "Done.", "page_count": 3},
    ])

    class _Resp:
        def __init__(self, payload: Any) -> None: self._p = payload
        def raise_for_status(self) -> None: pass
        def json(self) -> Any: return self._p

    monkeypatch.setattr(c.requests, "get", lambda url, **kw: _Resp(next(sequence)))
    monkeypatch.setattr(c.time, "sleep", lambda _s: None)

    cfg = OCRConfig(
        provider="chandra", api_key="K",
        poll_interval=0.0, poll_max_wait=10.0,
    )
    out = c.poll("https://check.example/x", config=cfg)
    assert isinstance(out, ExtractResult)
    assert out.text == "Done."
    assert out.pages_processed == 3


def test_poll_raises_on_failed_status(monkeypatch):
    class _Resp:
        def raise_for_status(self) -> None: pass
        def json(self) -> Any: return {"status": "error", "error": "OOM"}

    monkeypatch.setattr(c.requests, "get", lambda *a, **kw: _Resp())
    monkeypatch.setattr(c.time, "sleep", lambda _s: None)
    cfg = OCRConfig(provider="chandra", api_key="K", poll_interval=0.0)
    with pytest.raises(RuntimeError, match="Chandra job failed"):
        c.poll("https://check.example/x", config=cfg)
