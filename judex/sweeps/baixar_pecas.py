"""Download STF PDFs to the local bytes cache.

The WAF-bound half of the PDF pipeline: fetches `PecaTarget.url` from
STF and writes raw bytes to ``data/raw/pecas/<sha1>.<ext>.gz``.
Extraction is handled separately by ``judex.sweeps.extrair_pecas``.

Surfaced via Typer at ``judex baixar-pecas``; library entry point is
:func:`run_download_pecas`. Detached invocation:

    nohup uv run judex baixar-pecas --csv X.csv --saida out/ ...

Input-mode priority: ``--retentar-de`` > ``--csv`` > range > filter.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from judex.scraping.proxy_pool import ProxyPool
from judex.sweeps import peca_cli as _pdf_cli
from judex.sweeps.download_driver import run_download_sweep
from judex.sweeps.peca_classification import (
    TIER_C_DOC_TYPES,
    filter_substantive,
    summarize_tipos,
)


def run_download_pecas(
    *,
    classe: str | None = None,
    inicio: int | None = None,
    fim: int | None = None,
    csv: Path | None = None,
    retentar_de: Path | None = None,
    impte_contem: str = "",
    tipos_doc: str = "",
    relator_contem: str = "",
    excluir_tipos_doc: str = "",
    limite: int = 0,
    apenas_substantivas: bool = True,
    saida: Path | None = None,
    forcar: bool = False,
    dry_run: bool = False,
    nao_perguntar: bool = False,
    retomar: bool = False,
    proxy_pool: Path | None = None,
    proxy_rotate_seconds: float = 270.0,
    proxy_cooldown_minutes: float = 4.0,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        targets, mode_label = _pdf_cli.resolve_targets(
            stage="baixar",
            retentar_de=retentar_de,
            csv=csv,
            classe=classe,
            inicio=inicio,
            fim=fim,
            impte_contem=impte_contem,
            tipos_doc=tipos_doc,
            relator_contem=relator_contem,
            excluir_tipos_doc=excluir_tipos_doc,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    from judex.utils.cli_render import render_info, render_warning

    if apenas_substantivas:
        before = len(targets)
        targets = filter_substantive(targets)
        dropped = before - len(targets)
        if dropped:
            render_info(
                f"--apenas-substantivas: dropped {dropped:,} tier-C targets "
                f"({before:,} → {len(targets):,}). Use --todos-tipos to disable."
            )

    # Pre-flight tipo summary + unseen-tipo warning. Runs regardless of
    # filter state — unseen tipos are worth flagging either way.
    top, unseen = summarize_tipos(targets)
    if top:
        top_str = ", ".join(f"{t!r} ({n:,})" for t, n in top)
        render_info(f"top tipos: {top_str}")
    if unseen:
        unseen_sorted = sorted(unseen.items(), key=lambda kv: -kv[1])
        body = ["not in classification, kept by default:"]
        body += [f"  • {t!r} (n={n:,})" for t, n in unseen_sorted]
        body.append(
            "see docs/peca-tipo-classification.md § Policy for unseen tipos."
        )
        render_warning("unseen tipo(s)", body)

    if limite and len(targets) > limite:
        targets = targets[:limite]

    if not targets:
        print("error: no targets resolved. Check --classe/-i/-f, --csv, "
              "--retentar-de, or filter args.", file=sys.stderr)
        return 2

    _pdf_cli.print_download_preview(targets, mode_label=mode_label)

    if dry_run:
        return 0

    _pdf_cli.confirm_or_exit(nao_perguntar=nao_perguntar)

    saida = saida or Path("runs/active/baixar-adhoc")
    saida.mkdir(parents=True, exist_ok=True)

    pool = ProxyPool.from_file(proxy_pool) if proxy_pool else None
    if pool is not None:
        print(f"=== proxy rotation active · pool_size={pool.size()} "
              f"· rotate_every={proxy_rotate_seconds:.0f}s "
              f"· cooldown={proxy_cooldown_minutes:.1f}min ===",
              flush=True)

    _, _, failed = run_download_sweep(
        targets,
        out_dir=saida,
        forcar=forcar,
        resume=retomar,
        retry_from=retentar_de,
        pool=pool,
        proxy_rotate_seconds=proxy_rotate_seconds,
        proxy_cooldown_minutes=proxy_cooldown_minutes,
    )
    return 0 if failed == 0 else 1


