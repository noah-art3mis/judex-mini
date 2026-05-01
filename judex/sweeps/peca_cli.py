"""Shared CLI scaffolding for `baixar-pecas` + `extrair-pecas`.

Input-mode resolver (retry > csv > range > filter), TTY-aware
confirmation prompt, and the two preview printers. Kept here so both
scripts stay thin; tests hit this module directly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TextIO

from judex.scraping.ocr.dispatch import estimate_cost, estimate_wall
from judex.sweeps.peca_targets import (
    PecaTarget,
    collect_peca_targets,
    targets_from_csv,
    targets_from_errors_jsonl,
    targets_from_range,
)
from judex.utils import peca_cache
from judex.utils.filters import split_csv


# Pages-per-PDF anchor for the extract preview. Re-measured 2026-04-29
# from a pypdf sample of 1,904 cached PDFs: mean 4.90, median 3, p90 12,
# p99 22. The download anchors live in `judex/utils/cost.py` (the
# download preview defers to that module's forecast table).
_AVG_PAGES_PER_PDF = 4.9


# ----- Input-mode resolver --------------------------------------------------


def resolve_targets(args: argparse.Namespace) -> tuple[list[PecaTarget], str]:
    """Return `(targets, mode_label)` per spec's input-mode priority.

    Priority: `--retentar-de` > `--csv` > range (`-c` + `-i`/`-f`) >
    filter fallback. The label is human-readable for the preview
    block ("retry foo", "csv alvos.csv", "range HC 100-200", "filtros").

    Bare invocation (none of the four modes specified) raises
    ``ValueError``. Walking the entire corpus is a perf-cliff
    footgun: `pdfs.state.json` atomic-rewrites cap downstream
    throughput at ~0.13 rec/s on WSL2, putting a 120k-record extract
    at ~9 days. The caller must always opt into a scope.
    """
    if getattr(args, "retentar_de", None):
        path = Path(args.retentar_de)
        return targets_from_errors_jsonl(path), f"retry {path.name}"

    if getattr(args, "csv", None):
        path = Path(args.csv)
        roots = _default_roots(args)
        return targets_from_csv(path, roots=roots), f"csv {path.name}"

    classe = getattr(args, "classe", None)
    inicio = getattr(args, "inicio", None)
    fim = getattr(args, "fim", None)
    if classe and (inicio is not None or fim is not None):
        ini = inicio if inicio is not None else fim
        end = fim if fim is not None else inicio
        roots = _default_roots(args)
        return (
            targets_from_range(classe, ini, end, roots=roots),
            f"range {classe} {ini}-{end}",
        )

    impte_contains = split_csv(getattr(args, "impte_contem", "") or "")
    doc_types = split_csv(getattr(args, "tipos_doc", "") or "")
    relator_contains = split_csv(getattr(args, "relator_contem", "") or "")
    exclude_doc_types = split_csv(
        getattr(args, "excluir_tipos_doc", "") or ""
    )
    has_filter = bool(
        classe or impte_contains or doc_types
        or relator_contains or exclude_doc_types
    )
    if not has_filter:
        raise ValueError(
            "scope required: pass --retentar-de, --csv, range "
            "(-c CLASSE -i N -f M), or at least one filter "
            "(--classe / --impte-contem / --tipos-doc / "
            "--relator-contem / --excluir-tipos-doc). Bare "
            "invocation walks the full corpus and is structurally "
            "too slow (atomic state-write floor → ~0.13 rec/s, days "
            "for what should be minutes). See CLAUDE.md § Non-obvious "
            "gotchas."
        )

    roots = _default_roots(args)
    targets = collect_peca_targets(
        roots,
        classe=classe,
        impte_contains=impte_contains,
        doc_types=doc_types,
        relator_contains=relator_contains,
        exclude_doc_types=exclude_doc_types,
    )
    return targets, "filtros"


def _default_roots(args: argparse.Namespace) -> list[Path]:
    roots = getattr(args, "roots", None) or []
    if roots:
        return [Path(r) for r in roots]
    return [Path("data/source/processos")]


# ----- Confirm / non-TTY fail-closed ---------------------------------------


def confirm_or_exit(nao_perguntar: bool) -> None:
    """Block until the user confirms, or fail-closed on non-TTY.

    - `nao_perguntar=True` → proceed silently.
    - TTY, answer ∈ {s, sim, y, yes} → proceed.
    - TTY, anything else            → exit(0), "cancelado."
    - Non-TTY, no `--nao-perguntar` → exit(2), guardrail message.
    """
    if nao_perguntar:
        return
    if not sys.stdin.isatty():
        sys.stderr.write(
            "error: stdin is not a TTY; use --nao-perguntar "
            "for unattended runs.\n",
        )
        sys.exit(2)
    sys.stdout.write("Prosseguir? [s/N] ")
    sys.stdout.flush()
    answer = sys.stdin.readline().strip().lower()
    if answer not in {"s", "sim", "y", "yes"}:
        print("cancelado.")
        sys.exit(0)


# ----- Preview printers ----------------------------------------------------


def print_download_preview(
    targets: list[PecaTarget], *,
    mode_label: str,
    stream: TextIO = sys.stdout,
) -> None:
    """Baixar-pdfs preview: bytes-cache split + side-by-side cost/wall
    forecast for single direct-IP and 16-shard + proxy modes.

    Math + anchors live in `judex.utils.cost`; this function is the
    renderer.
    """
    from judex.utils.cost import (
        forecast_baixar_pecas,
        render_forecast_table,
    )

    already = sum(1 for t in targets if peca_cache.has_bytes(t.url))
    to_download = len(targets) - already
    n_procs = len({t.processo_id for t in targets if t.processo_id is not None})

    lines = [
        f"targets: {len(targets)} PDFs across {n_procs} processes (modo: {mode_label})",
        f"já em disco (pulados):   {already:>6d}",
        f"a baixar:               {to_download:>6d}",
        "",
    ]
    stream.write("\n".join(lines))
    forecasts = forecast_baixar_pecas(to_download)
    stream.write(render_forecast_table(
        forecasts, n_units=to_download, unit_label="PDFs"
    ))
    stream.write("\n")


def print_extract_preview(
    targets: list[PecaTarget], *,
    mode_label: str,
    provedor: str,
    stream: TextIO = sys.stdout,
) -> None:
    """Extrair-pdfs preview: 3-way split (cached-by-provedor, no-bytes,
    to-extract) + cost/wall estimates keyed on `--provedor`.
    """
    cached = 0
    no_bytes = 0
    for t in targets:
        if not peca_cache.has_bytes(t.url):
            no_bytes += 1
            continue
        if (
            peca_cache.read_extractor(t.url) == provedor
            and peca_cache.read(t.url) is not None
        ):
            cached += 1
    to_extract = len(targets) - cached - no_bytes
    n_procs = len({t.processo_id for t in targets if t.processo_id is not None})
    n_pages = int(to_extract * _AVG_PAGES_PER_PDF)
    cost = estimate_cost(provedor, n_pages) if provedor else 0.0
    wall_s = estimate_wall(provedor, to_extract) if provedor else 0.0

    lines = [
        f"targets: {len(targets)} PDFs across {n_procs} processes (modo: {mode_label})",
        f"já extraídos por {provedor} (pulados): {cached:>6d}",
        f"sem bytes locais (falharão):         {no_bytes:>6d}",
        f"a extrair:                           {to_extract:>6d}",
        f"páginas estimadas (~{_AVG_PAGES_PER_PDF} pg/PDF): {n_pages:>6d}",
        "",
        f"provedor: {provedor} (sync)",
        f"custo estimado:  ${cost:>6.2f}",
        f"tempo estimado:  ~{wall_s / 60:>6.1f} min",
        "",
    ]
    stream.write("\n".join(lines))
