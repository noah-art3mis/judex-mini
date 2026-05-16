"""Single source of truth for "is this (kind, status) failure retryable?".

Two call sites need the same answer:

- :func:`judex.pipeline.scheduler._is_retryable_status` — the live
  scheduler's seed-builder, deciding whether to re-enqueue a task on
  resume.
- :func:`judex.pipeline.log.classify_unified_error` — the classifier
  that powers ``judex recuperar`` (REPLAY bucket admission) and
  ``--retentar-de`` target selection.

When these disagreed historically (``(fetch_bytes, empty)`` known to
``classify_unified_error`` as transient — pinned by HC 271343 in
``runs/active/hc-atualizar-20260503`` — but unknown to
``_is_retryable_status``), ``recuperar --apply`` dispatched the row,
the child runner's seed-builder filtered it out, and the residual
never shrank. This module holds the policy; both sites delegate.
The equivalence is pinned by ``tests/unit/test_recovery_policy.py``.
"""

from __future__ import annotations

from typing import Optional


RETRY_CAP = 2
"""Maximum number of retry cycles per task. Inherited from ADR-0004's
"cap of 2 retry cycles per stage" contract (now per-Task in the unified
pipeline). The retryability predicate below is policy; the cap is
budget — separate concerns, both consulted by the scheduler wrapper."""


def is_retryable_status(
    kind: Optional[str], status: Optional[str],
) -> bool:
    """True if a ``(kind, status)`` failure is worth retrying as-is.

    Two layers in the decision table:

    1. **Transport-layer statuses** (``http_error``, ``provider_error``)
       are transient regardless of kind. They name a network / provider
       flake, not a content fact, so the kind doesn't change their
       interpretation. ``classify_unified_error`` callers that pass a
       bare ``{"status": ...}`` row — no ``kind`` — must still get the
       right answer here.
    2. **Content-layer statuses** (``empty``, ``no_bytes``,
       ``unallocated_pid``, ...) ARE kind-dependent. The notable case:
       ``empty`` means a 0-byte body on the bytes stage (WAF/LB flake;
       transient — pinned by HC 271343 in ``hc-atualizar-20260503``)
       but means "provider returned 0 chars" on the extract stage
       (terminal under replay; ``recuperar`` routes it to
       PROVIDER_SWITCH instead).

    Full table:

    * ``None`` → True (never attempted; first-time work).
    * ``ok`` / ``skipped_cached`` → False (already terminal-good;
      caller filters before asking).
    * ``http_error`` (any kind) → True. Portal/sistemas WAF / SSL /
      timeout / connection flake.
    * ``provider_error`` (any kind) → True. Cloud OCR provider hiccup.
    * ``(fetch_bytes, empty)`` → True. The recuperar-vs-scheduler
      drift cell — fixed when the policy was extracted here.
    * ``(extract_text, empty)`` → False. Same provider would give same
      result; recovery is a provider switch.
    * ``no_bytes`` → False (cross-stage; retrying the extract burns
      the OCR pool on missing input. ``recuperar`` REFETCH_UPSTREAM).
    * ``unallocated_pid`` → False (STF's portal genuinely has no
      incidente bound to the case-id; ADR-0002).
    * Anything unknown → False (conservative — better to surface in
      the residual report than to churn the WAF on an unmapped
      failure).
    """
    if status is None:
        return True
    if status in ("ok", "skipped_cached"):
        return False
    if status in ("http_error", "provider_error"):
        return True
    if kind == "fetch_bytes" and status == "empty":
        return True
    return False


def is_cross_stage_status(status: Optional[str]) -> bool:
    """True if the failure is a missing upstream artefact.

    Currently only ``no_bytes`` (extract-stage couldn't run because
    bytes-stage didn't land). Recovery for a cross-stage row is to
    refetch the upstream stage, not to retry this one — ``recuperar``
    routes these to the REFETCH_UPSTREAM bucket, the scheduler's
    seed-builder skips them entirely on resume.
    """
    return status == "no_bytes"
