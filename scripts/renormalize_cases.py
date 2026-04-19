"""Renormalize old-schema case JSONs against cached HTML fragments.

Reads every `data/cases/<CLASSE>/judex-mini_<CLASSE>_<N>*.json`, checks
its `schema_version`, and if < SCHEMA_VERSION re-runs the current
extractors against the gzipped HTML cache at
`data/cache/html/<CLASSE>_<N>/`. Writes the renormalized item back
atomically (tmp + os.replace).

**No network.** The script never calls STF or sistemas.stf.jus.br; all
rebuilds come from the HTML fragment cache + the URL-keyed PDF text
cache. Cases with no / incomplete HTML cache are reported as
`needs_rescrape` and left untouched.

Why this works
--------------
Each schema bump (commits 45d86df → current) changed parsing, not
source HTML. The HTML fragments STF served are still in the cache;
running the current `src.scraping.extraction.*` modules against them
produces the new shape. The PDF text cache (URL-keyed) is untouched
by schema bumps, so sessao_virtual's `documentos` `text` values
survive too.

v4 note (2026-04-19). The v3 → v4 jump adds `extractor: Optional[str]`
on every link/documento and restructures `documentos` from dict to
list. Both fall out naturally: re-running `_build_documentos` emits
the list shape, and `_cache_only_pdf_fetcher` now returns
`(text, extractor)` with the extractor label read from the
`<sha1>.extractor` sidecar. Cache entries that predate the sidecar
(most of them, today) get `extractor: null` — an agreed lossy
backfill that new scrapes will populate as PDFs are re-extracted.

Usage
-----

    # Dry run — count old-schema files + cache coverage.
    PYTHONPATH=. uv run python scripts/renormalize_cases.py --dry-run

    # Rebuild one classe.
    PYTHONPATH=. uv run python scripts/renormalize_cases.py --classe HC

    # Rebuild everything, in parallel.
    PYTHONPATH=. uv run python scripts/renormalize_cases.py --workers 8

    # Force renormalization even for files already at SCHEMA_VERSION.
    PYTHONPATH=. uv run python scripts/renormalize_cases.py --force

Outputs a summary including `needs_rescrape` counts — those cases
need `scripts/run_sweep.py` to repopulate the HTML cache before the
renormalizer can touch them.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from bs4 import BeautifulSoup

from src.data.types import SCHEMA_VERSION, ScrapeMeta, StfItem
from src.scraping.extraction import http as ex
from src.scraping.extraction import sessao as sessao_ex
from src.scraping.scraper import (
    DETALHE,
    TAB_ANDAMENTOS,
    TAB_DECISOES,
    TAB_DESLOCAMENTOS,
    TAB_INFORMACOES,
    TAB_PARTES,
    TAB_PAUTAS,
    TAB_PETICOES,
    TAB_RECURSOS,
    TAB_SESSAO,
    _canonical_url,
    _extract_tema_from_abasessao,
)
from src.data.reshape import reshape_to_v7
from src.utils import html_cache, peca_cache

CASES_ROOT = Path("data/cases")


@dataclass
class RenormResult:
    path: Path
    status: str  # "ok" | "already_current" | "needs_rescrape" | "error"
    detail: Optional[str] = None


class CacheMiss(Exception):
    pass


def _cache_only_sessao_fetcher(classe: str, processo: int):
    """Sessão JSON fetcher that refuses to hit the network."""
    def fetcher(param: str, value: int) -> str:
        tab = f"sessao_{param}_{value}"
        hit = html_cache.read(classe, processo, tab)
        if hit is None:
            raise CacheMiss(f"sessao cache miss: {tab}")
        return hit
    return fetcher


def _cache_only_pdf_fetcher():
    """PDF fetcher that returns `(text, extractor)` from the cache.

    Both slots are None on a full miss. When text is cached but the
    `<sha1>.extractor` sidecar is absent (pre-v4 cache entries), we
    return `(text, None)` — the v4 renormalizer writes the documento
    with `extractor: null`, which is the agreed "we don't know which
    extractor produced this" signal.
    """
    def fetcher(url: str) -> tuple[Optional[str], Optional[str]]:
        return peca_cache.read(url), peca_cache.read_extractor(url)
    return fetcher


# Tabs the current extractors read to rebuild an StfItem. Missing →
# needs_rescrape (we can't synthesize partes or andamentos from nothing).
_REQUIRED_TABS: tuple[str, ...] = (
    TAB_INFORMACOES,
    TAB_PARTES,
    TAB_ANDAMENTOS,
    TAB_SESSAO,
)

# Tabs the rebuild reads only for their own derived field, or that have
# no extractor at all (TAB_DECISOES). Every extractor over these tabs
# no-ops on empty input (`find_all` returns []). So a cache archive
# written before these tabs were added to TABS can still renormalize —
# the corresponding list field just falls out empty, which is the same
# shape a live scrape would produce when the tab has no rows.
_OPTIONAL_TABS: tuple[str, ...] = (
    TAB_DECISOES,
    TAB_DESLOCAMENTOS,
    TAB_PETICOES,
    TAB_RECURSOS,
    TAB_PAUTAS,
)


def _read_all_cached(classe: str, processo: int) -> Optional[dict[str, str]]:
    """Return dict of {tab: html} or None if any required fragment is missing.

    Optional tabs fall through as empty strings when absent. This keeps
    pre-v6 cache archives (which predate `abaPautas` + `abaDecisoes`)
    renormalizable from partes + andamentos alone.
    """
    out: dict[str, str] = {}
    detalhe = html_cache.read(classe, processo, DETALHE)
    if detalhe is None:
        return None
    out[DETALHE] = detalhe
    for tab in _REQUIRED_TABS:
        h = html_cache.read(classe, processo, tab)
        if h is None:
            return None
        out[tab] = h
    for tab in _OPTIONAL_TABS:
        out[tab] = html_cache.read(classe, processo, tab) or ""
    return out


def _rebuild_item(classe: str, processo: int) -> Optional[StfItem]:
    """Rebuild an StfItem from cached fragments, or None on cache miss.

    Purely offline. Raises CacheMiss through sessao_virtual if its
    JSON endpoints weren't captured; callers treat that as needs_rescrape.
    """
    incidente = html_cache.read_incidente(classe, processo)
    if incidente is None:
        return None

    tabs = _read_all_cached(classe, processo)
    if tabs is None:
        return None

    detalhe_soup = BeautifulSoup(tabs[DETALHE], "lxml")
    info_soup = BeautifulSoup(tabs[TAB_INFORMACOES], "lxml")

    partes = ex.extract_partes(tabs[TAB_PARTES])

    tema = _extract_tema_from_abasessao(tabs[TAB_SESSAO])
    try:
        sessao_virtual = sessao_ex.extract_sessao_virtual_from_json(
            incidente=incidente,
            tema=tema,
            fetcher=_cache_only_sessao_fetcher(classe, processo),
            pdf_fetcher=_cache_only_pdf_fetcher(),
        )
    except CacheMiss:
        return None

    andamentos = ex.extract_andamentos(tabs[TAB_ANDAMENTOS])
    return StfItem(
        _meta=ScrapeMeta(
            schema_version=SCHEMA_VERSION,
            status_http=200,
            extraido=datetime.now().isoformat(),
        ),
        incidente=incidente,
        classe=classe,
        processo_id=processo,
        url=_canonical_url(incidente),
        numero_unico=ex.extract_numero_unico(detalhe_soup),
        meio=ex.extract_meio(detalhe_soup),
        publicidade=ex.extract_publicidade(detalhe_soup),
        badges=ex.extract_badges(detalhe_soup),
        assuntos=ex.extract_assuntos(info_soup),
        data_protocolo=ex.extract_data_protocolo(info_soup),
        orgao_origem=ex.extract_orgao_origem(info_soup),
        origem=ex.extract_origem(info_soup),
        numero_origem=ex.extract_numero_origem(info_soup),
        volumes=ex.extract_volumes(info_soup),
        folhas=ex.extract_folhas(info_soup),
        apensos=ex.extract_apensos(info_soup),
        relator=ex.extract_relator(detalhe_soup),
        primeiro_autor=ex.extract_primeiro_autor(partes),
        partes=partes,
        andamentos=andamentos,
        sessao_virtual=sessao_virtual,
        deslocamentos=ex.extract_deslocamentos(tabs[TAB_DESLOCAMENTOS]),
        peticoes=ex.extract_peticoes(tabs[TAB_PETICOES]),
        recursos=ex.extract_recursos(tabs[TAB_RECURSOS]),
        pautas=ex.extract_pautas(tabs[TAB_PAUTAS]),
        outcome=ex.derive_outcome({
            "sessao_virtual": sessao_virtual,
            "andamentos": andamentos,
        }),
    )


def _load_existing(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw[0] if raw else {}
    return raw or {}


def _atomic_write_json(path: Path, item: StfItem) -> None:
    """Write a per-process case JSON as a bare dict (v3 shape).

    Called by the migrator after renormalizing. v2 files arrive
    list-wrapped; they're unwrapped by ``_load_existing`` and
    rewritten flat.
    """
    tmp = path.with_suffix(f".json.tmp.{os.getpid()}")
    tmp.write_text(
        json.dumps(item, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _process_file(
    path: Path, *, force: bool, dry_run: bool, mode: str = "full"
) -> RenormResult:
    try:
        existing = _load_existing(path)
    except Exception as e:
        return RenormResult(path, "error", f"load: {e}")

    # v6: schema_version lives under `_meta`. Pre-v6 files had it
    # top-level; fall back so the renormalizer can spot already-v6 files
    # regardless of shape history.
    meta = existing.get("_meta") or {}
    current_version = meta.get("schema_version") or existing.get("schema_version")
    if not force and current_version == SCHEMA_VERSION:
        return RenormResult(path, "already_current")

    if mode == "shape-only":
        try:
            new_item = reshape_to_v6(existing)
        except Exception as e:
            return RenormResult(path, "error", f"reshape: {type(e).__name__}: {e}")
        if dry_run:
            return RenormResult(path, "ok", "dry-run")
        try:
            _atomic_write_json(path, new_item)
        except Exception as e:
            return RenormResult(path, "error", f"write: {e}")
        return RenormResult(path, "ok")

    classe = existing.get("classe")
    processo = existing.get("processo_id")
    if classe is None or processo is None:
        return RenormResult(path, "error", "missing classe/processo_id")

    try:
        new_item = _rebuild_item(classe, int(processo))
    except Exception as e:
        return RenormResult(path, "error", f"rebuild: {type(e).__name__}: {e}")

    if new_item is None:
        return RenormResult(path, "needs_rescrape")

    if dry_run:
        return RenormResult(path, "ok", "dry-run")

    try:
        _atomic_write_json(path, new_item)
    except Exception as e:
        return RenormResult(path, "error", f"write: {e}")
    return RenormResult(path, "ok")


def _iter_case_files(
    root: Path, classes: Optional[list[str]]
) -> list[Path]:
    targets: list[Path] = []
    if not root.exists():
        return targets
    for classe_dir in sorted(root.iterdir()):
        if not classe_dir.is_dir():
            continue
        if classes is not None and classe_dir.name not in classes:
            continue
        targets.extend(sorted(classe_dir.glob("judex-mini_*.json")))
    return targets


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--cases-root", type=Path, default=CASES_ROOT,
        help="where to find case JSONs (default: data/cases).",
    )
    ap.add_argument(
        "--classe", action="append", default=None,
        help="limit to one classe; repeat for multiple. Default: all.",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="rebuild even when schema_version matches SCHEMA_VERSION.",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="classify every file, but don't write anything.",
    )
    ap.add_argument(
        "--workers", type=int, default=1,
        help="parallel worker count (default: 1; extractors are CPU-bound).",
    )
    ap.add_argument(
        "--limit", type=int, default=0,
        help="stop after N files (0 = no limit; applied after filtering).",
    )
    ap.add_argument(
        "--report-every", type=int, default=500,
        help="log a progress line every N files.",
    )
    ap.add_argument(
        "--mode", choices=("full", "shape-only"), default="full",
        help=(
            "full: re-run extractors against cached HTML (canonical; "
            "needs full HTML cache or short-circuits to needs_rescrape). "
            "shape-only: pure JSON v1/v2/v3 → v6 dict surgery, no HTML "
            "or PDF reads — recovers files the full path would skip."
        ),
    )
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    paths = _iter_case_files(args.cases_root, args.classe)
    if not paths:
        print(f"no case JSONs under {args.cases_root}", file=sys.stderr)
        return 2
    if args.limit:
        paths = paths[: args.limit]

    print(
        f"scanning {len(paths)} files "
        f"(SCHEMA_VERSION={SCHEMA_VERSION}, mode={args.mode}, "
        f"force={args.force}, dry_run={args.dry_run}, "
        f"workers={args.workers})",
        flush=True,
    )

    counts: dict[str, int] = {}
    needs_rescrape: list[Path] = []
    errors: list[tuple[Path, str]] = []
    t0 = time.perf_counter()

    def _tally(r: RenormResult, i: int) -> None:
        counts[r.status] = counts.get(r.status, 0) + 1
        if r.status == "needs_rescrape":
            needs_rescrape.append(r.path)
        elif r.status == "error":
            errors.append((r.path, r.detail or ""))
        if i % args.report_every == 0:
            rate = i / max(time.perf_counter() - t0, 1e-6)
            print(
                f"  [{i}/{len(paths)}] "
                + " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
                + f"  {rate:.0f} files/s",
                flush=True,
            )

    if args.workers <= 1:
        for i, p in enumerate(paths, 1):
            _tally(
                _process_file(
                    p, force=args.force, dry_run=args.dry_run, mode=args.mode
                ),
                i,
            )
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [
                pool.submit(
                    _process_file,
                    p,
                    force=args.force,
                    dry_run=args.dry_run,
                    mode=args.mode,
                )
                for p in paths
            ]
            for i, fut in enumerate(as_completed(futures), 1):
                _tally(fut.result(), i)

    wall = time.perf_counter() - t0
    print()
    print("=== renormalize summary ===")
    for k, v in sorted(counts.items()):
        print(f"  {k:18s} {v}")
    print(f"  wall              {wall:.1f}s "
          f"({len(paths)/max(wall,1e-6):.0f} files/s)")

    if needs_rescrape:
        out_path = Path("runs/active/renormalize_needs_rescrape.csv")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            f.write("classe,processo\n")
            for p in needs_rescrape:
                try:
                    item = _load_existing(p)
                    f.write(f"{item.get('classe','')},{item.get('processo_id','')}\n")
                except Exception:
                    continue
        print(f"  wrote rescrape list → {out_path}")

    if errors:
        print("  first 10 errors:")
        for p, d in errors[:10]:
            print(f"    {p}: {d}")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
