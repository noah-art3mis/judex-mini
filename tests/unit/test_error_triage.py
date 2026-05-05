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


@pytest.mark.parametrize("row,expected", [
    # Unified-pipeline (`executar`) status alias for ADR-0002. Legacy
    # `varrer-processos` emits `status=unallocated`; `executar` emits
    # `status=unallocated_pid`. Same fact, different name. Observed in
    # HC 2021 executar (1,975 rows / 28% of the 7,085-case input — a
    # gap-sweep, so high unallocated density is expected).
    ({"status": "unallocated_pid"}, "terminal"),
    # Unified-pipeline rows surface proxy-pool / chunked-encoding
    # exceptions under `status=http_error` rather than as fail/error
    # rows. Both signatures are definitionally transient (proxy auth
    # churn, mid-stream connection broken). Observed in HC 2021 executar
    # fetch_meta (26 ProxyError rows on portal.stf.jus.br) — without
    # this branch the classifier defaulted them to terminal and 26
    # replayable cases were dropped.
    ({"status": "http_error",
      "error": "ProxyError: HTTPSConnectionPool(host='portal.stf.jus.br', port=443): Max retries exceeded"},
     "transient"),
    ({"status": "http_error",
      "error": "ChunkedEncodingError: Response ended prematurely"},
     "transient"),
    # http_error on varrer that genuinely is a 404 stays terminal.
    ({"status": "http_error",
      "error": "HTTPError: 404 Not Found",
      "http_status": 404}, "terminal"),
])
def test_classify_varrer_unified_pipeline(row: dict, expected: str) -> None:
    """Unified pipeline (`executar`) emits status names the legacy
    classifier didn't recognise. Pin the parity here so post-patch
    drift is loud."""
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


@pytest.mark.parametrize("row,expected", [
    # Unified-pipeline `status="empty"` for "200 OK with zero-length
    # body". The legacy name was `empty_response` and `executar`
    # renamed it to `empty`. The signature is exact: every row in the
    # HC 2021 executar run carrying `status=empty` had the same error
    # `unrecognised peça magic bytes: b''` (the b'' is literally a
    # zero-byte response, not a real-404). 1,035 such rows — all
    # transient WAF/LB flakes; re-request usually lands.
    ({"status": "empty",
      "error": "unrecognised peça magic bytes: b''; expected one of [b'%PDF', b'{\\rtf']"},
     "transient"),
    # ProxyError under http_error — same proxy-pool-churn shape as
    # varrer. Observed in HC 2021 executar baixar (13 rows).
    ({"status": "http_error",
      "error": "ProxyError: HTTPSConnectionPool(host='sistemas.stf.jus.br', port=443): Max retries exceeded"},
     "transient"),
    # ChunkedEncodingError under http_error — mid-stream connection
    # broken. Definitionally transient. Observed in HC 2021 executar
    # baixar (17 rows; 7 "Response ended prematurely" + 10
    # "IncompleteRead" variants — both are the same TCP-level event).
    ({"status": "http_error",
      "error": "ChunkedEncodingError: Response ended prematurely"},
     "transient"),
    ({"status": "http_error",
      "error": "ChunkedEncodingError: ('Connection broken: IncompleteRead(15563 bytes read, 12345 more expected)',)"},
     "transient"),
])
def test_classify_baixar_unified_pipeline(row: dict, expected: str) -> None:
    """Same unified-pipeline-parity contract as varrer — pin the new
    status names so they don't silently regress to terminal."""
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
    # Recipe must point at the live unified-pipeline command, not the
    # removed legacy `extrair-pecas`.
    assert "judex executar" in (recipe.command_hint or "")
    assert "extrair-pecas" not in (recipe.command_hint or "")


def test_extrair_unknown_type_routes_to_refetch_bytes() -> None:
    """Same override pattern: corrupt cache → refetch via baixar, not drop."""
    recipe = recovery_recipe("extrair",
                             {"status": "unknown_type",
                              "error": "extension not in {pdf, rtf}"})
    assert recipe.action == "refetch_bytes"
    # Refetch-then-re-extract is two steps in the unified pipeline,
    # both via `judex executar` (no separate baixar-pecas command exists
    # since the 0e874b3 cleanup).
    assert "judex executar" in (recipe.command_hint or "")
    assert "baixar-pecas" not in (recipe.command_hint or "")


def test_extrair_outlier_skipped_routes_to_switch_provider_local() -> None:
    """``outlier_skipped`` is emitted by the runner when a PDF exceeds the
    cloud-OCR size cap (>1 MB by default — Modal/Fly response-body limit).
    Re-running with the *same* provider would skip again. The actionable
    recovery is local Tesseract (no body cap).

    Distinct command-hint shape from ``empty`` (which routes to chandra
    /mistral): outliers specifically require a local provider, not just
    any beefier one. Sub-issue 02 of .scratch/run-cleanup-loop/.
    """
    recipe = recovery_recipe(
        "extrair",
        {"status": "outlier_skipped",
         "error_type": "OutlierPdf",
         "error": "PDF size 1.19 MB exceeds 1 MB cloud-OCR threshold"},
    )
    assert recipe.action == "switch_provider"
    hint = recipe.command_hint or ""
    assert "tesseract" in hint, hint
    # URL-scoped (no over-extraction): must point at extrair-urls, not
    # the case-scoped executar --csv path that re-OCRs whole cases.
    assert "extrair-urls" in hint, hint
    # Must not point at a cloud provider — defeats the purpose.
    for cloud in ("chandra", "mistral", "tesseract_modal", "tesseract_fly"):
        assert cloud not in hint, (
            f"outlier recipe should target *local* tesseract, not {cloud}: {hint}"
        )


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


def test_recovery_recipe_routes_votos_404_to_permanent_404() -> None:
    """The ``digital.stf.jus.br/.../votos/{id}/conteudo.pdf`` endpoint
    serves PDFs that were withdrawn / never published. A 404 there is
    deterministic and permanent — re-running just confirms the same
    absence. Distinct recipe so operators (and limpar) can see these as
    a separate accounting bucket without lumping them with WAF 404s
    that *would* be transient on a different IP.

    Sub-issue 05 of .scratch/run-cleanup-loop/. Concrete cases that
    triggered this: HC 252164, 264813, 266879 (each with a
    Voto + Relatório symmetric pair).
    """
    row = {
        "status": "http_error",
        "error": "HTTPError: 404",
        "http_status": 404,
        "url": "https://digital.stf.jus.br/decisoes-monocraticas/api/public/votos/12345/conteudo.pdf",
    }
    recipe = recovery_recipe("baixar", row)
    assert recipe.action == "drop_terminal"
    # Must surface the permanent-404 reason in the summary so the
    # operator (or a future limpar count) can distinguish.
    summary_lower = (recipe.summary or "").lower()
    assert "permanent" in summary_lower or "withdrawn" in summary_lower, (
        f"summary must flag the permanent-404 nature, got: {recipe.summary!r}"
    )


def test_recovery_recipe_non_votos_404_keeps_generic_drop() -> None:
    """A 404 on a non-votos URL must keep the generic terminal recipe —
    the permanent-404 override is keyed on the votos endpoint specifically.
    """
    row = {
        "status": "http_error",
        "error": "HTTPError: 404",
        "http_status": 404,
        "url": "https://portal.stf.jus.br/processos/downloadPeca.asp?id=999&ext=.pdf",
    }
    recipe = recovery_recipe("baixar", row)
    assert recipe.action == "drop_terminal"
    summary_lower = (recipe.summary or "").lower()
    assert "permanent" not in summary_lower


def test_recovery_recipe_routes_cross_stage_to_refetch_upstream() -> None:
    """no_bytes on extrair must point at the unified pipeline rerun, not
    at the removed legacy baixar-pecas/extrair-pecas commands."""
    recipe = recovery_recipe("extrair",
                             {"status": "no_bytes",
                              "error": "bytes missing from cache"})
    assert recipe.action == "refetch_upstream"
    assert "judex executar" in (recipe.command_hint or "")
    assert "baixar-pecas" not in (recipe.command_hint or "")


def test_recovery_recipe_ok_action_is_none() -> None:
    """An ``ok`` row needs no action; the recipe must say so explicitly."""
    assert recovery_recipe("baixar", {"status": "ok"}).action == "none"
    assert recovery_recipe("baixar", {"status": "cached"}).action == "none"
