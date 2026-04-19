"""judex.utils.pricing — cost estimation.

Covers the two cost surfaces (proxy bandwidth + OCR) and env-var
overrides. Deliberately thin: the arithmetic is a few multiplies;
the point is that the reporting is wired end-to-end and that the
zero-cost paths (direct-IP, pypdf) are handled.
"""

from __future__ import annotations

import pytest

from judex.utils.pricing import (
    estimate_ocr_cost,
    estimate_proxy_cost,
    ocr_usd_per_1k_pages,
    proxy_usd_per_gb,
)


def test_proxy_cost_zero_when_direct_ip() -> None:
    c = estimate_proxy_cost(
        bytes_downloaded=10_000_000_000, used_proxy=False,
    )
    assert c.dollars == 0.0
    assert "direct-IP" in c.summary_line()


def test_proxy_cost_scales_with_bytes_and_rate() -> None:
    # 500 MB at $8/GB = $4.00
    c = estimate_proxy_cost(
        bytes_downloaded=500_000_000, used_proxy=True, usd_per_gb=8.0,
    )
    assert c.dollars == pytest.approx(4.0)


def test_proxy_cost_reads_env_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY_PRICE_USD_PER_GB", "5.0")
    assert proxy_usd_per_gb() == pytest.approx(5.0)


def test_proxy_cost_ignores_malformed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY_PRICE_USD_PER_GB", "not-a-number")
    # Falls back to default rather than raising
    assert proxy_usd_per_gb() > 0.0


def test_ocr_cost_is_zero_for_pypdf() -> None:
    c = estimate_ocr_cost(provider="pypdf", pages=10_000)
    assert c.dollars == 0.0
    assert "pypdf" in c.summary_line()


def test_ocr_cost_mistral_default() -> None:
    c = estimate_ocr_cost(provider="mistral", pages=1_000)
    # Default $1/1k pages
    assert c.dollars == pytest.approx(1.0)


def test_ocr_cost_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR_PRICE_MISTRAL_USD_PER_1K_PAGES", "2.5")
    # Default module-level lookup picks up env
    assert ocr_usd_per_1k_pages("mistral") == pytest.approx(2.5)
    c = estimate_ocr_cost(provider="mistral", pages=2_000)
    assert c.dollars == pytest.approx(5.0)
