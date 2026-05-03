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
from judex.pipeline.sessions import RotatingSession
from judex.pipeline.state import PipelineState

if TYPE_CHECKING:
    from judex.scraping.proxy_pool import ProxyPool


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
    portal_proxies: Optional["ProxyPool"] = None,
    sistemas_proxies: Optional["ProxyPool"] = None,
) -> dict[str, HandlerFn]:
    """Build the three real handlers bound to a live ``PipelineState``.

    ``source_dir`` is where ``handle_fetch_meta`` writes case JSONs.
    Defaults to ``data/source/processos`` (the canonical path in
    ``CLAUDE.md § data-layout``); per-case files land at
    ``<source_dir>/<classe>/judex-mini_<classe>_<n>-<n>.json``.

    ``portal_proxies`` / ``sistemas_proxies`` are independent
    :class:`ProxyPool` references (typically two pools loaded from the
    same flat file — independent so portal-WAF cooldowns don't leak
    into sistemas state and vice versa). When ``None``, the
    corresponding handler runs direct-IP. See
    :class:`judex.pipeline.sessions.RotatingSession`.

    Imports are deferred to keep ``judex.pipeline`` importable without
    the full scrape stack (so unit tests can mock instead of pulling
    requests / OCR modules).
    """
    import json
    from pathlib import Path
    from judex.scraping import scraper as _scraper
    from judex.scraping.http_session import _http_get_with_retry
    from judex.scraping.ocr import dispatch as ocr_dispatch
    from judex.scraping.ocr.base import OCRConfig
    from judex.sweeps.peca_classification import filter_substantive
    from judex.sweeps.peca_targets import _iter_case_pdf_targets
    from judex.utils import peca_cache
    from judex.utils.peca_utils import extract_rtf_text

    portal_holder = RotatingSession(portal_proxies)
    sistemas_holder = RotatingSession(sistemas_proxies)
    # Under ``--provedor auto`` the OCRConfig is built per-target inside
    # ``handle_extract_text`` (the router decides on doc_type); for
    # single-provider runs we pre-build once and re-use. Mirrors the
    # legacy fork in ``extrair_pecas.run_extract_pecas``.
    ocr_config: Optional["OCRConfig"]
    if provedor == "auto":
        ocr_config = None
    else:
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
                classe, processo, session=portal_holder.session(), fetch_dje=fetch_dje
            )
        except _scraper.NoIncidenteError:
            state.record_meta(task.case_key, status="unallocated_pid")
            return []
        except Exception as exc:  # noqa: BLE001
            portal_holder.report_failure(exc)
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
        # Dedup by URL: ``_iter_case_pdf_targets`` does NOT dedupe
        # within a case (per its docstring), so the same peça URL can
        # appear via multiple surfaces (e.g., once on an andamento.link
        # and again as a DJe decisao.rtf for the same document). Without
        # dedup the scheduler emits redundant fetch_bytes tasks; the
        # second hits ``peca_cache.has_bytes`` → True → skip, so the
        # cost is bookkeeping noise (sistemas.started inflated, state
        # writes wasted), not real WAF spend. The 50-case validation
        # surfaced 3 dupes / 119 tasks (~2.5%); fixing here keeps
        # report.md counters honest.
        targets = list({t.url: t for t in targets}.values())
        # Carry ``doc_type`` forward in the Task payload — needed by
        # ``--provedor auto``'s per-target router (and persisted into
        # the bytes record by ``handle_fetch_bytes`` so resume
        # preserves the routing decision).
        return [
            Task(
                kind="fetch_bytes",
                pool="sistemas",
                payload={"url": t.url, "doc_type": t.doc_type},
                case_key=task.case_key,
            )
            for t in targets
        ]

    def handle_fetch_bytes(task: Task) -> list[Task]:
        url = task.payload["url"]
        doc_type = task.payload.get("doc_type")

        if peca_cache.has_bytes(url):
            state.record_bytes(task.case_key, url=url, status="ok", doc_type=doc_type)
            return [
                Task(
                    kind="extract_text",
                    pool="ocr",
                    payload={"url": url, "doc_type": doc_type},
                    case_key=task.case_key,
                )
            ]

        try:
            r = _http_get_with_retry(sistemas_holder.session(), url, timeout=60)
        except Exception as exc:  # noqa: BLE001
            sistemas_holder.report_failure(exc)
            status, msg = _classify_http_exception(exc)
            state.record_bytes(
                task.case_key, url=url, status=status, error=msg, doc_type=doc_type,
            )
            return []

        try:
            peca_cache.write_bytes(url, r.content)
        except ValueError as exc:
            # Unsupported magic bytes — treat as terminal.
            state.record_bytes(
                task.case_key, url=url, status="empty", error=str(exc),
                doc_type=doc_type,
            )
            return []

        state.record_bytes(task.case_key, url=url, status="ok", doc_type=doc_type)
        return [
            Task(
                kind="extract_text",
                pool="ocr",
                payload={"url": url, "doc_type": doc_type},
                case_key=task.case_key,
            )
        ]

    def handle_extract_text(task: Task) -> list[Task]:
        url = task.payload["url"]
        doc_type = task.payload.get("doc_type")
        body = peca_cache.read_bytes(url)
        if not body:
            state.record_text(
                task.case_key,
                url=url,
                status="no_bytes",
                error="cache miss; run fetch_bytes first",
            )
            return []

        # RTF bypass: structured-text payload, parsed instantly with
        # striprtf — no OCR cost, no provider involvement. Same magic-
        # byte sniff legacy ``extract_driver._detect_bytes_type`` uses.
        # Without this branch, pypdf chokes on ``{\\rtf`` and records
        # ``provider_error`` for ~14% of HC 2020-era text URLs (the DJe
        # decisao.rtf surface).
        if body[:5] == b"{\\rtf":
            try:
                rtf_text = extract_rtf_text(body) or ""
            except Exception as exc:  # noqa: BLE001
                state.record_text(
                    task.case_key,
                    url=url,
                    status="provider_error",
                    extractor="rtf",
                    error=f"{type(exc).__name__}: {exc}",
                )
                return []
            if not rtf_text.strip():
                state.record_text(
                    task.case_key, url=url, status="empty", extractor="rtf"
                )
                return []
            peca_cache.write(url, rtf_text, extractor="rtf")
            state.record_text(task.case_key, url=url, status="ok", extractor="rtf")
            return []

        # Resolve the effective provider for THIS target. Under
        # ``--provedor auto`` the router (lifted from legacy
        # ``extrair_pecas.pick_provider``) routes ACÓRDÃO doc_types to
        # tesseract (or whatever ``JUDEX_AUTO_TESSERACT_PROVIDER`` says)
        # and everything else to pypdf — same policy as the legacy
        # `extrair-pecas --provedor auto` chain. For single-provider
        # runs the pre-built ``ocr_config`` is reused unchanged.
        if provedor == "auto":
            from judex.sweeps.extrair_pecas import pick_provider
            effective_provedor = pick_provider(doc_type)
            effective_config = OCRConfig(provider=effective_provedor)
        else:
            effective_provedor = provedor
            effective_config = ocr_config  # type: ignore[assignment]

        try:
            result = ocr_dispatch.extract_pdf(body, effective_config)
        except Exception as exc:  # noqa: BLE001
            state.record_text(
                task.case_key,
                url=url,
                status="provider_error",
                extractor=effective_provedor,
                error=f"{type(exc).__name__}: {exc}",
            )
            return []

        if not result.text or not result.text.strip():
            state.record_text(
                task.case_key,
                url=url,
                status="empty",
                extractor=effective_provedor,
            )
            return []

        peca_cache.write(url, result.text, extractor=effective_provedor)
        if result.elements is not None:
            peca_cache.write_elements(url, result.elements)
        state.record_text(
            task.case_key, url=url, status="ok", extractor=effective_provedor,
        )
        return []

    return {
        "fetch_meta": handle_fetch_meta,
        "fetch_bytes": handle_fetch_bytes,
        "extract_text": handle_extract_text,
    }
