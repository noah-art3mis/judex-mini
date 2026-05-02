"""Behavior tests for the Fly.io Tesseract OCR provider.

Pins the transient-error retry contract: 502/503/504 + ReadTimeout +
ConnectionError get retried (transparent recovery from Fly cold-start
storms and Machine OOM restarts), while 4xx errors fail immediately
(auth / malformed PDF / 404 are permanent).
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
import requests

from judex.scraping.ocr import OCRConfig, ExtractResult
from judex.scraping.ocr import tesseract_fly as tf


class _Resp:
    """Minimal stub of requests.Response for the success path."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _ErrResp:
    """Stub that raises HTTPError with a given status on raise_for_status()."""

    def __init__(self, status: int) -> None:
        self.status_code = status
        # Mock response on the exception so the predicate can read .response.status_code.
        self._exc = requests.HTTPError(f"{status} stub")
        self._exc.response = self  # type: ignore[attr-defined]

    def raise_for_status(self) -> None:
        raise self._exc

    def json(self) -> Any:
        return {}


def _seq_post(responses: list[Any]) -> Iterator[Any]:
    """Return a fake `requests.post` that walks through `responses` and tracks calls."""
    it = iter(responses)
    return it


def _install_fake_post(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    it = iter(responses)

    def fake_post(url: str, **kwargs: Any) -> Any:
        calls.append({"url": url, "kwargs": kwargs})
        nxt = next(it)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt

    monkeypatch.setattr(tf.requests, "post", fake_post)
    # Tenacity sleeps via time.sleep — patch it module-wide so retries are instant in tests.
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda _s: None)
    return calls


def test_extract_retries_on_502_and_succeeds_on_third_attempt(monkeypatch):
    """Two 502s followed by a 200 should retry transparently and return the 200's text."""
    responses = [
        _ErrResp(502),
        _ErrResp(502),
        _Resp({"text": "ok body", "n_pages": 3}),
    ]
    calls = _install_fake_post(monkeypatch, responses)

    cfg = OCRConfig(provider="tesseract_fly", api_url="https://fake.fly.dev/extract")
    out = tf.extract(b"%PDF-fake", config=cfg)

    assert isinstance(out, ExtractResult)
    assert out.text == "ok body"
    assert out.pages_processed == 3
    assert out.provider == "tesseract_fly"
    assert len(calls) == 3, "expected 3 attempts (2 retries + 1 success)"


def test_extract_retries_on_read_timeout_then_succeeds(monkeypatch):
    """ReadTimeout (Machine accepted but OCR took >5 min) should also retry."""
    responses = [
        requests.exceptions.ReadTimeout("simulated tesseract OOM"),
        _Resp({"text": "recovered", "n_pages": 1}),
    ]
    calls = _install_fake_post(monkeypatch, responses)

    cfg = OCRConfig(provider="tesseract_fly", api_url="https://fake.fly.dev/extract")
    out = tf.extract(b"%PDF-fake", config=cfg)

    assert out.text == "recovered"
    assert len(calls) == 2


def test_extract_does_not_retry_on_4xx(monkeypatch):
    """A 400/404 from the server is permanent (bad PDF / wrong URL); fail fast.

    Pins that retry budget isn't wasted on errors that won't change.
    """
    responses = [_ErrResp(400)]
    calls = _install_fake_post(monkeypatch, responses)

    cfg = OCRConfig(provider="tesseract_fly", api_url="https://fake.fly.dev/extract")
    with pytest.raises(requests.HTTPError):
        tf.extract(b"%PDF-fake", config=cfg)

    assert len(calls) == 1, "4xx must not trigger retries"


def test_extract_gives_up_after_max_attempts_of_persistent_5xx(monkeypatch):
    """Persistent 502s eventually surface as HTTPError instead of retrying forever."""
    # 10 attempts worth — should be enough to exceed the configured cap.
    responses: list[Any] = [_ErrResp(502)] * 10
    calls = _install_fake_post(monkeypatch, responses)

    cfg = OCRConfig(provider="tesseract_fly", api_url="https://fake.fly.dev/extract")
    with pytest.raises(requests.HTTPError):
        tf.extract(b"%PDF-fake", config=cfg)

    # Don't pin the exact attempt count (might tune later); pin that it bounded.
    assert 1 < len(calls) <= 6, f"retries should be bounded, got {len(calls)}"
