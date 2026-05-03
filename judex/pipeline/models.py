"""Data types for the unified pipeline.

These are intentionally small. The scheduler uses them as routing tags
and the state-store uses them as keys; nothing here implements
behaviour. Behaviour lives in ``scheduler.py``, ``handlers.py``, and
``state.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


PoolName = Literal["portal", "sistemas", "ocr"]
"""Worker-pool identifier. Each pool has its own concurrency, throttle,
breaker, and (for portal/sistemas) proxy posture."""


TaskKind = Literal["fetch_meta", "fetch_bytes", "extract_text"]
"""The three task types of the per-case DAG.

* ``fetch_meta`` runs on ``portal``; emits one ``fetch_bytes`` per peça URL.
* ``fetch_bytes`` runs on ``sistemas``; emits one ``extract_text``.
* ``extract_text`` runs on ``ocr``; terminal.
"""


TaskStatus = Literal[
    "pending",
    "running",
    "ok",
    "http_error",
    "provider_error",
    "no_bytes",
    "empty",
    "unallocated_pid",
    "skipped_cached",
]
"""Per-task outcome vocabulary. Mirrors ``judex/sweeps/peca_store.py``
and ``judex/sweeps/process_store.py`` so ``error_triage.classify_error``
is reusable across stages without translation."""


@dataclass(frozen=True)
class Task:
    """One unit of work routed to one pool.

    Frozen because tasks flow through queues; mutating after enqueue
    would race with worker dequeue.
    """

    kind: TaskKind
    pool: PoolName
    case_key: tuple[str, int]  # (classe, processo_id)
    payload: dict = field(default_factory=dict, hash=False, compare=False)

    @property
    def id(self) -> str:
        """Stable identifier used as the state-store key for non-meta tasks.

        ``fetch_meta`` is keyed by case (one per case); ``fetch_bytes``
        and ``extract_text`` are keyed by URL (or sha1, depending on
        what the payload carries). Callers that need a unique
        per-task id should compose ``(kind, case_key, payload_id)``
        themselves — this property is a convenience for logging.
        """
        if self.kind == "fetch_meta":
            return f"fetch_meta:{self.case_key[0]}-{self.case_key[1]}"
        url = self.payload.get("url", "?")
        return f"{self.kind}:{url}"


@dataclass
class PoolConfig:
    """Per-pool runtime configuration.

    Concurrency and pacing knobs only; the actual pool runtime
    (semaphore, throttle, breaker, proxy pool) is constructed by
    ``scheduler.py`` from this config.
    """

    name: PoolName
    concurrency: int = 1
    proxy_pool_path: str | None = None
    throttle_max_delay: float = 60.0
    circuit_window: int = 50
    circuit_threshold: float = 0.8


@dataclass
class Counters:
    """Per-pool live counters for progress reporting.

    Mutable; the scheduler updates these in place. ``busy_seconds`` is
    measured *inside* the semaphore — i.e., real handler time, not
    queue wait. Pool utilisation is ``busy_seconds / wall_seconds``.
    """

    started: int = 0
    finished: int = 0
    failed: int = 0
    skipped: int = 0
    busy_seconds: float = 0.0
