"""Fetch andamento PDFs for HCs where marquee criminal-bar lawyers appear.

Feeds `analysis/hc_famous_lawyers.py`'s text-profile cells: the curated
lawyer list in the notebook only uses `partes.nome` + `outcome` (metadata).
To describe *what* these lawyers do, we need the decisão monocrática / acórdão
text, which lives in PDFs linked from `andamentos[].link` on portal.stf.jus.br.

Pacing matters — `portal.stf.jus.br/processos/*` is WAF-gated (403 bursts).
We reuse the scraper's session + retry-403 + pace with `--throttle-sleep`.

Usage:
    PYTHONPATH=. uv run python scripts/fetch_famous_lawyer_pdfs.py \
        --throttle-sleep 2.0
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from src.config import ScraperConfig
from src.scraper_http import _http_get_with_retry, new_session
from src.utils import pdf_cache
from src.utils.adaptive_throttle import AdaptiveThrottle
from src.utils.pdf_utils import (
    detect_file_type,
    extract_pdf_text_from_content,
    extract_rtf_text,
)
from src.utils.request_log import RequestLog


FAMOUS_NEEDLES = (
    "TORON",
    "PIERPAOLO",
    "PEDRO MACHADO DE ALMEIDA CASTRO",
    "ARRUDA BOTELHO",
    "MARCELO LEONARDO",
    "NILO BATISTA",
    "VILARDI",
    "PODVAL",
    "MUDROVITSCH",
    "BADARO",
    "DANIEL GERBER",
    "TRACY JOSEPH REINALDET",
)

SUBSTANTIVE_DOC_TYPES = {
    "DECISÃO MONOCRÁTICA",
    "INTEIRO TEOR DO ACÓRDÃO",
    "MANIFESTAÇÃO DA PGR",
    "DESPACHO",
}


def _is_famous_impetrante(partes: list) -> list[str]:
    hits: list[str] = []
    for p in partes or []:
        if p.get("tipo") != "IMPTE.(S)":
            continue
        nome = (p.get("nome") or "").upper()
        for n in FAMOUS_NEEDLES:
            if n in nome:
                hits.append(n)
                break
    return hits


def _collect_targets(roots: list[Path]) -> list[tuple[str, int, str, str]]:
    files = sorted(
        {p for r in roots if r.exists() for p in r.rglob("judex-mini_HC_*.json")}
    )
    out: list[tuple[str, int, str, str]] = []
    seen_urls: set[str] = set()
    for f in files:
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        rec = d[0] if isinstance(d, list) else d
        if rec.get("classe") != "HC":
            continue
        hits = _is_famous_impetrante(rec.get("partes") or [])
        if not hits:
            continue
        pid = rec.get("processo_id")
        lawyer = hits[0]
        for a in rec.get("andamentos") or []:
            link = a.get("link")
            desc = a.get("link_descricao")
            if not link or not link.lower().endswith(".pdf"):
                continue
            if desc not in SUBSTANTIVE_DOC_TYPES:
                continue
            if link in seen_urls:
                continue
            seen_urls.add(link)
            out.append((lawyer, pid, desc, link))
    return out


def _fetch_one(
    session, url: str, config: ScraperConfig, *, context: dict | None = None
) -> str | None:
    r = _http_get_with_retry(session, url, config=config, timeout=60)
    ftype = detect_file_type(r)
    if ftype == "pdf":
        return extract_pdf_text_from_content(r.content)
    if ftype == "rtf":
        return extract_rtf_text(r.content)
    logging.warning(f"unknown file type for {url}")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--throttle-sleep", type=float, default=2.0,
                    help="seconds between successive GETs (default 2.0)")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after N fetches (0 = no limit)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print targets and exit without fetching")
    ap.add_argument("--check", action="store_true",
                    help="report cache coverage (cached vs missing) and exit")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    roots = [Path("output"), Path("output/sample")]
    targets = _collect_targets(roots)
    print(f"targets: {len(targets)} PDF URLs across {len({t[1] for t in targets})} HCs")

    if args.dry_run:
        from collections import Counter
        by_type = Counter(t[2] for t in targets)
        for k, v in by_type.most_common():
            print(f"  {v:4d}  {k}")
        return 0

    if args.check:
        from collections import Counter
        missing = [(pid, desc, url) for _, pid, desc, url in targets
                   if pdf_cache.read(url) is None]
        cached = len(targets) - len(missing)
        print(f"cached:  {cached}")
        print(f"missing: {len(missing)}")
        if missing:
            by_type = Counter(d for _, d, _ in missing)
            print("missing by type:")
            for k, v in by_type.most_common():
                print(f"  {v:4d}  {k}")
            print("first 5 missing URLs:")
            for pid, desc, url in missing[:5]:
                print(f"  HC {pid} {desc}: {url}")
        return 0 if not missing else 1

    session = new_session()
    throttle = AdaptiveThrottle(
        target_concurrency=1.0,
        start_delay=args.throttle_sleep,
        min_delay=args.throttle_sleep,
        max_delay=max(args.throttle_sleep * 10, 30.0),
    )
    request_log = RequestLog()
    config = ScraperConfig(throttle=throttle, request_log=request_log)

    fetched = 0
    cached_already = 0
    failed: list[tuple[str, str]] = []

    for i, (lawyer, pid, desc, url) in enumerate(targets, 1):
        if args.limit and fetched >= args.limit:
            break
        if pdf_cache.read(url) is not None:
            cached_already += 1
            request_log.log(url=url, from_cache=True,
                            context={"processo_id": pid, "doc_type": desc,
                                     "lawyer": lawyer, "classe": "HC"})
            continue
        try:
            text = _fetch_one(session, url, config,
                              context={"processo_id": pid, "doc_type": desc,
                                       "lawyer": lawyer, "classe": "HC"})
        except Exception as e:
            logging.warning(f"[{i}/{len(targets)}] {pid} {desc}: FAIL {e}")
            failed.append((url, repr(e)))
            continue
        if text:
            pdf_cache.write(url, text)
            fetched += 1
            logging.info(f"[{i}/{len(targets)}] {pid} {desc}: ok ({len(text)} chars)")
        else:
            logging.warning(f"[{i}/{len(targets)}] {pid} {desc}: empty text")
            failed.append((url, "empty text"))

    print(f"done: fetched={fetched} already_cached={cached_already} failed={len(failed)}")
    if failed:
        print("first 5 failures:")
        for u, e in failed[:5]:
            print(f"  {e}  {u}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
