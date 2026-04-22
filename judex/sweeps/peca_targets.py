"""Generic PDF target collection from judex-mini output files.

Walks `judex-mini_*.json` files under one or more roots and emits one
PecaTarget per substantive-doc URL in the andamento list. Four
resolvers share the same output shape:

- `collect_peca_targets` — filter fallback (classe, impte_contains,
  doc_types, relator_contains, exclude_doc_types). Used when no direct
  selector is set.
- `targets_from_range` — `-c CLASSE -i INICIO -f FIM`. All PDFs in
  each process in the inclusive range.
- `targets_from_csv` — `--csv alvos.csv`. Rows of `(classe, processo)`.
  All PDFs per matching case.
- `targets_from_errors_jsonl` — `--retentar-de pdfs.errors.jsonl`.
  Rehydrates full PdfTargets (url + processo_id + classe + doc_type +
  context) from a prior run's error log.

Direct selectors (range / CSV / retry) ignore the filter parameters
per `docs/superpowers/specs/2026-04-19-varrer-pdfs-ocr-knob.md §
Input-mode resolution`.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence


@dataclass
class PecaTarget:
    url: str
    processo_id: Optional[int] = None
    classe: Optional[str] = None
    doc_type: Optional[str] = None
    context: dict[str, Any] = field(default_factory=dict)


def _is_supported_doc_url(url: Optional[str]) -> bool:
    """True if `url` looks like a downloadable case document (PDF or RTF).

    Three STF URL shapes land as targets:
      - `.pdf` suffix — andamento `downloadPeca.asp?…&ext=.pdf` (note the
        leading dot is part of the suffix) and sessão-virtual voto PDFs
        on `sistemas.stf.jus.br/repgeral/` + `digital.stf.jus.br/…`.
      - `.rtf` suffix — future-proofing; not currently emitted by STF.
      - `ext=RTF` query suffix — andamento `downloadTexto.asp?…&ext=RTF`
        (STF's actual RTF form; the ext is a query param, not a file
        extension). The extraction layer auto-detects RTF by magic
        bytes, so the URL-side check only needs to recognise it as a
        valid document.
    """
    if not url:
        return False
    u = url.lower()
    if u.endswith((".pdf", ".rtf")):
        return True
    return u.endswith("ext=rtf")


def collect_peca_targets(
    roots: Sequence[Path],
    *,
    classe: Optional[str] = None,
    impte_contains: Sequence[str] = (),
    doc_types: Sequence[str] = (),
    relator_contains: Sequence[str] = (),
    exclude_doc_types: Sequence[str] = (),
) -> list[PecaTarget]:
    """Collect PDF targets from judex-mini output files.

    All filters AND together. Leaving a filter empty/None disables it.

    - `classe`: match exactly, e.g. "HC", "RE", "ADI".
    - `impte_contains`: any of these (case-insensitive) substrings
      appears in a `.partes[].nome` field whose `.tipo == "IMPTE.(S)"`.
    - `doc_types`: `andamento.link.tipo` must be in this set.
    - `relator_contains`: any of these substrings appears in `.relator`.
    - `exclude_doc_types`: `andamento.link.tipo` must NOT be in
      this set. Applied after `doc_types`.

    Deduplicates by URL across input files.
    """
    files = sorted({
        p for r in roots if Path(r).exists()
        for p in Path(r).rglob("judex-mini_*.json")
    })

    doc_type_set = set(doc_types) if doc_types else None
    excluded_doc_types = set(exclude_doc_types) if exclude_doc_types else None
    impte_needles = tuple(s.upper() for s in impte_contains) or None
    relator_needles = tuple(s.upper() for s in relator_contains) or None

    seen_urls: set[str] = set()
    out: list[PecaTarget] = []

    for f in files:
        try:
            rec = json.loads(f.read_text())
        except Exception:
            continue

        if classe is not None and rec.get("classe") != classe:
            continue

        impte_hits: list[str] = []
        if impte_needles is not None:
            for p in rec.get("partes") or []:
                if p.get("tipo") != "IMPTE.(S)":
                    continue
                nome = (p.get("nome") or "").upper()
                for needle in impte_needles:
                    if needle in nome and needle not in impte_hits:
                        impte_hits.append(needle)
            if not impte_hits:
                continue

        if relator_needles is not None:
            rel = (rec.get("relator") or "").upper()
            if not any(n in rel for n in relator_needles):
                continue

        pid = rec.get("processo_id")
        rec_classe = rec.get("classe")

        for a in rec.get("andamentos") or []:
            url, desc = _andamento_link(a)
            if not _is_supported_doc_url(url):
                continue
            if doc_type_set is not None and desc not in doc_type_set:
                continue
            if excluded_doc_types is not None and desc in excluded_doc_types:
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)

            ctx: dict[str, Any] = {}
            if impte_hits:
                ctx["impte_hits"] = list(impte_hits)
            out.append(PecaTarget(
                url=url,
                processo_id=pid,
                classe=rec_classe,
                doc_type=desc,
                context=ctx,
            ))
    return out


def _andamento_link(a: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Normalize `andamento.link` across schema versions.

    v3 (dominant on-disk shape): `link` is a bare URL string;
    `link_descricao` carries the doc type.
    v5+: `link` is a dict `{url, tipo, text, extractor}` or None.

    Returns `(url, doc_type)` or `(None, None)` when absent/malformed.
    """
    link_val = a.get("link")
    if isinstance(link_val, dict):
        return link_val.get("url"), link_val.get("tipo")
    if isinstance(link_val, str) and link_val:
        return link_val, a.get("link_descricao")
    return None, None


def _iter_case_pdf_targets(rec: dict[str, Any]) -> Iterator[PecaTarget]:
    """Yield one PecaTarget per .pdf URL in `rec.andamentos`.

    No filters. Parallel to the inner loop of `collect_peca_targets`
    but without the per-rec/impte/relator/doc-type filters — the
    direct-selector resolvers (range / CSV) scope by picking which
    files to feed in, not by filtering inside them.
    """
    pid = rec.get("processo_id")
    rec_classe = rec.get("classe")
    for a in rec.get("andamentos") or []:
        url, doc_type = _andamento_link(a)
        if not _is_supported_doc_url(url):
            continue
        yield PecaTarget(
            url=url,
            processo_id=pid,
            classe=rec_classe,
            doc_type=doc_type,
        )


def _load_case_records(path: Path) -> list[dict[str, Any]]:
    """Return the records inside a `judex-mini_*.json`.

    Two on-disk shapes exist — a single-record dict (one process per
    file) and a list of record dicts (batch/range files). Both are
    flattened here; malformed JSON is silently dropped.
    """
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _targets_from_files(paths: Sequence[Path]) -> list[PecaTarget]:
    """Dedupe-by-URL over a fixed file list."""
    seen: set[str] = set()
    out: list[PecaTarget] = []
    for p in paths:
        for rec in _load_case_records(p):
            for tgt in _iter_case_pdf_targets(rec):
                if tgt.url in seen:
                    continue
                seen.add(tgt.url)
                out.append(tgt)
    return out


def _find_case_file(roots: Sequence[Path], classe: str, processo: int) -> Optional[Path]:
    """Locate the case file for `(classe, processo)` under any root.

    Accepts two filename shapes produced by the scraper:
      - `judex-mini_<classe>_<processo>.json` (plain)
      - `judex-mini_<classe>_<processo>-<processo>.json` (range-row form)

    The scraper writes case files **flat under a per-classe bucket**:
    `<root>/<CLASSE>/judex-mini_<CLASSE>_<pid>.json`. There are no
    further subdirectories. We exploit that to do constant-time
    `Path.is_file()` probes — checking `<root>/<classe>/<name>` first
    (production layout) and falling back to `<root>/<name>` (callers
    that pass the classe-bucket directly as the root). Two stats per
    candidate name per root, no tree walks.

    The previous implementation called ``r.rglob(name)`` for every
    candidate, which is O(tree_size) per call and dominated
    `baixar-pecas` startup at sharded scale: 16 shards × ~1700 pids
    each × an 80k-file rglob each = thousands of full tree walks
    before the first HTTP request.

    Returns None if no candidate exists — a scraped-but-missing process
    is not an error, just absent from the resolved target set.
    """
    candidates = (
        f"judex-mini_{classe}_{processo}.json",
        f"judex-mini_{classe}_{processo}-{processo}.json",
    )
    for r in roots:
        r_path = Path(r)
        for name in candidates:
            bucketed = r_path / classe / name
            if bucketed.is_file():
                return bucketed
            direct = r_path / name
            if direct.is_file():
                return direct
    return None


def targets_from_range(
    classe: str, inicio: int, fim: int, *, roots: Sequence[Path]
) -> list[PecaTarget]:
    """All PDF URLs across `classe` processes in the inclusive range
    `[inicio, fim]`. Silently skips processes with no case file on disk."""
    files: list[Path] = []
    for n in range(inicio, fim + 1):
        p = _find_case_file(roots, classe, n)
        if p is not None:
            files.append(p)
    return _targets_from_files(files)


def targets_from_csv(csv_path: Path, *, roots: Sequence[Path]) -> list[PecaTarget]:
    """All PDF URLs across every `(classe, processo)` row in the CSV.

    Accepts minimal `classe,processo` columns. Extra columns (e.g.
    `source` from `run_sweep.py`'s CSV shape) are ignored.
    """
    files: list[Path] = []
    with Path(csv_path).open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            classe = (row.get("classe") or "").strip()
            processo_raw = (row.get("processo") or "").strip()
            if not classe or not processo_raw:
                continue
            p = _find_case_file(roots, classe, int(processo_raw))
            if p is not None:
                files.append(p)
    return _targets_from_files(files)


def targets_from_errors_jsonl(errors_path: Path) -> list[PecaTarget]:
    """Rehydrate PdfTargets from a prior run's `pdfs.errors.jsonl`.

    Each line is a JSON object emitted by `PecaStore.write_errors_file()`.
    Relies on url / processo_id / classe / doc_type / context being
    present — other fields (status, error, ts) are ignored.
    """
    out: list[PecaTarget] = []
    with Path(errors_path).open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            out.append(PecaTarget(
                url=rec["url"],
                processo_id=rec.get("processo_id"),
                classe=rec.get("classe"),
                doc_type=rec.get("doc_type"),
                context=rec.get("context") or {},
            ))
    return out
