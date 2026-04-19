"""Behavior tests for the Mistral OCR provider (sync + batch helpers)."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from judex.scraping.ocr import OCRConfig, ExtractResult
from judex.scraping.ocr import mistral as m


# ---------------------------------------------------------------------------
# Sync extract
# ---------------------------------------------------------------------------


def test_concat_pages_joins_markdown_with_blank_line():
    pages = [
        {"index": 0, "markdown": "# Page one body"},
        {"index": 1, "markdown": "Page two body"},
    ]
    assert m._concat_pages(pages) == "# Page one body\n\nPage two body"


def test_concat_pages_skips_empty_and_nondict():
    assert m._concat_pages([{"markdown": "  "}, None, "x", {"markdown": "kept"}]) == "kept"


def test_parse_ocr_response_carries_pages_processed():
    payload = {
        "model": "mistral-ocr-2503-completion",
        "pages": [{"index": 0, "markdown": "hi"}],
        "usage_info": {"pages_processed": 7, "doc_size_bytes": None},
    }
    out = m._parse_ocr_response(payload)
    assert out.text == "hi"
    assert out.pages_processed == 7
    assert out.elements == payload["pages"]
    assert out.provider == "mistral"


def test_extract_walks_upload_then_signed_url_then_ocr(monkeypatch):
    """Three HTTP calls in order: upload → signed_url → /v1/ocr.
    Test pins the order and verifies the final ExtractResult shape.
    """
    calls: list[tuple[str, str]] = []

    class _Resp:
        def __init__(self, payload: Any) -> None:
            self._payload = payload
        def raise_for_status(self) -> None: pass
        def json(self) -> Any: return self._payload

    def fake_post(url: str, **kwargs: Any) -> _Resp:
        calls.append(("POST", url))
        if url.endswith("/v1/files"):
            return _Resp({"id": "file-abc"})
        if url.endswith("/v1/ocr"):
            return _Resp({
                "pages": [{"index": 0, "markdown": "Body."}],
                "usage_info": {"pages_processed": 1},
            })
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url: str, **kwargs: Any) -> _Resp:
        calls.append(("GET", url))
        assert "/v1/files/file-abc/url" in url
        return _Resp({"url": "https://signed.example/x"})

    monkeypatch.setattr(m.requests, "post", fake_post)
    monkeypatch.setattr(m.requests, "get", fake_get)

    cfg = OCRConfig(provider="mistral", api_key="k")
    out = m.extract(b"%PDF-1.4 fake", config=cfg)

    assert isinstance(out, ExtractResult)
    assert out.text == "Body."
    assert out.pages_processed == 1
    # ordered: upload, signed_url, ocr
    assert [c[0] for c in calls] == ["POST", "GET", "POST"]
    assert calls[0][1].endswith("/v1/files")
    assert "/v1/files/file-abc/url" in calls[1][1]
    assert calls[2][1].endswith("/v1/ocr")


# ---------------------------------------------------------------------------
# Batch helpers
# ---------------------------------------------------------------------------


def test_build_batch_jsonl_emits_one_line_per_input_with_base64_pdf():
    items = [("HC_135041_doc1", b"%PDF-fake-1"), ("HC_149328_doc1", b"%PDF-fake-2")]
    out = m.build_batch_jsonl(items, model="mistral-ocr-latest")
    lines = out.strip().split("\n")
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["custom_id"] == "HC_135041_doc1"
    body = first["body"]
    assert body["model"] == "mistral-ocr-latest"
    expected_b64 = base64.b64encode(b"%PDF-fake-1").decode("ascii")
    assert body["document"]["document_url"] == f"data:application/pdf;base64,{expected_b64}"


def test_build_batch_jsonl_empty_input_returns_empty_string():
    assert m.build_batch_jsonl([], model="mistral-ocr-latest") == ""


def test_parse_batch_results_maps_custom_id_to_extract_result():
    rows = [
        {
            "custom_id": "doc-A",
            "response": {"body": {
                "pages": [{"index": 0, "markdown": "A1"}],
                "usage_info": {"pages_processed": 1},
            }},
        },
        {
            "custom_id": "doc-B",
            "response": {"body": {
                "pages": [{"index": 0, "markdown": "B1"}, {"index": 1, "markdown": "B2"}],
                "usage_info": {"pages_processed": 2},
            }},
        },
        # Failed / empty response — should be dropped
        {"custom_id": "doc-C", "error": {"message": "bad pdf"}},
    ]
    out = m.parse_batch_results(rows)
    assert set(out.keys()) == {"doc-A", "doc-B"}
    assert out["doc-A"].text == "A1"
    assert out["doc-B"].text == "B1\n\nB2"
    assert out["doc-B"].pages_processed == 2


def test_wait_for_batch_returns_terminal_status(monkeypatch):
    """SUCCESS short-circuits; verifies the polling loop terminates on
    the first terminal status without further sleeps.
    """
    calls = {"n": 0}

    def fake_status(job_id: str, *, config: OCRConfig) -> dict[str, Any]:
        calls["n"] += 1
        return {"status": "RUNNING"} if calls["n"] < 2 else {"status": "SUCCESS", "output_file": "out-1"}

    monkeypatch.setattr(m, "get_batch_status", fake_status)
    monkeypatch.setattr(m.time, "sleep", lambda _s: None)

    cfg = OCRConfig(provider="mistral", api_key="k", batch=True)
    final = m.wait_for_batch("job-1", config=cfg, poll_interval=0.0, max_wait=10.0)
    assert final["status"] == "SUCCESS"
    assert calls["n"] == 2


def test_wait_for_batch_raises_on_timeout(monkeypatch):
    monkeypatch.setattr(m, "get_batch_status", lambda *a, **kw: {"status": "RUNNING"})
    monkeypatch.setattr(m.time, "sleep", lambda _s: None)
    # monotonic returns 0 then 100 — exceeds max_wait=1
    times = iter([0.0, 100.0])
    monkeypatch.setattr(m.time, "monotonic", lambda: next(times))

    cfg = OCRConfig(provider="mistral", api_key="k")
    with pytest.raises(TimeoutError):
        m.wait_for_batch("job-1", config=cfg, poll_interval=0.0, max_wait=1.0)
