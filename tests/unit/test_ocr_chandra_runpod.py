"""Behavior tests for the RunPod-hosted Chandra provider.

The provider talks to RunPod's async ``/run`` API (the OpenAI proxy
on RunPod's worker-vllm template returned 500 on the endpoint we
deployed against; sticking with the canonical async path). Tests
mock both the PDF rasterisation (so the suite doesn't need
poppler-utils on CI) and the HTTP layer.
"""

from __future__ import annotations

from typing import Any

import pytest

from judex.scraping.ocr import ExtractResult, OCRConfig
from judex.scraping.ocr import chandra_runpod as cr


# ----- endpoint base URL resolution ----------------------------------------


def test_endpoint_base_uses_explicit_api_url_when_set():
    cfg = OCRConfig(
        provider="chandra_runpod", api_key="K",
        api_url="https://x/v2/abc",
    )
    assert cr._endpoint_base(cfg) == "https://x/v2/abc"


def test_endpoint_base_constructs_runpod_path_from_env_var(monkeypatch):
    """The constructed base URL must end in ``/v2/{ep}`` (no ``/openai``
    suffix) — that's where ``/run`` and ``/status`` live."""
    monkeypatch.setenv("RUNPOD_CHANDRA_ENDPOINT_ID", "ep123")
    cfg = OCRConfig(provider="chandra_runpod", api_key="K")
    assert cr._endpoint_base(cfg) == "https://api.runpod.ai/v2/ep123"


def test_endpoint_base_raises_when_unset(monkeypatch):
    monkeypatch.delenv("RUNPOD_CHANDRA_ENDPOINT_ID", raising=False)
    cfg = OCRConfig(provider="chandra_runpod", api_key="K")
    with pytest.raises(RuntimeError, match="RUNPOD_CHANDRA_ENDPOINT_ID"):
        cr._endpoint_base(cfg)


# ----- submit ---------------------------------------------------------------


def test_submit_posts_multimodal_message_and_returns_job_id(monkeypatch):
    """Submit posts a vLLM-shaped multimodal message body to /run.
    The body wraps OpenAI-style ``messages`` under ``input`` (RunPod
    worker-vllm convention), with one ``image_url`` block and one
    ``text`` block. Drift on this shape is the silent kind — the
    request 200s but vLLM emits empty completions."""
    captured: dict[str, Any] = {}

    class _Resp:
        def raise_for_status(self) -> None: pass
        def json(self) -> Any: return {"id": "job-xyz", "status": "IN_QUEUE"}

    def fake_post(url: str, **kwargs: Any) -> _Resp:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        return _Resp()

    monkeypatch.setattr(cr.requests, "post", fake_post)
    cfg = OCRConfig(
        provider="chandra_runpod", api_key="K",
        api_url="https://x/v2/abc",
    )
    job_id = cr.submit(b"\x89PNG fake", config=cfg, base=cfg.api_url)

    assert job_id == "job-xyz"
    assert captured["url"] == "https://x/v2/abc/run"
    assert captured["headers"]["Authorization"] == "Bearer K"

    body = captured["json"]
    inp = body["input"]
    content = inp["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1]["type"] == "text"
    assert "Markdown" in content[1]["text"]
    assert inp["max_tokens"] == 4096
    assert inp["temperature"] == 0.0


def test_submit_raises_when_no_job_id(monkeypatch):
    class _Resp:
        def raise_for_status(self) -> None: pass
        def json(self) -> Any: return {"error": "nope"}

    monkeypatch.setattr(cr.requests, "post", lambda *a, **kw: _Resp())
    cfg = OCRConfig(provider="chandra_runpod", api_key="K", api_url="https://x/v2/abc")
    with pytest.raises(RuntimeError, match="no job id"):
        cr.submit(b"\x89PNG", config=cfg, base="https://x/v2/abc")


# ----- poll -----------------------------------------------------------------


def test_poll_returns_text_on_completed(monkeypatch):
    """Verifies the polling loop transitions through IN_QUEUE →
    IN_PROGRESS → COMPLETED and extracts assistant text from RunPod's
    output envelope (a list of chunks, each with choices[].tokens[]).
    """
    sequence = iter([
        {"id": "j", "status": "IN_QUEUE"},
        {"id": "j", "status": "IN_PROGRESS"},
        {"id": "j", "status": "COMPLETED",
         "output": [{"choices": [{"tokens": ["Hel", "lo ", "world."]}]}]},
    ])

    class _Resp:
        def __init__(self, payload: Any) -> None: self._p = payload
        def raise_for_status(self) -> None: pass
        def json(self) -> Any: return self._p

    monkeypatch.setattr(cr.requests, "get", lambda url, **kw: _Resp(next(sequence)))
    monkeypatch.setattr(cr.time, "sleep", lambda _s: None)

    cfg = OCRConfig(
        provider="chandra_runpod", api_key="K", api_url="https://x/v2/abc",
        poll_interval=0.0, poll_max_wait=10.0,
    )
    text = cr.poll("j", config=cfg, base="https://x/v2/abc")
    assert text == "Hello world."


@pytest.mark.parametrize("terminal", ["FAILED", "CANCELLED", "TIMED_OUT"])
def test_poll_raises_on_terminal_failure(monkeypatch, terminal):
    class _Resp:
        def raise_for_status(self) -> None: pass
        def json(self) -> Any: return {"id": "j", "status": terminal,
                                        "error": "boom"}

    monkeypatch.setattr(cr.requests, "get", lambda *a, **kw: _Resp())
    monkeypatch.setattr(cr.time, "sleep", lambda _s: None)
    cfg = OCRConfig(
        provider="chandra_runpod", api_key="K",
        api_url="https://x/v2/abc", poll_interval=0.0,
    )
    with pytest.raises(RuntimeError, match=f"ended {terminal}"):
        cr.poll("j", config=cfg, base="https://x/v2/abc")


# ----- _extract_text -------------------------------------------------------


def test_extract_text_flattens_multi_chunk_multi_choice_output():
    """Real long-generation responses produce ``output`` as a list of
    streaming chunks, each with its own ``choices[].tokens[]``. The
    extractor flattens both layers and joins token strings into one
    continuous text. Pinning this matters because the pong test from
    the deployed endpoint returned 1 chunk × 1 token, which is the
    *easiest* case — a multi-chunk response is when the flattening
    logic actually has to do work."""
    output = [
        {"choices": [{"tokens": ["pong"]}]},
        {"choices": [{"tokens": ["second", " ", "chunk"]}]},
    ]
    assert cr._extract_text(output) == "pongsecond chunk"


def test_extract_text_robust_to_missing_fields():
    """Output array might contain garbage / partial entries — should
    never crash, just skip non-conforming chunks."""
    output = [
        {"no_choices": True},
        None,
        {"choices": [{"no_tokens": True}]},
        {"choices": [{"tokens": ["valid"]}]},
    ]
    assert cr._extract_text(output) == "valid"


def test_extract_text_empty_on_non_list_output():
    assert cr._extract_text(None) == ""
    assert cr._extract_text({}) == ""
    assert cr._extract_text("string") == ""


# ----- extract: page aggregation -------------------------------------------


def test_extract_iterates_pages_and_joins_with_blank_line(monkeypatch):
    """Multi-page PDFs submit one /run job per page and concatenate
    the resulting texts with the same ``\\n\\n`` separator other OCR
    providers use."""
    monkeypatch.setattr(cr, "_pdf_to_page_pngs",
                        lambda b, dpi=200: [b"p1", b"p2", b"p3"])

    submitted: list[bytes] = []

    def fake_submit(page, *, config, base):
        submitted.append(page)
        return f"job-{len(submitted)}"

    poll_results = iter(["First page.", "Second page.", "Third page."])

    def fake_poll(job_id, *, config, base):
        return next(poll_results)

    monkeypatch.setattr(cr, "submit", fake_submit)
    monkeypatch.setattr(cr, "poll", fake_poll)

    cfg = OCRConfig(
        provider="chandra_runpod", api_key="K",
        api_url="https://x/v2/abc",
    )
    result = cr.extract(b"%PDF-1.4 fake", config=cfg)

    assert isinstance(result, ExtractResult)
    assert result.provider == "chandra_runpod"
    assert result.pages_processed == 3
    assert result.text == "First page.\n\nSecond page.\n\nThird page."
    assert submitted == [b"p1", b"p2", b"p3"]


def test_extract_drops_blank_pages_from_concatenation(monkeypatch):
    """A blank page produces an empty completion; aggregation must
    not insert ``\\n\\n\\n\\n`` artifacts where the blank fell."""
    monkeypatch.setattr(cr, "_pdf_to_page_pngs",
                        lambda b, dpi=200: [b"p1", b"p2", b"p3"])
    monkeypatch.setattr(cr, "submit", lambda p, **kw: "job")
    poll_results = iter(["First.", "", "Third."])
    monkeypatch.setattr(cr, "poll", lambda j, **kw: next(poll_results))

    cfg = OCRConfig(
        provider="chandra_runpod", api_key="K",
        api_url="https://x/v2/abc",
    )
    result = cr.extract(b"%PDF-1.4 fake", config=cfg)
    assert result.text == "First.\n\nThird."
    assert result.pages_processed == 3  # blank still counted


def test_pdf_to_page_pngs_raises_clean_message_when_pdf2image_missing(monkeypatch):
    """When poppler-utils / pdf2image isn't installed, the user should
    see an actionable RuntimeError naming the extras group, not a raw
    ImportError."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pdf2image":
            raise ImportError("No module named 'pdf2image'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="ocr-local"):
        cr._pdf_to_page_pngs(b"%PDF")


# ----- registry integration -------------------------------------------------


def test_provider_registered_in_dispatch():
    """The provider must be discoverable through the dispatch registry
    so ``extrair-pecas --provedor chandra_runpod`` works without
    additional wiring."""
    from judex.scraping.ocr import dispatch as d
    assert "chandra_runpod" in d.REGISTRY
    assert d.REGISTRY["chandra_runpod"].env_var == "RUNPOD_API_KEY"


# ----- cost anchor ----------------------------------------------------------


def test_cost_anchored_to_4090_serverless_rate():
    """Per-page rate anchor: ~$0.31/1k pages (= $0.00031 active sec ×
    ~1 page/sec on RTX 4090). Drift here would silently mis-budget
    the next bulk re-extract."""
    cfg = OCRConfig(provider="chandra_runpod", api_key="K")
    assert cr.cost(1000, cfg) == pytest.approx(0.31)
    # 12,930 ACÓRDÃOs × 30 pages avg = 387,900 pages → ~$120
    assert cr.cost(387_900, cfg) == pytest.approx(120.25, rel=1e-3)


def test_wall_unanchored_until_bakeoff():
    cfg = OCRConfig(provider="chandra_runpod", api_key="K")
    with pytest.raises(NotImplementedError):
        cr.wall(100, cfg)
