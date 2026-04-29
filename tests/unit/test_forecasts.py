"""Tests for `judex.utils.forecasts`.

Behavioral tests — they assert the forecasting math reflects the
real-run anchors (PDF size, request wall, shard speedup), not that
the constants have specific names. If the anchors are re-measured
and updated, only the bounds in these tests need adjusting.
"""

from __future__ import annotations

import os

import pytest

from judex.utils import forecasts


def test_baixar_returns_two_modes_in_canonical_order() -> None:
    fcs = forecasts.forecast_baixar_pecas(1000)
    assert len(fcs) == 2
    assert "direct" in fcs[0].mode.lower()
    assert "shard" in fcs[1].mode.lower()


def test_baixar_single_ip_costs_zero_dollars() -> None:
    """Direct IP has no proxy bandwidth bill — that's the whole
    point of the mode. Drift here would mis-budget a recipe."""
    fcs = forecasts.forecast_baixar_pecas(5_000)
    assert fcs[0].cost_usd == 0.0


def test_baixar_shard_costs_more_than_single_ip() -> None:
    """16-shard mode pays for proxy bandwidth; single-IP doesn't.
    Costs cannot be equal."""
    fcs = forecasts.forecast_baixar_pecas(10_000)
    assert fcs[1].cost_usd > fcs[0].cost_usd


def test_baixar_shard_finishes_faster_than_single_ip() -> None:
    """16-shard mode trades money for time; wall must be lower."""
    fcs = forecasts.forecast_baixar_pecas(10_000)
    assert fcs[1].wall_s < fcs[0].wall_s


def test_baixar_bandwidth_matches_anchor() -> None:
    """Bandwidth = n × 0.139 MB. Anchor is the corpus mean of
    79,084 cached `.pdf.gz` files (re-measured 2026-04-29). The
    test uses generous bounds so re-anchoring within ±10% doesn't
    require updating it."""
    fcs = forecasts.forecast_baixar_pecas(10_000)
    # Single-IP and shard modes must report the same bandwidth.
    assert fcs[0].bandwidth_gb == fcs[1].bandwidth_gb
    # 10k PDFs × 0.139 MB / 1024 ≈ 1.36 GB
    assert 1.2 < fcs[0].bandwidth_gb < 1.5


def test_baixar_shard_mode_uses_a_proxy_rate_env_override() -> None:
    """The proxy rate is env-configurable via PROXY_PRICE_USD_PER_GB.
    A change in the rate must propagate to the forecast."""
    n = 5_000
    base = forecasts.forecast_baixar_pecas(n)[1].cost_usd

    old = os.environ.get("PROXY_PRICE_USD_PER_GB")
    try:
        os.environ["PROXY_PRICE_USD_PER_GB"] = "100.0"
        bumped = forecasts.forecast_baixar_pecas(n)[1].cost_usd
    finally:
        if old is None:
            os.environ.pop("PROXY_PRICE_USD_PER_GB", None)
        else:
            os.environ["PROXY_PRICE_USD_PER_GB"] = old

    assert bumped > base * 5  # 100 / 8 = 12.5×; conservative lower bound


def test_varrer_returns_two_modes() -> None:
    fcs = forecasts.forecast_varrer_processos(2_000)
    assert len(fcs) == 2
    assert fcs[1].wall_s < fcs[0].wall_s


def test_varrer_bandwidth_matches_47kb_per_case_anchor() -> None:
    """Per-case wire bytes ≈ 47 KB blended. 1000 cases → ~46 MB."""
    fcs = forecasts.forecast_varrer_processos(1_000)
    mb = fcs[0].bandwidth_gb * 1024
    assert 40 < mb < 55


def test_extract_pypdf_costs_zero() -> None:
    """pypdf is local; no API bill."""
    fcs = forecasts.forecast_extrair_pecas(10_000, provedor="pypdf")
    assert len(fcs) == 1
    assert fcs[0].cost_usd == 0.0


def test_extract_mistral_costs_more_than_zero() -> None:
    fcs = forecasts.forecast_extrair_pecas(10_000, provedor="mistral")
    assert fcs[0].cost_usd > 0.0


def test_render_forecast_table_includes_each_mode_and_unit_count() -> None:
    fcs = forecasts.forecast_baixar_pecas(8252)
    out = forecasts.render_forecast_table(
        fcs, n_units=8252, unit_label="PDFs"
    )
    assert "8,252" in out
    assert "PDFs" in out
    for f in fcs:
        assert f.mode in out


def test_format_wall_handles_seconds_minutes_hours_days() -> None:
    assert "s" in forecasts._format_wall(45)
    assert "m" in forecasts._format_wall(180)
    assert "h" in forecasts._format_wall(7_200)
    assert "d" in forecasts._format_wall(200_000)


def test_baixar_scales_linearly() -> None:
    """Doubling targets doubles wall and bandwidth."""
    a = forecasts.forecast_baixar_pecas(5_000)[0]
    b = forecasts.forecast_baixar_pecas(10_000)[0]
    assert b.wall_s == pytest.approx(2 * a.wall_s, rel=1e-6)
    assert b.bandwidth_gb == pytest.approx(2 * a.bandwidth_gb, rel=1e-6)
