"""Behavior tests for `_resolve_publicacoes_dje` — the loop that enriches
each DJe listing entry with detail-page fields.

Regression pin for the Phase 1 (ADR-0003) bug: redirect-form entries
have `detail_url=None` (post-2022 STF migration; the legacy detail
page no longer exists for these). The resolver must skip them, not
pass `None` to the fetcher (which crashes with
`AttributeError: 'NoneType' object has no attribute 'encode'`).
"""

from __future__ import annotations

import pytest

from judex.scraping.scraper_dje import _resolve_publicacoes_dje


def test_resolve_skips_redirect_form_entries_with_none_detail_url():
    """Redirect-form entries (Phase 1 ADR-0003) have detail_url=None and
    must NOT trigger a detail fetch — would crash with AttributeError.
    """
    fetched_urls: list[str] = []

    def fake_fetcher(url: str) -> str:
        fetched_urls.append(url)
        return "<html>detail</html>"

    entries = [
        # Legacy entry — has detail_url, gets enriched.
        {"detail_url": "https://example.com/detail/1", "data": "2022-05-01"},
        # Redirect-form entry — None detail_url, should be skipped.
        {"detail_url": None, "data": "2024-03-15",
         "external_redirect": "https://digital.stf.jus.br/publico/publicacoes"},
    ]

    # Should not raise.
    out = _resolve_publicacoes_dje(entries, detail_fetcher=fake_fetcher)

    # Fetcher only called for the legacy entry.
    assert fetched_urls == ["https://example.com/detail/1"]
    # Both entries returned (redirect form preserved as-is).
    assert len(out) == 2
    # Redirect-form entry's external_redirect preserved.
    assert out[1]["external_redirect"] == "https://digital.stf.jus.br/publico/publicacoes"
    assert out[1]["detail_url"] is None


def test_resolve_handles_all_redirect_form_entries_without_crash():
    """Pure post-2022 case: all entries are redirect-form. Resolver
    should be a no-op (no fetches), not crash.
    """
    def fake_fetcher(url: str) -> str:
        raise AssertionError(f"should not be called, got url={url!r}")

    entries = [
        {"detail_url": None, "external_redirect": "https://digital.stf.jus.br/publico/publicacoes"},
        {"detail_url": None, "external_redirect": "https://digital.stf.jus.br/publico/publicacoes"},
    ]

    out = _resolve_publicacoes_dje(entries, detail_fetcher=fake_fetcher)

    assert len(out) == 2
    assert all(e["detail_url"] is None for e in out)
