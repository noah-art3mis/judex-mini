"""Shared CLI scaffolding for `baixar-pecas` + `extrair-pecas`.

Input-mode resolver (retry > csv > range > filter), TTY-aware
confirmation prompt, and the two preview printers. Kept here so both
scripts stay thin; tests hit this module directly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence, TextIO

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


def resolve_targets(
    *,
    retentar_de: Path | None = None,
    csv: Path | None = None,
    classe: str | None = None,
    inicio: int | None = None,
    fim: int | None = None,
    impte_contem: str = "",
    tipos_doc: str = "",
    relator_contem: str = "",
    excluir_tipos_doc: str = "",
    roots: Sequence[Path] | None = None,
) -> tuple[list[PecaTarget], str]:
    """Return `(targets, mode_label)` per spec's input-mode priority.

    Priority: ``retentar_de`` > ``csv`` > range (``classe`` + ``inicio``/``fim``)
    > filter fallback. The label is human-readable for the preview block
    ("retry foo", "csv alvos.csv", "range HC 100-200", "filtros").

    Bare invocation (none of the four modes specified) raises
    ``ValueError``. Walking the entire corpus is a perf-cliff
    footgun: `pdfs.state.json` atomic-rewrites cap downstream
    throughput at ~0.13 rec/s on WSL2, putting a 120k-record extract
    at ~9 days. The caller must always opt into a scope.
    """
    if retentar_de:
        path = Path(retentar_de)
        return targets_from_errors_jsonl(path), f"retry {path.name}"

    if csv:
        path = Path(csv)
        return targets_from_csv(path, roots=_default_roots(roots)), f"csv {path.name}"

    if classe and (inicio is not None or fim is not None):
        ini = inicio if inicio is not None else fim
        end = fim if fim is not None else inicio
        return (
            targets_from_range(classe, ini, end, roots=_default_roots(roots)),
            f"range {classe} {ini}-{end}",
        )

    impte_contains = split_csv(impte_contem or "")
    doc_types = split_csv(tipos_doc or "")
    relator_contains = split_csv(relator_contem or "")
    exclude_doc_types = split_csv(excluir_tipos_doc or "")
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

    targets = collect_peca_targets(
        _default_roots(roots),
        classe=classe,
        impte_contains=impte_contains,
        doc_types=doc_types,
        relator_contains=relator_contains,
        exclude_doc_types=exclude_doc_types,
    )
    return targets, "filtros"


def _default_roots(roots: Sequence[Path] | None) -> list[Path]:
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
    from judex.utils.cli_render import render_kv_block
    from judex.utils.cost import (
        forecast_baixar_pecas,
        render_forecast_table,
    )

    already = sum(1 for t in targets if peca_cache.has_bytes(t.url))
    to_download = len(targets) - already
    n_procs = len({t.processo_id for t in targets if t.processo_id is not None})

    render_kv_block(
        f"targets · {len(targets):,} PDFs across {n_procs:,} processes",
        [
            ("já em disco (pulados)", f"{already:,}"),
            ("a baixar", f"{to_download:,}"),
        ],
        subtitle=f"modo: {mode_label}",
        stream=stream,
    )
    stream.write(render_forecast_table(
        forecast_baixar_pecas(to_download),
        n_units=to_download, unit_label="PDFs",
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

    For ``--provedor auto``, the cached-match check and the cost/wall
    estimates are computed per-target via the same router the runtime
    uses, so the preview reflects the actual heterogeneous workload.
    """
    from judex.utils.cli_render import render_kv_block

    if provedor == "auto":
        from judex.sweeps.extrair_pecas import pick_provider
        per_target_provider = pick_provider
    else:
        per_target_provider = lambda _t, _p=provedor: _p

    cached = 0
    no_bytes = 0
    to_extract_by_provider: dict[str, int] = {}
    for t in targets:
        if not peca_cache.has_bytes(t.url):
            no_bytes += 1
            continue
        target_provedor = per_target_provider(t)
        if (
            peca_cache.read_extractor(t.url) == target_provedor
            and peca_cache.read(t.url) is not None
        ):
            cached += 1
        else:
            to_extract_by_provider[target_provedor] = (
                to_extract_by_provider.get(target_provedor, 0) + 1
            )
    to_extract = sum(to_extract_by_provider.values())
    n_procs = len({t.processo_id for t in targets if t.processo_id is not None})
    n_pages = int(to_extract * _AVG_PAGES_PER_PDF)

    # Per-provider cost/wall, summed across whatever providers the run
    # actually exercises. `auto` typically picks pypdf+tesseract — both
    # free / local — so total cost is $0 and total wall is dominated by
    # the tesseract subset.
    total_cost = 0.0
    total_wall_s = 0.0
    for prov, n in to_extract_by_provider.items():
        if prov:
            total_cost += estimate_cost(prov, int(n * _AVG_PAGES_PER_PDF))
            total_wall_s += estimate_wall(prov, n)

    render_kv_block(
        f"targets · {len(targets):,} PDFs across {n_procs:,} processes",
        [
            (f"já extraídos por {provedor} (pulados)", f"{cached:,}"),
            ("sem bytes locais (falharão)", f"{no_bytes:,}"),
            ("a extrair", f"{to_extract:,}"),
            (f"páginas estimadas (~{_AVG_PAGES_PER_PDF} pg/PDF)", f"{n_pages:,}"),
        ],
        subtitle=f"modo: {mode_label}",
        stream=stream,
    )

    forecast_rows: list[tuple[str, str]] = [("provedor", f"{provedor} (sync)")]
    if provedor == "auto" and to_extract_by_provider:
        breakdown = ", ".join(
            f"{p}={n:,}" for p, n in sorted(to_extract_by_provider.items())
        )
        forecast_rows.append(("rota auto", breakdown))
    forecast_rows += [
        ("custo estimado", f"${total_cost:,.2f}"),
        ("tempo estimado", f"~{total_wall_s / 60:,.1f} min"),
    ]
    render_kv_block(
        "forecast",
        forecast_rows,
        stream=stream,
    )
    stream.write("\n")
