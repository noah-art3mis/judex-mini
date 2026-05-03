"""Status-aware classification of sweep errors → replay decision.

Every line in `sweep.errors.jsonl` (varrer) and `pdfs.errors.jsonl`
(baixar / extrair) is one row. This module decides per row whether
the failure is:

- ``transient`` — replay it: WAF 403, Fly OCR 502, SSL-EOF, network
  flake, 5xx server-side, cookies refresh.
- ``terminal``  — drop it: ``unallocated`` processo_id (ADR-0002), real
  404, extractor returned empty / unknown type, decode error.
- ``cross_stage`` — drop within this stage's retry, but report so the
  operator knows: ``no_bytes`` rows from extrair are fixable by a
  baixar-retry, but inside ``judex coletar`` baixar-retry has already
  capped out by the time extrair runs (see ADR-0004).
- ``ok`` — not really an error: ``status=cached`` shows up in the
  state-snapshot side of errors.jsonl on baixar runs and must be
  dropped, not replayed.

The classifier is keyed on ``(status, error_substring)``. Status alone
is too coarse: varrer's ``fail`` row covers both "scrape returned None
(incidente not resolved)" — which is a terminal *processo_id não
alocado* — and transient WAF 403s. Pattern coverage is pinned by
``tests/unit/test_error_triage.py`` against every (status, error_substring)
tuple observed in real run dirs as of 2026-05-02.

Unknown rows default to ``terminal`` deliberately. Mis-classifying
terminal as transient burns retry budget on rows that cannot succeed;
mis-classifying transient as terminal abandons a recoverable failure
that surfaces in the residual report. The latter is louder and safer.
"""

from __future__ import annotations

from typing import Literal


Kind = Literal["transient", "terminal", "cross_stage", "ok"]
Stage = Literal["varrer", "baixar", "extrair"]

_VALID_STAGES = ("varrer", "baixar", "extrair")


# Substrings that flag a transient HTTP / network / TLS failure on
# either varrer or baixar. Conservative — extend when a new pattern
# appears in run dirs.
_TRANSIENT_NETWORK_PATTERNS = (
    "403",
    "5xx",
    "500",
    "502",
    "503",
    "504",
    "SSLEOF",
    "ssl",
    "ConnectionReset",
    "ConnectionError",
    "Timeout",
    "timed out",
    "ReadTimeout",
    "auth triad",
    "cookies",
)


def _has_transient_network_signal(error: str) -> bool:
    if not error:
        return False
    lowered = error.lower()
    return any(p.lower() in lowered for p in _TRANSIENT_NETWORK_PATTERNS)


def _classify_varrer(row: dict) -> Kind:
    status = row.get("status")
    error = row.get("error") or ""
    http_status = row.get("http_status")

    if status == "ok":
        return "ok"
    if status == "unallocated":
        return "terminal"

    # Legacy não-alocado: pre-`unallocated`-status corpus emits this
    # exact message under status=fail. Treat as terminal so cold runs
    # against old errors.jsonl converge.
    if "scrape returned none" in error.lower():
        return "terminal"

    # Real 404 (case page genuinely missing) — distinct from unallocated.
    if http_status == 404 or " 404 " in error or error.startswith("404"):
        return "terminal"

    if status in ("fail", "error"):
        if _has_transient_network_signal(error):
            return "transient"
        # Conservative: a fail row without a recognised transient
        # signature is treated as terminal so retry doesn't churn on
        # an unmapped deterministic failure.
        return "terminal"

    return "terminal"


def _classify_baixar(row: dict) -> Kind:
    status = row.get("status")
    error = row.get("error") or ""
    http_status = row.get("http_status")

    if status in ("ok", "cached"):
        return "ok"
    if status == "empty_response":
        return "transient"
    if status == "non_document_response":
        return "transient"
    if status == "http_error":
        if http_status == 404:
            return "terminal"
        if " 404 " in error or "404 " in error or "Not Found" in error:
            return "terminal"
        if _has_transient_network_signal(error):
            return "transient"
        return "terminal"

    return "terminal"


def _classify_extrair(row: dict) -> Kind:
    status = row.get("status")

    if status in ("ok", "cached"):
        return "ok"
    if status == "no_bytes":
        return "cross_stage"
    if status == "provider_error":
        return "transient"
    if status == "empty":
        return "terminal"
    if status == "unknown_type":
        return "terminal"

    return "terminal"


def classify_error(stage: Stage, row: dict) -> Kind:
    """Classify one errors.jsonl row given its source stage.

    The row dict is consumed read-only; only ``status``, ``error``,
    and ``http_status`` are inspected.
    """
    if stage not in _VALID_STAGES:
        raise ValueError(
            f"stage must be one of {_VALID_STAGES}, got {stage!r}"
        )
    if stage == "varrer":
        return _classify_varrer(row)
    if stage == "baixar":
        return _classify_baixar(row)
    return _classify_extrair(row)
