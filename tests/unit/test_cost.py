"""Tests for ``judex.utils.cost``.

Covers both surfaces the module unifies:

- Pre-launch forecasting (forecast_baixar_pecas, forecast_varrer_processos,
  forecast_extrair_pecas, render_forecast_table). Behavioral assertions —
  the math reflects the real-run anchors (PDF size, request wall, shard
  speedup), not specific constant names. Re-anchoring within ±10% does
  not require updating the bounds.
- Post-hoc attribution (estimate_proxy_cost, estimate_ocr_cost) and the
  rate getters (proxy_usd_per_gb, ocr_usd_per_1k_pages). Verifies that
  zero-cost paths (direct-IP, pypdf) are handled and that env overrides
  apply at a single source.
"""

from __future__ import annotations

import os

import pytest

from judex.utils import cost


# ----- forecast_baixar_pecas -------------------------------------------------


def test_baixar_returns_two_modes_in_canonical_order() -> None:
    fcs = cost.forecast_baixar_pecas(1000)
    assert len(fcs) == 2
    assert "direct" in fcs[0].mode.lower()
    assert "shard" in fcs[1].mode.lower()


def test_baixar_single_ip_costs_zero_dollars() -> None:
    """Direct IP has no proxy bandwidth bill — that's the whole point of
    the mode. Drift here would mis-budget a recipe."""
    fcs = cost.forecast_baixar_pecas(5_000)
    assert fcs[0].cost_usd == 0.0


def test_baixar_shard_costs_more_than_single_ip() -> None:
    fcs = cost.forecast_baixar_pecas(10_000)
    assert fcs[1].cost_usd > fcs[0].cost_usd


def test_baixar_shard_finishes_faster_than_single_ip() -> None:
    fcs = cost.forecast_baixar_pecas(10_000)
    assert fcs[1].wall_s < fcs[0].wall_s


def test_baixar_bandwidth_matches_anchor() -> None:
    """Bandwidth = n × 0.139 MB. Anchor is the corpus mean of 79,084
    cached `.pdf.gz` (re-measured 2026-04-29). Bounds are generous so
    re-anchoring within ±10% does not require updating the test."""
    fcs = cost.forecast_baixar_pecas(10_000)
    assert fcs[0].bandwidth_gb == fcs[1].bandwidth_gb
    # 10k PDFs × 0.139 MB / 1024 ≈ 1.36 GB
    assert 1.2 < fcs[0].bandwidth_gb < 1.5


def test_baixar_shard_mode_uses_a_proxy_rate_env_override() -> None:
    """Proxy rate is env-configurable via PROXY_PRICE_USD_PER_GB. A
    change must propagate to the forecast."""
    n = 5_000
    base = cost.forecast_baixar_pecas(n)[1].cost_usd

    old = os.environ.get("PROXY_PRICE_USD_PER_GB")
    try:
        os.environ["PROXY_PRICE_USD_PER_GB"] = "100.0"
        bumped = cost.forecast_baixar_pecas(n)[1].cost_usd
    finally:
        if old is None:
            os.environ.pop("PROXY_PRICE_USD_PER_GB", None)
        else:
            os.environ["PROXY_PRICE_USD_PER_GB"] = old

    assert bumped > base * 5  # 100 / 8 = 12.5×; conservative lower bound


def test_baixar_scales_linearly() -> None:
    a = cost.forecast_baixar_pecas(5_000)[0]
    b = cost.forecast_baixar_pecas(10_000)[0]
    assert b.wall_s == pytest.approx(2 * a.wall_s, rel=1e-6)
    assert b.bandwidth_gb == pytest.approx(2 * a.bandwidth_gb, rel=1e-6)


# ----- forecast_varrer_processos --------------------------------------------


def test_varrer_returns_two_modes() -> None:
    fcs = cost.forecast_varrer_processos(2_000)
    assert len(fcs) == 2
    assert fcs[1].wall_s < fcs[0].wall_s


def test_varrer_bandwidth_matches_47kb_per_case_anchor() -> None:
    """Per-case wire bytes ≈ 47 KB blended. 1000 cases → ~46 MB."""
    fcs = cost.forecast_varrer_processos(1_000)
    mb = fcs[0].bandwidth_gb * 1024
    assert 40 < mb < 55


# ----- forecast_extrair_pecas ------------------------------------------------


def test_extract_pypdf_costs_zero() -> None:
    fcs = cost.forecast_extrair_pecas(10_000, provedor="pypdf")
    assert len(fcs) == 1
    assert fcs[0].cost_usd == 0.0


def test_extract_mistral_costs_more_than_zero() -> None:
    fcs = cost.forecast_extrair_pecas(10_000, provedor="mistral")
    assert fcs[0].cost_usd > 0.0


# ----- rendering -------------------------------------------------------------


def test_render_forecast_table_includes_each_mode_and_unit_count() -> None:
    fcs = cost.forecast_baixar_pecas(8252)
    out = cost.render_forecast_table(fcs, n_units=8252, unit_label="PDFs")
    assert "8,252" in out
    assert "PDFs" in out
    for f in fcs:
        assert f.mode in out


def test_format_wall_handles_seconds_minutes_hours_days() -> None:
    assert "s" in cost._format_wall(45)
    assert "m" in cost._format_wall(180)
    assert "h" in cost._format_wall(7_200)
    assert "d" in cost._format_wall(200_000)


# ----- proxy cost (post-hoc) -------------------------------------------------


def test_proxy_cost_zero_when_direct_ip() -> None:
    c = cost.estimate_proxy_cost(
        bytes_downloaded=10_000_000_000, used_proxy=False,
    )
    assert c.dollars == 0.0
    assert "direct-IP" in c.summary_line()


def test_proxy_cost_scales_with_bytes_and_rate() -> None:
    # 1 GB at $3.65/GB = $3.65
    c = cost.estimate_proxy_cost(
        bytes_downloaded=1_000_000_000, used_proxy=True, usd_per_gb=3.65,
    )
    assert c.dollars == pytest.approx(3.65)


def test_proxy_cost_reads_env_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY_PRICE_USD_PER_GB", "5.0")
    assert cost.proxy_usd_per_gb() == pytest.approx(5.0)


def test_proxy_cost_ignores_malformed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY_PRICE_USD_PER_GB", "not-a-number")
    assert cost.proxy_usd_per_gb() > 0.0  # falls back to default


# ----- OCR cost (post-hoc) ---------------------------------------------------


def test_ocr_cost_is_zero_for_pypdf() -> None:
    c = cost.estimate_ocr_cost(provider="pypdf", pages=10_000)
    assert c.dollars == 0.0
    assert "pypdf" in c.summary_line()


def test_ocr_cost_mistral_default() -> None:
    """Default OCR rate for Mistral is the cheapest tier — batch ($1/1k).
    Single source: provider SPEC's cost(1000, OCRConfig(batch=True))."""
    c = cost.estimate_ocr_cost(provider="mistral", pages=1_000)
    assert c.dollars == pytest.approx(1.0)


def test_ocr_cost_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR_PRICE_MISTRAL_USD_PER_1K_PAGES", "2.5")
    assert cost.ocr_usd_per_1k_pages("mistral") == pytest.approx(2.5)
    c = cost.estimate_ocr_cost(provider="mistral", pages=2_000)
    assert c.dollars == pytest.approx(5.0)


# ----- New tests pinning the unification's behavior --------------------------


def test_ocr_rate_reads_from_provider_spec_for_new_providers() -> None:
    """Post-deepening, the OCR rate getter reads from each provider's
    SPEC. This means Gemini / paddle / surya / tesseract — providers
    added in the OCR-bakeoff work that the prior pricing.py did not
    know about — now report a default rate without explicit additions
    to this module."""
    for name in ("gemini", "paddle", "surya", "tesseract"):
        rate = cost.ocr_usd_per_1k_pages(name)
        assert rate > 0.0, f"{name} should have a non-zero default rate"


def test_ocr_rate_uses_batch_tier_when_provider_supports_it() -> None:
    """The default rate is the cheapest tier per the provider's SPEC.
    For batch-supporting providers (mistral, gemini), that is the batch
    rate. Mistral batch = $1/1k; sync = $2/1k; default = batch."""
    assert cost.ocr_usd_per_1k_pages("mistral") == pytest.approx(1.0)
    # Gemini batch = $0.66/1k; sync = $1.32/1k; default = batch.
    assert cost.ocr_usd_per_1k_pages("gemini") == pytest.approx(0.66)
