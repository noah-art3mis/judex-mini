"""Behavior tests for the OCR dispatcher and cost estimator."""

from __future__ import annotations

from typing import Any

import pytest

from judex.scraping.ocr import (
    ExtractResult,
    OCRConfig,
    cheapest_provider,
    estimate_cost,
    extract_pdf,
)
from judex.scraping.ocr import dispatch as d
from judex.scraping.ocr.dispatch import estimate_wall


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


# ----- estimate_wall — sync provider picker for the preview block ----------


def test_estimate_wall_anchors_from_2026_04_19_bakeoff():
    """Per-PDF wall times (sync, not batch) that gate the preview ETA.

    Anchors: pypdf 0.1s, mistral 3.5s, chandra 15s, unstructured 25s.
    The preview multiplies these by `to-extract`; drift here silently
    under/over-estimates every sweep ETA.
    """
    assert estimate_wall("pypdf", 100) == pytest.approx(10.0)
    assert estimate_wall("mistral", 100) == pytest.approx(350.0)
    assert estimate_wall("chandra", 100) == pytest.approx(1500.0)
    assert estimate_wall("unstructured", 100) == pytest.approx(2500.0)


def test_estimate_wall_mistral_batch_is_submit_and_exit():
    """Mistral batch blocks on ~30s submit, SLA report is separate.

    A 1k-PDF batch submit takes the same wall as a 10-PDF batch submit
    (the SLA is the bottleneck, not the submit), so the estimate MUST
    NOT scale with n_pdfs or the preview misleads users into thinking
    batch is slower than sync at scale.
    """
    assert estimate_wall("mistral", 10, batch=True) == pytest.approx(30.0)
    assert estimate_wall("mistral", 10_000, batch=True) == pytest.approx(30.0)


def test_estimate_wall_unknown_provider_raises():
    with pytest.raises(KeyError):
        estimate_wall("bogus", 10)
