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
        "uv run judex varrer-processos --retentar-de <run>/sweep.errors.jsonl --saida <run>/",
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
        "uv run judex baixar-pecas --retentar-de <run>/pdfs.errors.jsonl --saida <run>/",
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
        "uv run judex extrair-pecas --retentar-de <run>/pdfs.errors.jsonl --saida <run>/",
    ),
    ("extrair", "cross_stage"): Recipe(
        "refetch_upstream",
        "no_bytes — bytes weren't downloaded; re-baixar first, then re-extrair",
        "uv run judex baixar-pecas --csv <subset> --saida <run>/  # then extrair-pecas same csv",
    ),
}

# Status-specific overrides on extrair: classifier returns ``terminal``
# for both, but the operator action is *not* "drop"; it's a different
# tool. Looked up before the generic ``(stage, kind)`` table.
_EXTRAIR_STATUS_OVERRIDES: dict[str, Recipe] = {
    "empty": Recipe(
        "switch_provider",
        "scanned/image-only PDF — pypdf gave up; re-extract with a beefier provider",
        "uv run judex extrair-pecas --csv <subset> --provedor chandra --forcar --saida <run>-empty-recover/",
    ),
    "unknown_type": Recipe(
        "refetch_bytes",
        "magic bytes weren't %PDF / {\\rtf — cache is corrupt; refresh the bytes",
        "uv run judex baixar-pecas --csv <subset> --saida <run>/",
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


def recovery_recipe(stage: Stage, row: dict) -> Recipe:
    """Return the operator action for one errors.jsonl row.

    Composes ``classify_error`` with the ``RECOVERY_RECIPES`` table.
    For extrair-stage rows a status-specific override fires before the
    generic ``(stage, kind)`` lookup: ``empty`` and ``unknown_type``
    are kind=terminal in the classifier but recoverable via a
    different tool (provider switch / byte refetch), so the recipe
    points at that tool rather than at ``drop_terminal``.
    """
    if stage == "extrair":
        status = row.get("status")
        if status in _EXTRAIR_STATUS_OVERRIDES:
            return _EXTRAIR_STATUS_OVERRIDES[status]
    kind = classify_error(stage, row)
    return RECOVERY_RECIPES[(stage, kind)]
