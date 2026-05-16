"""Pin the single source of truth for "is this failure retryable?".

Two call sites historically had their own copy of the policy:

- :func:`judex.pipeline.scheduler._is_retryable_status` decides whether
  the live scheduler's seed-builder re-enqueues a task on resume.
- :func:`judex.pipeline.log.classify_unified_error` decides whether
  ``recuperar`` puts a state.json row into the REPLAY bucket and
  whether ``--retentar-de`` admits it as a target.

The two drifted: ``classify_unified_error`` knew that
``(fetch_bytes, empty)`` is a WAF/LB flake (HC 271343 evidence,
``hc-atualizar-20260503``), but ``_is_retryable_status`` did not.
``recuperar --apply`` therefore dispatched the row, the child runner's
seed-builder filtered it out, the child exited with zero work, and the
operator-facing residual never shrank. This test pins the equivalence
so the two cannot drift again.
"""

from __future__ import annotations

import pytest

from judex.pipeline.log import classify_unified_error
from judex.pipeline.recovery_policy import (
    RETRY_CAP,
    is_cross_stage_status,
    is_retryable_status,
)
from judex.pipeline.scheduler import _is_retryable_status


# Every (kind, status) pair the unified pipeline emits — extend when
# new TaskStatus values land. Three kinds × the union of statuses each
# stage can record per ``judex.pipeline.models.TaskStatus``.
_KINDS = ("fetch_meta", "fetch_bytes", "extract_text")
_STATUSES = (
    "ok", "skipped_cached",
    "http_error", "provider_error",
    "empty", "no_bytes",
    "unallocated_pid",
)


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("status", _STATUSES)
def test_predicate_agrees_with_classifier(kind: str, status: str) -> None:
    """``is_retryable_status(kind, status)`` is True iff
    ``classify_unified_error({"kind": kind, "status": status}) ==
    "transient"``. Anything else (ok / cross_stage / terminal) maps to
    False on the predicate side.

    This is the structural equivalence the two call sites need. If a
    future deepening adds a new status that should be transient, only
    one place needs to learn it.
    """
    classified = classify_unified_error({"kind": kind, "status": status})
    assert (classified == "transient") == is_retryable_status(kind, status)


@pytest.mark.parametrize("status", _STATUSES)
def test_cross_stage_predicate_matches_classifier(status: str) -> None:
    """``no_bytes`` is the only status the unified pipeline routes to
    ``cross_stage`` today; the predicate must agree."""
    classified = classify_unified_error({"kind": "extract_text", "status": status})
    assert (classified == "cross_stage") == is_cross_stage_status(status)


def test_scheduler_wrapper_honours_predicate() -> None:
    """``_is_retryable_status`` adds a retry-count cap on top of
    ``is_retryable_status``. Below the cap the two must agree on every
    retryable case; at or above the cap the wrapper must return False
    even when the underlying predicate would say True. This is the
    contract the seed-builder relies on.
    """
    for kind in _KINDS:
        for status in _STATUSES:
            base = is_retryable_status(kind, status)
            assert _is_retryable_status(kind, status, retry_count=0) is base
            if base:
                assert _is_retryable_status(
                    kind, status, retry_count=RETRY_CAP - 1,
                ) is True
                assert _is_retryable_status(
                    kind, status, retry_count=RETRY_CAP,
                ) is False


def test_retry_cap_is_two() -> None:
    """ADR-0004's "cap of 2 retry cycles per stage" contract — pinned so
    a refactor that moved the constant doesn't silently change its
    value."""
    assert RETRY_CAP == 2


def test_fetch_bytes_empty_is_retryable() -> None:
    """The historical drift case: ``(fetch_bytes, empty)`` is a 0-byte
    STF response (WAF/LB flake) and must be retryable on both sides.
    Pinned by HC 271343 in ``runs/active/hc-atualizar-20260503``. Before
    the recovery_policy extraction this assertion failed against the
    scheduler — it returned False, so ``recuperar --apply`` dispatches
    were silent no-ops."""
    assert is_retryable_status("fetch_bytes", "empty") is True
    assert classify_unified_error(
        {"kind": "fetch_bytes", "status": "empty"}
    ) == "transient"
    assert _is_retryable_status("fetch_bytes", "empty", retry_count=0) is True


def test_extract_text_empty_is_terminal() -> None:
    """Symmetric counterpart: ``(extract_text, empty)`` means the
    provider returned 0 chars after running; same provider would give
    same result. Recovery is a provider switch (``recuperar`` routes it
    to PROVIDER_SWITCH), not a replay. Both sides must say "not
    retryable" so the seed-builder doesn't burn the OCR pool on a
    deterministic-empty extract."""
    assert is_retryable_status("extract_text", "empty") is False
    assert classify_unified_error(
        {"kind": "extract_text", "status": "empty"}
    ) == "terminal"
