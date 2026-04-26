"""Extract text from locally-cached STF PDFs.

Reads bytes from `data/raw/pecas/<sha1>.<ext>.gz` (populated by
`scripts/baixar_pecas.py`), dispatches text extraction via
`src.scraping.ocr.extract_pdf` per `--provedor`, writes text +
sidecar + optional element list to `data/derived/pecas-texto/`.
Zero HTTP.

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
from judex.sweeps.peca_classification import filter_substantive, summarize_tipos


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


def run_extract_pecas(
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
    provedor: str = "pypdf",
    forcar: bool = False,
    saida: Path | None = None,
    dry_run: bool = False,
    nao_perguntar: bool = False,
    retomar: bool = False,
) -> int:
    if provedor not in _PROVIDERS:
        print(f"error: invalid --provedor {provedor!r}; choose from {_PROVIDERS}", file=sys.stderr)
        return 2

    args = argparse.Namespace(
        classe=classe, inicio=inicio, fim=fim, csv=csv,
        retentar_de=retentar_de,
        impte_contem=impte_contem, tipos_doc=tipos_doc,
        relator_contem=relator_contem, excluir_tipos_doc=excluir_tipos_doc,
        limite=limite, apenas_substantivas=apenas_substantivas,
        provedor=provedor, forcar=forcar, saida=saida,
        dry_run=dry_run, nao_perguntar=nao_perguntar, retomar=retomar,
    )

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    targets, mode_label = _pdf_cli.resolve_targets(args)
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
    ap.add_argument("--impte-contem", dest="impte_contem", type=str, default="")
    ap.add_argument("--tipos-doc", dest="tipos_doc", type=str, default="")
    ap.add_argument("--relator-contem", dest="relator_contem", type=str, default="")
    ap.add_argument("--excluir-tipos-doc", dest="excluir_tipos_doc",
                    type=str, default="")
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument(
        "--apenas-substantivas", dest="apenas_substantivas",
        action="store_true", default=True,
        help="Pula peças tier-C. Default: True. Desativar com --todos-tipos.",
    )
    ap.add_argument(
        "--todos-tipos", dest="apenas_substantivas",
        action="store_false",
    )
    ap.add_argument("--provedor", type=str, default="pypdf", choices=_PROVIDERS,
                    help="Text extractor. Default: pypdf.")
    ap.add_argument("--forcar", action="store_true",
                    help="Re-extract even if sidecar already matches --provedor.")
    ap.add_argument("--saida", type=Path, default=None)
    ap.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="Preview only; do not run the extractor.")
    ap.add_argument("--nao-perguntar", dest="nao_perguntar", action="store_true")
    ap.add_argument("--retomar", action="store_true")
    args = ap.parse_args(argv)
    return run_extract_pecas(**vars(args))


if __name__ == "__main__":
    sys.exit(main())
