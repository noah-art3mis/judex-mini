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

import argparse
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
    args = argparse.Namespace(
        classe=classe, inicio=inicio, fim=fim, csv=csv,
        retentar_de=retentar_de,
        impte_contem=impte_contem, tipos_doc=tipos_doc,
        relator_contem=relator_contem, excluir_tipos_doc=excluir_tipos_doc,
        limite=limite, apenas_substantivas=apenas_substantivas,
        saida=saida, forcar=forcar, dry_run=dry_run,
        nao_perguntar=nao_perguntar, retomar=retomar,
        proxy_pool=proxy_pool,
        proxy_rotate_seconds=proxy_rotate_seconds,
        proxy_cooldown_minutes=proxy_cooldown_minutes,
    )

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        targets, mode_label = _pdf_cli.resolve_targets(args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.apenas_substantivas:
        before = len(targets)
        targets = filter_substantive(targets)
        dropped = before - len(targets)
        if dropped:
            print(
                f"--apenas-substantivas: dropped {dropped} tier-C targets "
                f"({before} → {len(targets)}). Use --todos-tipos to disable.",
                flush=True,
            )

    # Pre-flight tipo summary + unseen-tipo warning. Runs regardless of
    # filter state — unseen tipos are worth flagging either way.
    top, unseen = summarize_tipos(targets)
    if top:
        top_str = ", ".join(f"{t!r} ({n:,})" for t, n in top)
        print(f"top tipos: {top_str}", flush=True)
    if unseen:
        unseen_str = ", ".join(
            f"{t!r} (n={n:,})" for t, n in sorted(unseen.items(), key=lambda kv: -kv[1])
        )
        print(
            f"⚠  unseen tipo(s) — not in classification, kept by default: {unseen_str}. "
            f"See docs/peca-tipo-classification.md § Policy for unseen tipos.",
            flush=True,
        )

    if args.limite and len(targets) > args.limite:
        targets = targets[: args.limite]

    if not targets:
        print("error: no targets resolved. Check --classe/-i/-f, --csv, "
              "--retentar-de, or filter args.", file=sys.stderr)
        return 2

    _pdf_cli.print_download_preview(targets, mode_label=mode_label)

    if args.dry_run:
        return 0

    _pdf_cli.confirm_or_exit(nao_perguntar=args.nao_perguntar)

    saida = args.saida or Path("runs/active/baixar-adhoc")
    saida.mkdir(parents=True, exist_ok=True)

    pool = ProxyPool.from_file(args.proxy_pool) if args.proxy_pool else None
    if pool is not None:
        print(f"=== proxy rotation active · pool_size={pool.size()} "
              f"· rotate_every={args.proxy_rotate_seconds:.0f}s "
              f"· cooldown={args.proxy_cooldown_minutes:.1f}min ===",
              flush=True)

    _, _, failed = run_download_sweep(
        targets,
        out_dir=saida,
        forcar=args.forcar,
        resume=args.retomar,
        retry_from=args.retentar_de,
        pool=pool,
        proxy_rotate_seconds=args.proxy_rotate_seconds,
        proxy_cooldown_minutes=args.proxy_cooldown_minutes,
    )
    return 0 if failed == 0 else 1


