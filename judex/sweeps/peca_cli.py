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


# Rough anchors used by the preview. The ~2 MB/PDF and ~5 pg/PDF numbers
# are order-of-magnitude — precise wall/disk come from post-run reports.
_AVG_PDF_MB = 2.0
_AVG_PAGES_PER_PDF = 5

# Baked-in throttle used by the download driver. The preview estimates wall
# time against this value; if `download_driver` ever changes its default,
# update this constant to match.
_THROTTLE_SLEEP_S = 2.0


# ----- Input-mode resolver --------------------------------------------------


def resolve_targets(args: argparse.Namespace) -> tuple[list[PecaTarget], str]:
    """Return `(targets, mode_label)` per spec's input-mode priority.

    Priority: `--retentar-de` > `--csv` > range (`-c` + `-i`/`-f`) >
    filter fallback. The label is human-readable for the preview
    block ("retry foo", "csv alvos.csv", "range HC 100-200", "filtros").
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

    # Filter fallback.
    roots = _default_roots(args)
    targets = collect_peca_targets(
        roots,
        classe=classe,
        impte_contains=split_csv(getattr(args, "impte_contem", "") or ""),
        doc_types=split_csv(getattr(args, "tipos_doc", "") or ""),
        relator_contains=split_csv(getattr(args, "relator_contem", "") or ""),
        exclude_doc_types=split_csv(getattr(args, "excluir_tipos_doc", "") or ""),
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
    """Baixar-pdfs preview: bytes-cache split + disk / wall estimates."""
    already = sum(1 for t in targets if peca_cache.has_bytes(t.url))
    to_download = len(targets) - already
    n_procs = len({t.processo_id for t in targets if t.processo_id is not None})
    space_mb = to_download * _AVG_PDF_MB
    # Wall: pure HTTP + sleep per target. ~1s HTTP + _THROTTLE_SLEEP_S.
    wall_s = to_download * (1.0 + _THROTTLE_SLEEP_S)

    lines = [
        f"targets: {len(targets)} PDFs across {n_procs} processes (modo: {mode_label})",
        f"já em disco (pulados):   {already:>6d}",
        f"a baixar:               {to_download:>6d}",
        f"espaço estimado:     ~{space_mb:>6.0f} MB (at ~{_AVG_PDF_MB:.1f} MB/PDF)",
        f"tempo estimado:      ~{wall_s / 60:>6.1f} min "
        f"(at ~{_THROTTLE_SLEEP_S:.1f}s/req throttle + HTTP)",
        "",
    ]
    stream.write("\n".join(lines))


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
    n_pages = to_extract * _AVG_PAGES_PER_PDF
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
