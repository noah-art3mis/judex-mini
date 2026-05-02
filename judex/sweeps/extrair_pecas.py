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


_PROVIDERS = (
    "pypdf", "mistral", "chandra", "unstructured",
    "tesseract", "tesseract_modal", "tesseract_fly", "auto",
)

# `auto` routes per-target. ACÓRDÃO PDFs (vector-rendered through iText)
# pypdf-duplicate their content ~1.86× by reading both the visible text
# stream and a hidden Ementa-cover stream — gold-CER ≈ 90%, characterised
# 2026-05-01. tesseract on the same PDFs lands at <1% CER. Other
# doc classes show no comparable bug; pypdf is faster and equally clean
# there. So the router fork is doc_type-driven.
_AUTO_TESSERACT_DOC_TYPES = frozenset({"INTEIRO TEOR DO ACÓRDÃO"})


def pick_provider(target) -> str:
    """Return the provider that should extract this target under `--provedor auto`.

    `tesseract` for ACÓRDÃO-class doc_types (where pypdf has the
    iText-cover duplication bug); `pypdf` for everything else.
    Accepts a :class:`PecaTarget` or a bare ``doc_type`` string (the
    str path is a test convenience). Case- and accent-insensitive on
    the doc_type via the same fold the tier classifier uses.

    Override the OCR venue for the ACÓRDÃO branch via env var
    ``JUDEX_AUTO_TESSERACT_PROVIDER`` (default ``"tesseract"`` for
    backward compatibility / unit tests; set to ``"tesseract_fly"``
    or ``"tesseract_modal"`` to route the OCR work off-host).
    """
    from judex.sweeps.peca_classification import _fold

    doc_type = getattr(target, "doc_type", target) if target is not None else None
    if doc_type and _fold(doc_type) in {_fold(d) for d in _AUTO_TESSERACT_DOC_TYPES}:
        return os.environ.get("JUDEX_AUTO_TESSERACT_PROVIDER", "tesseract")
    return "pypdf"


def _build_ocr_config(provedor: str) -> OCRConfig:
    """Assemble an OCRConfig from env vars appropriate to the provider.

    Local providers (pypdf, tesseract) need no API key; tesseract_modal
    is the Modal-hosted variant and uses the deployed app's auth, no
    env var here. tesseract_fly's address is read from FLY_TESSERACT_URL
    by the provider itself (no API key required for the public deploy).
    Cloud providers read their keys from env (MISTRAL_API_KEY,
    UNSTRUCTURED_API_KEY, CHANDRA_API_KEY); missing keys raise early
    with a clear message.
    """
    if provedor in ("pypdf", "tesseract", "tesseract_modal", "tesseract_fly"):
        return OCRConfig(provider=provedor, api_key="")

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
    paralelo: int = 1,
) -> int:
    if provedor not in _PROVIDERS:
        print(f"error: invalid --provedor {provedor!r}; choose from {_PROVIDERS}", file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        targets, mode_label = _pdf_cli.resolve_targets(
            stage="extrair",
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

    _pdf_cli.print_extract_preview(
        targets, mode_label=mode_label, provedor=provedor,
    )

    if dry_run:
        return 0

    _pdf_cli.confirm_or_exit(nao_perguntar=nao_perguntar)

    saida = saida or Path(f"runs/active/extrair-{provedor}")
    saida.mkdir(parents=True, exist_ok=True)

    if provedor == "auto":
        # Validate keys for any cloud providers the router could pick.
        # Today the only provider auto picks is tesseract (no key
        # needed) plus pypdf, so this is a no-op; future fan-out (e.g.
        # routing to chandra) would surface its env_key check here.
        provider_router = pick_provider
        ocr_config = None  # built per-target inside the driver
    else:
        provider_router = None
        ocr_config = _build_ocr_config(provedor)

    _, _, _, failed = run_extract_sweep(
        targets,
        out_dir=saida,
        provedor=provedor,
        ocr_config=ocr_config,
        forcar=forcar,
        resume=retomar,
        retry_from=retentar_de,
        provider_router=provider_router,
        paralelo=paralelo,
    )
    return 0 if failed == 0 else 1


