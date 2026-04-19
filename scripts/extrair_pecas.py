"""Extract text from locally-cached STF PDFs.

Reads bytes from `data/cache/pdf/<sha1>.pdf.gz` (populated by
`scripts/baixar_pecas.py`), dispatches text extraction via
`src.scraping.ocr.extract_pdf` per `--provedor`, writes text +
sidecar + optional element list back to the same cache. Zero HTTP.

Usage:

    # Default: pypdf (free, fast, text-layer only)
    PYTHONPATH=. uv run python scripts/extrair_pecas.py \\
        -c HC -i 252920 -f 253000 \\
        --provedor pypdf --nao-perguntar

    # Mistral OCR (re-extract a prior pypdf run; no network)
    PYTHONPATH=. uv run python scripts/extrair_pecas.py \\
        -c HC -i 252920 -f 253000 \\
        --provedor mistral --forcar --nao-perguntar

Input-mode priority matches `baixar-pecas`: retry > csv > range > filter.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from judex.sweeps import peca_cli as _pdf_cli
from judex.scraping.ocr import OCRConfig
from judex.sweeps.extract_driver import run_extract_sweep


_PROVIDERS = ("pypdf", "mistral", "chandra", "unstructured")


def _build_ocr_config(provedor: str) -> OCRConfig:
    """Assemble an OCRConfig from env vars appropriate to the provider.

    pypdf runs locally and needs no API key; OCR providers read their
    keys from env (MISTRAL_API_KEY, UNSTRUCTURED_API_KEY,
    CHANDRA_API_KEY). Missing keys raise early with a clear message.
    """
    if provedor == "pypdf":
        return OCRConfig(provider="pypdf", api_key="")

    env_key = {
        "mistral": "MISTRAL_API_KEY",
        "unstructured": "UNSTRUCTURED_API_KEY",
        "chandra": "CHANDRA_API_KEY",
    }[provedor]
    api_key = os.environ.get(env_key, "").strip()
    if not api_key:
        sys.stderr.write(
            f"error: --provedor {provedor} requires env var {env_key}.\n"
        )
        sys.exit(2)
    return OCRConfig(provider=provedor, api_key=api_key)


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
    ap.add_argument("--impte-contem", dest="impte_contem", type=str, default="")
    ap.add_argument("--tipos-doc", dest="tipos_doc", type=str, default="")
    ap.add_argument("--relator-contem", dest="relator_contem", type=str, default="")
    ap.add_argument("--excluir-tipos-doc", dest="excluir_tipos_doc",
                    type=str, default="")
    ap.add_argument("--limite", type=int, default=0)

    # Extractor.
    ap.add_argument("--provedor", type=str, default="pypdf", choices=_PROVIDERS,
                    help="Text extractor. Default: pypdf.")
    ap.add_argument("--forcar", action="store_true",
                    help="Re-extract even if sidecar already matches --provedor.")

    # Execution.
    ap.add_argument("--saida", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="Preview only; do not run the extractor.")
    ap.add_argument("--nao-perguntar", dest="nao_perguntar", action="store_true")
    ap.add_argument("--retomar", action="store_true")

    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    targets, mode_label = _pdf_cli.resolve_targets(args)
    if args.limite and len(targets) > args.limite:
        targets = targets[: args.limite]

    if not targets:
        print("error: no targets resolved. Check --classe/-i/-f, --csv, "
              "--retentar-de, or filter args.", file=sys.stderr)
        return 2

    _pdf_cli.print_extract_preview(
        targets, mode_label=mode_label, provedor=args.provedor,
    )

    if args.dry_run:
        return 0

    _pdf_cli.confirm_or_exit(nao_perguntar=args.nao_perguntar)

    ocr_config = _build_ocr_config(args.provedor)
    saida = args.saida or Path(f"runs/active/extrair-{args.provedor}")
    saida.mkdir(parents=True, exist_ok=True)

    _, _, _, failed = run_extract_sweep(
        targets,
        out_dir=saida,
        provedor=args.provedor,
        ocr_config=ocr_config,
        forcar=args.forcar,
        resume=args.retomar,
        retry_from=args.retentar_de,
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
