"""Real handlers for the unified pipeline.

Each handler is a sync function (the existing library code is sync;
the scheduler bridges via ``asyncio.to_thread``). On every outcome
the handler records to ``PipelineState`` so resume semantics are
correct after a crash.

Handler contract:

* Input: a :class:`Task` plus context (state, sessions, ocr config).
* Side effect: write to disk (case JSON, peça bytes, peça text).
* Side effect: record to ``state``.
* Return: list of follow-up tasks (possibly empty). Errors do NOT
  raise — they are caught, recorded as a status, and swallowed.
  The scheduler trusts handlers to never raise.

The handlers are constructed by ``make_handlers(state, ...)`` so the
scheduler can hold a single ``handlers: dict[TaskKind, HandlerFn]``
and dispatch by ``task.kind``. Tests can substitute mock handlers
through the same factory shape.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from judex.pipeline.models import Task, TaskStatus
from judex.pipeline.state import PipelineState


log = logging.getLogger(__name__)


HandlerFn = Callable[[Task], list[Task]]
"""Sync handler: takes a Task, returns 0..N successor tasks. Never
raises — all error outcomes are recorded to state and the empty list
is returned (or a forced-skip list, depending on whether downstream
work makes sense given the failure)."""


def _classify_http_exception(exc: BaseException) -> tuple[TaskStatus, str]:
    """Map an HTTP-side exception to a (status, error_message) pair.

    Mirrors ``judex.sweeps.shared.classify_exception`` semantics but
    keeps the dependency surface small. A future deepening can reuse
    that module directly.
    """
    from judex.sweeps.shared import classify_exception

    kind, http_status, _ = classify_exception(exc)
    if kind == "unallocated_pid":
        return ("unallocated_pid", "processo_id não alocado")
    if kind in ("waf_403", "http_error", "timeout", "ssl_error", "connection_error"):
        msg = f"{kind}"
        if http_status:
            msg = f"{kind} (http={http_status})"
        return ("http_error", msg)
    return ("http_error", f"{type(exc).__name__}: {exc}")


def make_handlers(
    state: PipelineState,
    *,
    provedor: str = "pypdf",
    fetch_dje: bool = True,
    source_dir: Optional["Path"] = None,
) -> dict[str, HandlerFn]:
    """Build the three real handlers bound to a live ``PipelineState``.

    ``source_dir`` is where ``handle_fetch_meta`` writes case JSONs.
    Defaults to ``data/source/processos`` (the canonical path in
    ``CLAUDE.md § data-layout``); per-case files land at
    ``<source_dir>/<classe>/judex-mini_<classe>_<n>-<n>.json``.

    Imports are deferred to keep ``judex.pipeline`` importable without
    the full scrape stack (so unit tests can mock instead of pulling
    requests / OCR modules).
    """
    import json
    from pathlib import Path
    from judex.scraping import scraper as _scraper
    from judex.scraping.http_session import _http_get_with_retry, new_session
    from judex.scraping.ocr import dispatch as ocr_dispatch
    from judex.scraping.ocr.base import OCRConfig
    from judex.sweeps.peca_classification import filter_substantive
    from judex.sweeps.peca_targets import _iter_case_pdf_targets
    from judex.utils import peca_cache

    portal_session = new_session()
    sistemas_session = new_session()
    ocr_config = OCRConfig(provider=provedor)

    items_root = Path(source_dir) if source_dir else Path("data/source/processos")

    def _write_case_json(classe: str, processo: int, item: dict) -> None:
        """Atomic write matching ``run_sweep._write_item_json``.

        Lift-and-replicate (not import) because run_sweep's helper is
        private and shape-coupled to the legacy run-state machinery;
        the disk-format contract is the part we want to share.
        """
        out_dir = items_root / classe
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"judex-mini_{classe}_{processo}-{processo}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(item, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    def handle_fetch_meta(task: Task) -> list[Task]:
        classe, processo = task.case_key
        try:
            item = _scraper.scrape_processo_http(
                classe, processo, session=portal_session, fetch_dje=fetch_dje
            )
        except _scraper.NoIncidenteError:
            state.record_meta(task.case_key, status="unallocated_pid")
            return []
        except Exception as exc:  # noqa: BLE001
            status, msg = _classify_http_exception(exc)
            state.record_meta(task.case_key, status=status, error=msg)
            return []

        # Persist the case JSON to disk. This is what the legacy
        # ``varrer-processos`` does via run_sweep._write_item_json;
        # without it, downstream consumers (warehouse rebuild,
        # validar-gabarito, ad-hoc analysis) don't see the case.
        try:
            _write_case_json(classe, processo, dict(item))
        except Exception as exc:  # noqa: BLE001
            state.record_meta(task.case_key, status="http_error",
                              error=f"write failed: {exc}")
            return []

        state.record_meta(task.case_key, status="ok")

        targets = list(_iter_case_pdf_targets(dict(item)))
        targets = filter_substantive(targets)
        return [
            Task(
                kind="fetch_bytes",
                pool="sistemas",
                payload={"url": t.url},
                case_key=task.case_key,
            )
            for t in targets
        ]

    def handle_fetch_bytes(task: Task) -> list[Task]:
        url = task.payload["url"]

        if peca_cache.has_bytes(url):
            state.record_bytes(task.case_key, url=url, status="ok")
            return [
                Task(
                    kind="extract_text",
                    pool="ocr",
                    payload={"url": url},
                    case_key=task.case_key,
                )
            ]

        try:
            r = _http_get_with_retry(sistemas_session, url, timeout=60)
        except Exception as exc:  # noqa: BLE001
            status, msg = _classify_http_exception(exc)
            state.record_bytes(task.case_key, url=url, status=status, error=msg)
            return []

        try:
            peca_cache.write_bytes(url, r.content)
        except ValueError as exc:
            # Unsupported magic bytes — treat as terminal.
            state.record_bytes(task.case_key, url=url, status="empty", error=str(exc))
            return []

        state.record_bytes(task.case_key, url=url, status="ok")
        return [
            Task(
                kind="extract_text",
                pool="ocr",
                payload={"url": url},
                case_key=task.case_key,
            )
        ]

    def handle_extract_text(task: Task) -> list[Task]:
        url = task.payload["url"]
        body = peca_cache.read_bytes(url)
        if not body:
            state.record_text(
                task.case_key,
                url=url,
                status="no_bytes",
                error="cache miss; run fetch_bytes first",
            )
            return []

        try:
            result = ocr_dispatch.extract_pdf(body, ocr_config)
        except Exception as exc:  # noqa: BLE001
            state.record_text(
                task.case_key,
                url=url,
                status="provider_error",
                extractor=provedor,
                error=f"{type(exc).__name__}: {exc}",
            )
            return []

        if not result.text or not result.text.strip():
            state.record_text(
                task.case_key,
                url=url,
                status="empty",
                extractor=provedor,
            )
            return []

        peca_cache.write(url, result.text, extractor=provedor)
        if result.elements is not None:
            peca_cache.write_elements(url, result.elements)
        state.record_text(task.case_key, url=url, status="ok", extractor=provedor)
        return []

    return {
        "fetch_meta": handle_fetch_meta,
        "fetch_bytes": handle_fetch_bytes,
        "extract_text": handle_extract_text,
    }
