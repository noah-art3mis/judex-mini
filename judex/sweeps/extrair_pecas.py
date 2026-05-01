"""Extract text from locally-cached STF PDFs.

Reads bytes from ``data/raw/pecas/<sha1>.<ext>.gz`` (populated by
``judex.sweeps.baixar_pecas``), dispatches text extraction via
``judex.scraping.ocr.extract_pdf`` per ``--provedor``, writes text +
sidecar + optional element list to ``data/derived/pecas-texto/``.
Zero HTTP.

Surfaced via Typer at ``judex extrair-pecas``; library entry point is
:func:`run_extract_pecas`. Detached invocation:

    nohup uv run judex extrair-pecas --csv X.csv --provedor pypdf ...

Input-mode priority matches ``baixar-pecas``: retry > csv > range > filter.
"""

from __future__ import annotations

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

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        targets, mode_label = _pdf_cli.resolve_targets(
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
    if apenas_substantivas:
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

    if limite and len(targets) > limite:
        targets = targets[:limite]

    if not targets:
        print("error: no targets resolved. Check --classe/-i/-f, --csv, "
              "--retentar-de, or filter args.", file=sys.stderr)
        return 2

    _pdf_cli.print_extract_preview(
        targets, mode_label=mode_label, provedor=provedor,
    )

    if dry_run:
        return 0

    _pdf_cli.confirm_or_exit(nao_perguntar=nao_perguntar)

    ocr_config = _build_ocr_config(provedor)
    saida = saida or Path(f"runs/active/extrair-{provedor}")
    saida.mkdir(parents=True, exist_ok=True)

    _, _, _, failed = run_extract_sweep(
        targets,
        out_dir=saida,
        provedor=provedor,
        ocr_config=ocr_config,
        forcar=forcar,
        resume=retomar,
        retry_from=retentar_de,
    )
    return 0 if failed == 0 else 1


