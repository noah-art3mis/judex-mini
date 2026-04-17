"""Shared CLI scaffolding for PDF target selection.

Both `scripts/fetch_pdfs.py` and `scripts/reextract_unstructured.py`
filter judex-mini output JSON the same way (classe, impte, doc_type,
relator, exclude_doc_types). This module exposes:

- ``add_filter_args(ap)`` — wires the six flags onto an argparse parser.
- ``targets_from_args(args)`` — calls `collect_pdf_targets` with the
  parsed values.
- ``split_csv(s)`` — parse a comma-separated CLI value into a list.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.sweeps.pdf_targets import PdfTarget, collect_pdf_targets


def split_csv(s: str | None) -> list[str]:
    if not s:
        return []
    return [p.strip() for p in s.split(",") if p.strip()]


def add_filter_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--roots", nargs="+", type=Path,
        default=[Path("data/output"), Path("data/output/sample")],
        help="Directories to walk for judex-mini_*.json files.",
    )
    ap.add_argument(
        "--classe", type=str, default=None,
        help='Match exact classe, e.g. "HC", "RE", "ADI".',
    )
    ap.add_argument(
        "--impte-contains", type=str, default="",
        help='Comma-separated substrings (ANY match) for '
             '.partes[].nome where .tipo == "IMPTE.(S)".',
    )
    ap.add_argument(
        "--doc-types", type=str, default="",
        help="Comma-separated exact andamento.link_descricao values "
             '(e.g. "DECISÃO MONOCRÁTICA,INTEIRO TEOR DO ACÓRDÃO"). '
             "Empty = all doc types.",
    )
    ap.add_argument(
        "--relator-contains", type=str, default="",
        help="Comma-separated substrings to match in .relator.",
    )
    ap.add_argument(
        "--exclude-doc-types", type=str, default="",
        help="Comma-separated doc_types to skip. Applied after --doc-types.",
    )


def targets_from_args(args: argparse.Namespace) -> list[PdfTarget]:
    return collect_pdf_targets(
        args.roots,
        classe=args.classe,
        impte_contains=split_csv(args.impte_contains),
        doc_types=split_csv(args.doc_types),
        relator_contains=split_csv(args.relator_contains),
        exclude_doc_types=split_csv(args.exclude_doc_types),
    )
