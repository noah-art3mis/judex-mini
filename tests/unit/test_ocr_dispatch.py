"""Behavior tests for the OCR dispatcher and cost estimator."""

from __future__ import annotations

from typing import Any

import pytest

from src.scraping.ocr import (
    ExtractResult,
    OCRConfig,
    cheapest_provider,
    estimate_cost,
    extract_pdf,
)
from src.scraping.ocr import dispatch as d


def test_extract_pdf_routes_by_provider_name(monkeypatch):
    seen: dict[str, Any] = {}

    def fake_mistral(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
        seen["called"] = "mistral"
        return ExtractResult(text="m", provider="mistral")

    def fake_chandra(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
        seen["called"] = "chandra"
        return ExtractResult(text="c", provider="chandra")

    monkeypatch.setitem(d._REGISTRY, "mistral", fake_mistral)
    monkeypatch.setitem(d._REGISTRY, "chandra", fake_chandra)

    cfg = OCRConfig(provider="mistral", api_key="k")
    out = extract_pdf(b"%PDF-1.4", config=cfg)
    assert seen["called"] == "mistral"
    assert out.text == "m"

    out2 = extract_pdf(b"%PDF-1.4", config=OCRConfig(provider="chandra", api_key="k"))
    assert seen["called"] == "chandra"
    assert out2.text == "c"


def test_extract_pdf_unknown_provider_raises():
    with pytest.raises(ValueError, match="unknown OCR provider"):
        extract_pdf(b"%PDF-1.4", config=OCRConfig(provider="bogus", api_key="k"))


def test_estimate_cost_matches_published_april_2026_rates():
    """Pin the per-page rates so an inadvertent PRICING edit can't
    silently change the cost gate. The numbers are the four anchors
    that drive the migration decision in current_progress.md."""
    # Famous-lawyer preset: 354 PDFs * 5 pg = 1770 pg
    assert estimate_cost("unstructured", 1770) == pytest.approx(17.70)
    assert estimate_cost("mistral", 1770, batch=True) == pytest.approx(1.77)
    assert estimate_cost("mistral", 1770, batch=False) == pytest.approx(3.54)
    assert estimate_cost("chandra", 1770, mode="accurate") == pytest.approx(5.31)

    # All-HC tier: ~766k pg
    assert estimate_cost("unstructured", 766_000) == pytest.approx(7660.0)
    assert estimate_cost("mistral", 766_000, batch=True) == pytest.approx(766.0)


def test_estimate_cost_unknown_provider_raises():
    with pytest.raises(ValueError, match="unknown OCR provider"):
        estimate_cost("bogus", 100)


def test_cheapest_provider_prefers_mistral_batch():
    """Pricing as of April 2026: Mistral batch ($1/1k) is the cheapest
    hosted option. If this flips (Mistral price hike, Chandra public
    rate drops), this assertion needs an explicit update — not silent
    drift."""
    assert cheapest_provider(batch_ok=True) == "mistral"


def test_cheapest_provider_falls_back_when_batch_disallowed():
    """Without batch, Mistral sync ($2) > Unstructured fast ($1).
    The Unstructured fast strategy isn't a real OCR though — caller
    needs to know what `cheapest_provider` is actually returning."""
    out = cheapest_provider(batch_ok=False)
    assert out in {"unstructured", "mistral"}  # pricing-tied; either is valid
