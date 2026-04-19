"""Cost estimation for sweeps.

Purpose: answer "how much did that run cost?" immediately after a
sweep finishes. Two cost surfaces exist:

1. **Proxy bandwidth** (`varrer-processos`, `baixar-pecas` when
   `--proxy-pool` is used). Residential providers bill per-GB.
2. **OCR API calls** (`extrair-pecas` when ``--provedor`` is mistral,
   chandra, or unstructured; pypdf is local → free).

Rates are environment-configurable so we don't hard-code provider
prices (they drift). Defaults are ballpark-2026 residential prices —
useful for "is this run $1 or $100" reasoning, not for billing.

Override via env vars before the run:

    PROXY_PRICE_USD_PER_GB=5.0 uv run judex baixar-pecas ...
    OCR_PRICE_MISTRAL_USD_PER_1K_PAGES=1.0 uv run judex extrair-pecas ...
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


_DEFAULT_PROXY_USD_PER_GB = 8.0
_DEFAULT_MISTRAL_USD_PER_1K_PAGES = 1.0
_DEFAULT_CHANDRA_USD_PER_1K_PAGES = 2.0
_DEFAULT_UNSTRUCTURED_USD_PER_1K_PAGES = 10.0


@dataclass(frozen=True)
class ProxyCost:
    bytes_downloaded: int
    used_proxy: bool
    usd_per_gb: float

    @property
    def dollars(self) -> float:
        if not self.used_proxy:
            return 0.0
        return (self.bytes_downloaded / 1_000_000_000) * self.usd_per_gb

    def summary_line(self) -> str:
        if not self.used_proxy:
            return "cost: $0.00 (direct-IP, no proxy bandwidth billed)"
        mb = self.bytes_downloaded / 1_000_000
        return (
            f"cost: ~${self.dollars:.2f}  "
            f"({mb:.1f} MB via proxy @ ${self.usd_per_gb:.2f}/GB)"
        )


@dataclass(frozen=True)
class OcrCost:
    provider: str  # pypdf | mistral | chandra | unstructured
    pages: int
    usd_per_1k_pages: float

    @property
    def dollars(self) -> float:
        if self.provider == "pypdf":
            return 0.0
        return (self.pages / 1_000) * self.usd_per_1k_pages

    def summary_line(self) -> str:
        if self.provider == "pypdf":
            return f"cost: $0.00 ({self.pages} pages via pypdf, local/free)"
        return (
            f"cost: ~${self.dollars:.2f}  "
            f"({self.pages} pages via {self.provider} @ "
            f"${self.usd_per_1k_pages:.2f}/1k pages)"
        )


def proxy_usd_per_gb() -> float:
    raw = os.environ.get("PROXY_PRICE_USD_PER_GB")
    if raw is None:
        return _DEFAULT_PROXY_USD_PER_GB
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_PROXY_USD_PER_GB


def ocr_usd_per_1k_pages(provider: str) -> float:
    """Look up the per-1k-pages rate for an OCR provider.

    Env overrides (case-insensitive provider):
        OCR_PRICE_MISTRAL_USD_PER_1K_PAGES
        OCR_PRICE_CHANDRA_USD_PER_1K_PAGES
        OCR_PRICE_UNSTRUCTURED_USD_PER_1K_PAGES

    Returns 0.0 for ``pypdf``.
    """
    p = provider.lower()
    if p == "pypdf":
        return 0.0
    env_key = f"OCR_PRICE_{p.upper()}_USD_PER_1K_PAGES"
    raw = os.environ.get(env_key)
    if raw is not None:
        try:
            return float(raw)
        except ValueError:
            pass
    return {
        "mistral": _DEFAULT_MISTRAL_USD_PER_1K_PAGES,
        "chandra": _DEFAULT_CHANDRA_USD_PER_1K_PAGES,
        "unstructured": _DEFAULT_UNSTRUCTURED_USD_PER_1K_PAGES,
    }.get(p, 0.0)


def estimate_proxy_cost(
    *, bytes_downloaded: int, used_proxy: bool,
    usd_per_gb: Optional[float] = None,
) -> ProxyCost:
    rate = usd_per_gb if usd_per_gb is not None else proxy_usd_per_gb()
    return ProxyCost(
        bytes_downloaded=bytes_downloaded,
        used_proxy=used_proxy,
        usd_per_gb=rate,
    )


def estimate_ocr_cost(
    *, provider: str, pages: int,
    usd_per_1k_pages: Optional[float] = None,
) -> OcrCost:
    rate = (
        usd_per_1k_pages
        if usd_per_1k_pages is not None
        else ocr_usd_per_1k_pages(provider)
    )
    return OcrCost(
        provider=provider,
        pages=pages,
        usd_per_1k_pages=rate,
    )
