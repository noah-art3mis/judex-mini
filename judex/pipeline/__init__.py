"""Unified pipeline: a single fire-and-forget runtime that replaces the
three-command chain (`varrer-processos` + `baixar-pecas` + `extrair-pecas`)
and `coletar`'s multi-substage orchestrator with one process driving
three asyncio worker pools (`portal`, `sistemas`, `ocr`).

See ``docs/superpowers/specs/2026-05-02-unified-pipeline.md`` for the
design and the six-point ergonomic success checklist.

Public API stabilises in slice 4 (when ``judex executar`` lands in
``judex/cli.py``); for now this package exposes its internals so
tests can pin the contracts that the runtime depends on.
"""

from judex.pipeline.models import (
    PoolName,
    TaskKind,
    TaskStatus,
    Task,
    PoolConfig,
    Counters,
)
from judex.pipeline.state import PipelineState, CaseRecord

__all__ = [
    "PoolName",
    "TaskKind",
    "TaskStatus",
    "Task",
    "PoolConfig",
    "Counters",
    "PipelineState",
    "CaseRecord",
]
