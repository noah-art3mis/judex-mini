"""Status-aware classification of sweep errors → replay decision → recovery recipe.

Every line in ``sweep.errors.jsonl`` (varrer) and ``pdfs.errors.jsonl``
(baixar / extrair) is one row. This module is two layers:

1. ``classify_error(stage, row) -> Kind`` — *what kind of failure is
   this?* Decides per row whether the failure is:

   - ``transient`` — replay it: WAF 403, Fly OCR 502, SSL-EOF, network
     flake, 5xx server-side, cookies refresh.
   - ``terminal``  — drop it: ``unallocated`` processo_id (ADR-0002),
     real 404, extractor returned empty / unknown type, decode error.
   - ``cross_stage`` — drop within this stage's retry, but report so
     the operator knows: ``no_bytes`` rows from extrair are fixable by
     a baixar-retry, but inside ``judex coletar`` baixar-retry has
     already capped out by the time extrair runs (see ADR-0004).
   - ``ok`` — not really an error: ``status=cached`` shows up in the
     state-snapshot side of errors.jsonl on baixar runs and must be
     dropped, not replayed.

2. ``recovery_recipe(stage, row) -> Recipe`` — *what should the
   operator do?* Composes on top of ``classify_error``: looks up the
   ``(stage, kind)`` cell in ``RECOVERY_RECIPES`` and returns a
   ``Recipe(action, summary, command_hint)`` the operator (or a future
   ``judex limpar`` cleanup step) can act on. Same table that backed
   the per-stage recovery tables in ``docs/recovery-patterns.md``
   before they were collapsed in here.

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

from dataclasses import dataclass
from typing import Literal


Kind = Literal["transient", "terminal", "cross_stage", "ok"]
Stage = Literal["varrer", "baixar", "extrair"]
Action = Literal[
    "none",                 # ok / cached — nothing to do
    "replay",               # transient — re-queue via --retomar / --retentar-de
    "drop_terminal",        # terminal — confirmed-final; report in residual
    "switch_provider",      # extrair empty — re-extract with chandra/mistral
    "refetch_bytes",        # extrair unknown_type — bytes are corrupt; re-baixar
    "refetch_upstream",     # extrair no_bytes — cross-stage; needs baixar first
    "investigate",          # unmapped — defaults to terminal but worth a look
]

_VALID_STAGES = ("varrer", "baixar", "extrair")


@dataclass(frozen=True)
class Recipe:
    """Operator-facing recovery action for one errors.jsonl row.

    - ``action``: the abstract verb (used by ``judex limpar`` /
      cleanup tooling to dispatch the right command).
    - ``summary``: one-line human reason ("WAF 403 — re-queue on a
      different IP").
    - ``command_hint``: optional ready-to-paste invocation. May be
      ``None`` when the action is ``"none"`` or ``"drop_terminal"``.
    """

    action: Action
    summary: str
    command_hint: str | None = None


# Recovery recipes keyed on ``(stage, kind)``. The classifier already
# decides the kind; this table only encodes operator action per kind
# in the context of each stage. ``ok`` and ``terminal`` cells are
# stage-uniform; ``transient`` and ``cross_stage`` carry stage-specific
# command hints.
#
# Extrair has two extra cells that are kind=terminal in the classifier
# but recoverable via a *different* tool (provider switch, byte
# refetch); those override the generic terminal recipe by inspecting
# the row's status before falling back to the table.
RECOVERY_RECIPES: dict[tuple[Stage, Kind], Recipe] = {
    ("varrer", "ok"): Recipe("none", "succeeded"),
    ("varrer", "terminal"): Recipe(
        "drop_terminal",
        "real 404 or unallocated processo_id (ADR-0002) — confirmed-final",
    ),
    ("varrer", "transient"): Recipe(
        "replay",
        "WAF 403 / 5xx / SSL / cookies churn — cookies + IP rotate naturally between runs",
        "uv run judex executar --retentar-de <run>/executar.errors.jsonl --saida <run>/",
    ),
    ("varrer", "cross_stage"): Recipe(
        "drop_terminal",
        "no upstream stage exists for varrer — should not occur",
    ),
    ("baixar", "ok"): Recipe("none", "succeeded or cached"),
    ("baixar", "terminal"): Recipe(
        "drop_terminal",
        "PDF genuinely missing on STF (real 404)",
    ),
    ("baixar", "transient"): Recipe(
        "replay",
        "empty / non-document / 5xx / SSL / Timeout — usually auth/cookie/Referer churn (abaX.asp triad, see CLAUDE.md)",
        "uv run judex executar --retentar-de <run>/executar.errors.jsonl --saida <run>/",
    ),
    ("baixar", "cross_stage"): Recipe(
        "drop_terminal",
        "no upstream stage exists for baixar — should not occur",
    ),
    ("extrair", "ok"): Recipe("none", "succeeded or cached"),
    ("extrair", "terminal"): Recipe(
        "drop_terminal",
        "extractor returned empty / unknown_type — see status-specific override",
    ),
    ("extrair", "transient"): Recipe(
        "replay",
        "Fly OCR 502 / network blip / provider error — re-queue",
        "uv run judex executar --retentar-de <run>/executar.errors.jsonl --saida <run>/",
    ),
    ("extrair", "cross_stage"): Recipe(
        "refetch_upstream",
        "no_bytes — bytes weren't downloaded; re-run executar against the same range/CSV (cache-skips the bytes that did succeed, refetches the missing)",
        "uv run judex executar --csv <subset> --saida <run>/",
    ),
}

# URL substring patterns on which an HTTP 404 is *deterministic and
# permanent*, not a WAF/transient flake. The
# ``digital.stf.jus.br/decisoes-monocraticas/api/public/votos/{id}/conteudo.pdf``
# endpoint serves Voto/Relatório PDFs that may have been withdrawn or
# never finalised — re-running on a fresh IP returns the same 404.
# Recovery: drop quietly, distinct from a generic terminal so operators
# can account for these without thinking they're missed retries.
_PERMANENT_404_URL_SUBSTRINGS: tuple[str, ...] = (
    "digital.stf.jus.br/decisoes-monocraticas/api/public/votos/",
)


_PERMANENT_404_RECIPE = Recipe(
    "drop_terminal",
    "permanent 404 on a known-withdrawn endpoint (votos/conteudo.pdf) — PDF was never published or has been removed; retry returns the same 404 on any IP",
)


def _is_permanent_404(row: dict) -> bool:
    """True if a row is an HTTP 404 against a known-permanent endpoint.

    Distinct from generic terminal 404s (which the ``(stage, terminal)``
    recipe catches) because the *reason* is provable: the upstream
    endpoint serves these as deterministic 404s rather than WAF blocks.
    """
    if row.get("http_status") != 404:
        return False
    url = row.get("url") or ""
    return any(p in url for p in _PERMANENT_404_URL_SUBSTRINGS)


# Status-specific overrides on extrair: classifier returns ``terminal``
# for these statuses, but the operator action is *not* "drop"; it's a
# different tool. Looked up before the generic ``(stage, kind)`` table.
_EXTRAIR_STATUS_OVERRIDES: dict[str, Recipe] = {
    "empty": Recipe(
        "switch_provider",
        "scanned/image-only PDF — pypdf gave up; re-extract with a beefier provider",
        "uv run judex re-extrair <urls.txt> --provedor chandra --forcar",
    ),
    "unknown_type": Recipe(
        "refetch_bytes",
        "magic bytes weren't %PDF / {\\rtf — cache is corrupt; refresh the bytes via a fresh executar pass",
        "uv run judex executar --csv <subset> --saida <run>/  # cache-skip on bytes drops, fresh fetch refills",
    ),
    # ``outlier_skipped``: emitted by the runner when a cached PDF exceeds
    # the cloud-OCR body cap (>1 MB by default — Modal/Fly response-size
    # limit). Re-running the same sweep would skip again. The actionable
    # recovery is **local** Tesseract, which has no body-size limit.
    # Action shape matches ``empty`` (provider switch) but the destination
    # provider is specifically the local one. URL-scoped via ``judex
    # re-extrair`` so we don't over-extract the rest of the case's
    # peças (which already have clean pypdf text).
    "outlier_skipped": Recipe(
        "switch_provider",
        "PDF exceeds cloud-OCR body cap — re-extract with local tesseract (no cap)",
        "uv run judex re-extrair <urls.txt> --provedor tesseract --forcar",
    ),
}


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
    # `ProxyError` is the requests/urllib3 wrapper for proxy-pool churn
    # (407 auth, 502 from upstream proxy, max-retries exceeded against
    # the proxy itself). Always transient — re-issue against a fresh
    # proxy from the pool.
    "ProxyError",
    # `ChunkedEncodingError` covers `Response ended prematurely` and
    # `IncompleteRead` — TCP-level mid-stream breaks. Definitionally
    # transient — the next request lands.
    "ChunkedEncodingError",
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
    # `unallocated` is the legacy `varrer-processos` name; `unallocated_pid`
    # is the unified-pipeline (`executar`) name for the same ADR-0002 fact.
    if status in ("unallocated", "unallocated_pid"):
        return "terminal"

    # Legacy não-alocado: pre-`unallocated`-status corpus emits this
    # exact message under status=fail. Treat as terminal so cold runs
    # against old errors.jsonl converge.
    if "scrape returned none" in error.lower():
        return "terminal"

    # Real 404 (case page genuinely missing) — distinct from unallocated.
    if http_status == 404 or " 404 " in error or error.startswith("404"):
        return "terminal"

    # `executar` surfaces network-layer failures under status=http_error
    # (proxy-pool churn, mid-stream breaks). The legacy `varrer-processos`
    # path used status=fail/error; both must triage on the same network
    # signal pattern set.
    if status == "http_error":
        if _has_transient_network_signal(error):
            return "transient"
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
    # `empty_response` is the legacy `baixar-pecas` name; `empty` is
    # the unified-pipeline (`executar`) rename. Both mean "200 OK with
    # zero-length body" — a pure WAF/LB flake, replay candidate.
    if status in ("empty_response", "empty"):
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


def recovery_recipe(stage: Stage, row: dict) -> Recipe:
    """Return the operator action for one errors.jsonl row.

    Composes ``classify_error`` with the ``RECOVERY_RECIPES`` table.
    For extrair-stage rows a status-specific override fires before the
    generic ``(stage, kind)`` lookup: ``empty`` and ``unknown_type``
    are kind=terminal in the classifier but recoverable via a
    different tool (provider switch / byte refetch), so the recipe
    points at that tool rather than at ``drop_terminal``.
    """
    # Permanent-404 override fires across every stage: the same
    # known-deterministic 404 endpoints would emit identical signals
    # regardless of which stage observed them. Checked before the
    # extrair-status overrides because a permanent 404 is more
    # specific than a generic empty/unknown_type/outlier classification.
    if _is_permanent_404(row):
        return _PERMANENT_404_RECIPE
    if stage == "extrair":
        status = row.get("status")
        if status in _EXTRAIR_STATUS_OVERRIDES:
            return _EXTRAIR_STATUS_OVERRIDES[status]
    kind = classify_error(stage, row)
    return RECOVERY_RECIPES[(stage, kind)]
