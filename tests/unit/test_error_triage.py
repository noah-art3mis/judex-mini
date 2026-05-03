"""Pin the (stage, status, error) → kind classifier.

Every (status, error_substring) tuple observed in real run dirs as of
2026-05-02 is in this file. When a sweep emits a previously-unseen
status, this test fails and the classifier must be extended — that is
the load-bearing safety property: an unmapped row defaults to
`terminal` (do not retry it), so missing a real transient pattern
costs convergence.
"""

from __future__ import annotations

import pytest

from judex.sweeps.error_triage import (
    RECOVERY_RECIPES,
    classify_error,
    recovery_recipe,
)


# ----- varrer ---------------------------------------------------------------


@pytest.mark.parametrize("row,expected", [
    # Terminal: ok
    ({"status": "ok"}, "ok"),
    # Terminal: STF resolved the lookup but the processo_id was never
    # bound to an incidente. ADR-0002. Per-classe registry pre-filters
    # but errors.jsonl can still carry these on cold runs.
    ({"status": "unallocated"}, "terminal"),
    # Terminal (legacy não-alocado before status=unallocated existed):
    # observed in HC 2026 backfill 2026-05-01 varrer/sweep.errors.jsonl
    # with all 903 rows being status=fail + this exact error message.
    ({"status": "fail", "error": "scrape returned None (incidente not resolved): ''"},
     "terminal"),
    ({"status": "fail", "error": "scrape returned None"}, "terminal"),
    # Transient: WAF 403 — the per-IP block clears within minutes.
    ({"status": "fail", "error": "403 Forbidden", "http_status": 403}, "transient"),
    ({"status": "fail", "error": "HTTPError: 403", "http_status": 403}, "transient"),
    # Transient: cookies/auth refresh flake.
    ({"status": "fail", "error": "auth triad refused; refreshing cookies"}, "transient"),
    # Transient: TLS / network.
    ({"status": "fail", "error": "SSLEOFError: EOF occurred in violation of protocol"},
     "transient"),
    ({"status": "fail", "error": "ConnectionResetError: [Errno 104]"}, "transient"),
    ({"status": "fail", "error": "requests.exceptions.Timeout: read timed out"},
     "transient"),
    # Transient: 5xx server-side.
    ({"status": "error", "error": "HTTPError: 502 Bad Gateway", "http_status": 502},
     "transient"),
    ({"status": "error", "error": "HTTPError: 503 Service Unavailable",
      "http_status": 503}, "transient"),
])
def test_classify_varrer(row: dict, expected: str) -> None:
    assert classify_error("varrer", row) == expected


# ----- baixar ---------------------------------------------------------------


@pytest.mark.parametrize("row,expected", [
    # Terminal: ok / cached.
    ({"status": "ok"}, "ok"),
    ({"status": "cached"}, "ok"),
    # Transient: STF returned 200 OK with empty body — observed in HC
    # 2025 backfill (10 rows out of 28k). Per peca_store comment:
    # "transient edge glitch; URL goes to errors.jsonl for replay".
    ({"status": "empty_response", "error": "200 OK with empty body"}, "transient"),
    # Transient: body had unexpected magic bytes (HTML soft-error page).
    ({"status": "non_document_response", "error": "expected PDF magic, got HTML"},
     "transient"),
    # Terminal: real 404, the peça is gone from STF — observed in HC
    # 2025 baixar (6 rows) and HC 2026 baixar (10 rows).
    ({"status": "http_error",
      "error": "HTTPError: 404 Client Error: Not Found for url: https://digital.stf.jus.br/decisoes...",
      "http_status": 404}, "terminal"),
    # Transient: WAF 403.
    ({"status": "http_error", "error": "HTTPError: 403 Forbidden",
      "http_status": 403}, "transient"),
    # Transient: 5xx.
    ({"status": "http_error", "error": "HTTPError: 502 Bad Gateway",
      "http_status": 502}, "transient"),
    ({"status": "http_error", "error": "HTTPError: 504 Gateway Timeout",
      "http_status": 504}, "transient"),
    # Transient: TLS/network.
    ({"status": "http_error", "error": "SSLEOFError: EOF occurred"}, "transient"),
])
def test_classify_baixar(row: dict, expected: str) -> None:
    assert classify_error("baixar", row) == expected


# ----- extrair --------------------------------------------------------------


@pytest.mark.parametrize("row,expected", [
    # Terminal: ok / cached.
    ({"status": "ok"}, "ok"),
    ({"status": "cached"}, "ok"),
    # Cross-stage: bytes never landed; fix is upstream in baixar, not
    # in extrair-retry. Observed in HC 2026 extrair (10 rows) with this
    # exact error message.
    ({"status": "no_bytes", "error": "run baixar-pecas first"}, "cross_stage"),
    # Transient: Fly OCR bounce — observed in HC 2026 extrair (383
    # rows, ~7%) and live in HC 2025 extrair.
    ({"status": "provider_error",
      "error": "HTTPError: 502 Server Error: Bad Gateway for url: https://judex-ocr-tesseract-arcos.fly.dev/extract"},
     "transient"),
    ({"status": "provider_error", "error": "HTTPError: 504 Gateway Timeout"},
     "transient"),
    ({"status": "provider_error", "error": "ReadTimeoutError: HTTPSConnectionPool"},
     "transient"),
    # Terminal: extractor finished but produced empty text. With
    # --provedor auto this means OCR also gave up — re-trying with the
    # same provider will repeat the empty result.
    ({"status": "empty", "error": "pypdf returned 0 chars"}, "terminal"),
    # Terminal: bytes are not an extractable document type (e.g.
    # `.htm` or some other rejected magic).
    ({"status": "unknown_type", "error": "extension not in {pdf, rtf}"}, "terminal"),
])
def test_classify_extrair(row: dict, expected: str) -> None:
    assert classify_error("extrair", row) == expected


# ----- safety: unknown rows default to terminal -----------------------------


def test_unknown_status_defaults_terminal() -> None:
    """An unmapped status must default to `terminal`, not `transient`.

    The cost of mis-classifying terminal as transient is a retry that
    cannot succeed — operator wastes a retry budget. The cost of
    mis-classifying transient as terminal is a recoverable failure
    that we abandon — operator notices in the residual report and
    files a classifier patch. The latter is louder and safer.
    """
    assert classify_error("varrer", {"status": "completely_made_up"}) == "terminal"
    assert classify_error("baixar", {"status": "magic_unicorn"}) == "terminal"
    assert classify_error("extrair", {"status": "void"}) == "terminal"


def test_invalid_stage_raises() -> None:
    """Stage typo should fail loudly, not silently classify wrong."""
    with pytest.raises(ValueError, match="stage"):
        classify_error("varrar", {"status": "ok"})  # type: ignore[arg-type]


# ----- recovery recipes -----------------------------------------------------


def test_recovery_table_covers_every_stage_kind_cell() -> None:
    """Every (stage, kind) the classifier can return must have a recipe.

    Without this, ``recovery_recipe`` would KeyError on a row whose
    triage outcome the table doesn't cover. The classifier returns
    one of four kinds for one of three stages; all 12 cells must be
    populated.
    """
    expected_keys = {
        (stage, kind)
        for stage in ("varrer", "baixar", "extrair")
        for kind in ("ok", "transient", "terminal", "cross_stage")
    }
    assert set(RECOVERY_RECIPES.keys()) == expected_keys


def test_extrair_empty_routes_to_switch_provider() -> None:
    """The whole point of the override: ``empty`` is kind=terminal in
    the classifier (re-running the same provider won't help) but the
    operator action is *not* "drop" — it's switch to chandra/mistral.
    The status-specific override must fire before the generic
    (extrair, terminal) → drop_terminal recipe.
    """
    recipe = recovery_recipe("extrair", {"status": "empty",
                                          "error": "pypdf returned 0 chars"})
    assert recipe.action == "switch_provider"
    assert "chandra" in (recipe.command_hint or "")


def test_extrair_unknown_type_routes_to_refetch_bytes() -> None:
    """Same override pattern: corrupt cache → refetch via baixar, not drop."""
    recipe = recovery_recipe("extrair",
                             {"status": "unknown_type",
                              "error": "extension not in {pdf, rtf}"})
    assert recipe.action == "refetch_bytes"
    assert "baixar-pecas" in (recipe.command_hint or "")


def test_recovery_recipe_routes_transient_to_replay() -> None:
    """A WAF 403 on varrer is the canonical replay row."""
    recipe = recovery_recipe("varrer",
                             {"status": "fail", "error": "403 Forbidden",
                              "http_status": 403})
    assert recipe.action == "replay"
    assert "retentar-de" in (recipe.command_hint or "")


def test_recovery_recipe_routes_terminal_to_drop() -> None:
    """A real 404 on baixar is the canonical drop row."""
    recipe = recovery_recipe("baixar",
                             {"status": "http_error",
                              "error": "HTTPError: 404 Not Found",
                              "http_status": 404})
    assert recipe.action == "drop_terminal"
    assert recipe.command_hint is None


def test_recovery_recipe_routes_cross_stage_to_refetch_upstream() -> None:
    """no_bytes on extrair must point at re-baixar, not at retry-extrair."""
    recipe = recovery_recipe("extrair",
                             {"status": "no_bytes",
                              "error": "run baixar-pecas first"})
    assert recipe.action == "refetch_upstream"
    assert "baixar-pecas" in (recipe.command_hint or "")


def test_recovery_recipe_ok_action_is_none() -> None:
    """An ``ok`` row needs no action; the recipe must say so explicitly."""
    assert recovery_recipe("baixar", {"status": "ok"}).action == "none"
    assert recovery_recipe("baixar", {"status": "cached"}).action == "none"
