"""Download STF PDFs to the local bytes cache.

The WAF-bound half of the PDF pipeline: fetches
`PecaTarget.url` from STF and writes raw bytes to
`data/cache/pdf/<sha1>.pdf.gz`. Extraction is handled separately by
`scripts/extrair_pecas.py`.

Usage:

    # Range mode (parallel to varrer-processos)
    PYTHONPATH=. uv run python scripts/baixar_pecas.py \\
        -c HC -i 252920 -f 253000 \\
        --saida runs/active/2026-04-19-hc-bytes \\
        --nao-perguntar

    # Filter fallback
    PYTHONPATH=. uv run python scripts/baixar_pecas.py \\
        --classe HC --impte-contem TORON \\
        --tipos-doc "DECISÃO MONOCRÁTICA,INTEIRO TEOR DO ACÓRDÃO" \\
        --saida runs/active/2026-04-19-toron

Input-mode priority: `--retentar-de` > `--csv` > range > filter.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.scraping.proxy_pool import ProxyPool
from src.sweeps import peca_cli as _pdf_cli
from src.sweeps.download_driver import run_download_sweep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Input modes.
    ap.add_argument("-c", "--classe", type=str, default=None,
                    help='Classe (e.g. "HC"). Alone → filter. With -i/-f → range.')
    ap.add_argument("-i", "--inicio", type=int, default=None,
                    help="First processo in range (inclusive).")
    ap.add_argument("-f", "--fim", type=int, default=None,
                    help="Last processo in range (inclusive).")
    ap.add_argument("--csv", type=Path, default=None,
                    help="CSV of (classe, processo). Beats range/filter.")
    ap.add_argument("--retentar-de", dest="retentar_de", type=Path, default=None,
                    help="Path to a prior pdfs.errors.jsonl; re-runs those URLs.")

    # Filters (fallback only).
    ap.add_argument("--impte-contem", dest="impte_contem", type=str, default="",
                    help="Filter: comma-separated substrings for IMPTE.(S).")
    ap.add_argument("--tipos-doc", dest="tipos_doc", type=str, default="",
                    help="Filter: comma-separated exact doc_type values.")
    ap.add_argument("--relator-contem", dest="relator_contem", type=str, default="",
                    help="Filter: comma-separated substrings in .relator.")
    ap.add_argument("--excluir-tipos-doc", dest="excluir_tipos_doc",
                    type=str, default="",
                    help="Filter: comma-separated doc_types to skip.")
    ap.add_argument("--limite", type=int, default=0,
                    help="Truncate to N targets (0 = no limit). After filtering.")

    # Execution.
    ap.add_argument("--saida", type=Path, default=None,
                    help="Output directory. Holds pdfs.state.json, log, errors.")
    ap.add_argument("--forcar", action="store_true",
                    help="Re-download even if bytes are already cached.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Preview only; do not fetch.")
    ap.add_argument("--nao-perguntar", dest="nao_perguntar", action="store_true",
                    help="Skip the interactive confirm. Required for non-TTY.")
    ap.add_argument("--retomar", action="store_true",
                    help="Skip targets already status=ok in pdfs.state.json.")

    # Proxy rotation (optional — off by default; costs proxy bandwidth).
    ap.add_argument(
        "--proxy-pool", dest="proxy_pool", type=Path, default=None,
        help="Path to a file with one proxy URL per line (# comments ok). "
             "Enables proactive IP rotation: swap sessions every "
             "--proxy-rotate-seconds so no single IP trips STF's WAF. "
             "Mirrors scripts/run_sweep.py semantics. See docs/rate-limits.md.",
    )
    ap.add_argument(
        "--proxy-rotate-seconds", dest="proxy_rotate_seconds",
        type=float, default=270.0,
        help="Seconds a proxy is used before rotating (default: 270). "
             "Ignored when --proxy-pool is absent.",
    )
    ap.add_argument(
        "--proxy-cooldown-minutes", dest="proxy_cooldown_minutes",
        type=float, default=4.0,
        help="Minutes a just-used proxy stays out of rotation (default: 4).",
    )

    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    targets, mode_label = _pdf_cli.resolve_targets(args)
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


if __name__ == "__main__":
    sys.exit(main())
