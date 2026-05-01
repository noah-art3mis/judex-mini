"""Behavior tests for the OCR dispatcher and cost estimator."""

from __future__ import annotations

import pytest

from judex.scraping.ocr import (
    ExtractResult,
    OCRConfig,
    ProviderSpec,
    cheapest_provider,
    estimate_cost,
    extract_pdf,
)
from judex.scraping.ocr import dispatch as d
from judex.scraping.ocr.dispatch import estimate_wall


def _fake_spec(name: str, text: str) -> ProviderSpec:
    def fake_extract(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
        return ExtractResult(text=text, provider=name)

    return ProviderSpec(
        name=name,
        extract=fake_extract,
        cost=lambda n, c: 0.0,
        wall=lambda n, c: 0.0,
        env_var="",
        supports_batch=False,
    )


def test_extract_pdf_routes_by_provider_name(monkeypatch):
    monkeypatch.setitem(d.REGISTRY, "mistral", _fake_spec("mistral", "m"))
    monkeypatch.setitem(d.REGISTRY, "chandra", _fake_spec("chandra", "c"))

    cfg = OCRConfig(provider="mistral", api_key="k")
    out = extract_pdf(b"%PDF-1.4", config=cfg)
    assert out.text == "m"
    assert out.provider == "mistral"

    out2 = extract_pdf(b"%PDF-1.4", config=OCRConfig(provider="chandra", api_key="k"))
    assert out2.text == "c"
    assert out2.provider == "chandra"


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


def test_cheapest_provider_picks_lowest_listed_rate():
    """`cheapest_provider` scans every registered provider's `cost(1, ...)`
    and returns the lowest. As of 2026-05 the cheapest is `tesseract_local`
    at $0 (local CPU, no API cost). Among API-priced/Modal-hosted providers
    the next-cheapest is paddle ($0.08/1k), then tesseract Modal-hosted
    ($0.14/1k post-bakeoff anchor).

    If a registered provider's listed rate changes, this assertion needs
    an explicit update — not silent drift. Quality / latency / local-vs-cloud
    status are NOT considered here; that's documented in the cheapest_provider
    docstring."""
    assert cheapest_provider(batch_ok=True) == "tesseract_local"


def test_cheapest_provider_responds_to_batch_flag():
    """When batch is disallowed, providers that only have batch pricing
    (mistral, gemini) fall back to their sync rate. The cheapest still
    needs to be a registered provider name. `tesseract_local` at $0 wins
    regardless of batch flag, since it never charges per page."""
    out = cheapest_provider(batch_ok=False)
    assert out in d.REGISTRY  # any registered name is structurally valid
    assert out == "tesseract_local"


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
    # Same error class as estimate_cost — unified by the deepening so
    # callers don't have to remember which one raises which exception.
    with pytest.raises(ValueError, match="unknown OCR provider"):
        estimate_wall("bogus", 10)
