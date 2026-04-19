"""Side-by-side OCR provider comparison harness.

Walks the famous-lawyer HC target set, fetches each PDF, runs the
selected providers (default: mistral + chandra) and compares character
counts against the on-disk cache (which is the prior Unstructured /
pypdf baseline — whichever was monotonically longest).

Output goes to ``--out``:

    runs/active/<date>-ocr-bakeoff/
      ├── results.jsonl   — per-PDF: chars + walls + previews per provider
      ├── failures.jsonl  — provider-side errors
      └── report.md       — aggregated summary

Cost model (April 2026, ~5 pg/PDF blended): 55-PDF run ≈ $1.40 total
($0.55 Mistral sync + $0.83 Chandra). See `src.scraping.ocr.estimate_cost`.

Usage:

    PYTHONPATH=. uv run python scripts/ocr_bakeoff.py \\
        --out runs/active/2026-04-19-ocr-bakeoff \\
        --providers mistral,chandra \\
        --limit 55

    # Dry-run: just report the candidate pool, no API calls
    PYTHONPATH=. uv run python scripts/ocr_bakeoff.py --out /tmp/x --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from dotenv import load_dotenv

from src.scraping.http_session import _http_get_with_retry, new_session
from src.scraping.ocr import OCRConfig, extract_pdf, estimate_cost
from src.scraping.scraper import ScraperConfig
from src.utils import pdf_cache


SAMPLE_CHARS = 800


def _url_key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


FAMOUS_LAWYERS = (
    "TORON", "PIERPAOLO", "PEDRO MACHADO DE ALMEIDA CASTRO",
    "ARRUDA BOTELHO", "MARCELO LEONARDO", "NILO BATISTA",
    "VILARDI", "PODVAL", "MUDROVITSCH", "BADARO",
    "DANIEL GERBER", "TRACY JOSEPH REINALDET",
)
KEY_DOC_TYPES = frozenset({
    "DECISÃO MONOCRÁTICA",
    "INTEIRO TEOR DO ACÓRDÃO",
    "MANIFESTAÇÃO DA PGR",
})


@dataclass
class Candidate:
    url: str
    processo_id: Optional[int]
    doc_type: str
    cached_chars: int


def _has_famous_impte(rec: dict[str, Any]) -> bool:
    for p in rec.get("partes") or []:
        if not isinstance(p, dict):
            continue
        if (p.get("tipo") or "").upper() != "IMPTE.(S)":
            continue
        nome = (p.get("nome") or "").upper()
        if any(needle in nome for needle in FAMOUS_LAWYERS):
            return True
    return False


def _collect_candidates(
    cases_root: Path, *, min_chars: int,
) -> list[Candidate]:
    """Walk HC case files, return famous-lawyer + key-doc PDFs whose
    cached text is shorter than `min_chars` (i.e. rescue candidates).

    Inlined target collection that tolerates both dict-shaped and
    list-shaped case JSON (the latter is the post-2026-04 renormalized
    format that breaks `src.sweeps.pdf_targets.collect_pdf_targets`).
    """
    seen_urls: set[str] = set()
    candidates: list[Candidate] = []

    for f in sorted(cases_root.rglob("judex-mini_*.json")):
        try:
            doc = json.loads(f.read_text())
        except Exception:
            continue
        recs = doc if isinstance(doc, list) else [doc]
        for rec in recs:
            if not isinstance(rec, dict):
                continue
            if rec.get("classe") != "HC":
                continue
            if not _has_famous_impte(rec):
                continue
            for a in rec.get("andamentos") or []:
                if not isinstance(a, dict):
                    continue
                link = a.get("link") if isinstance(a.get("link"), dict) else None
                desc = ((link.get("tipo") if link else None) or "").strip()
                if desc not in KEY_DOC_TYPES:
                    continue
                url = link.get("url") if link else None
                if not url or not url.lower().endswith(".pdf"):
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                cached = pdf_cache.read(url) or ""
                if len(cached) >= min_chars:
                    continue
                candidates.append(Candidate(
                    url=url,
                    processo_id=rec.get("processo_id"),
                    doc_type=desc,
                    cached_chars=len(cached),
                ))
    return candidates


def _fetch_pdf(session: Any, url: str, *, timeout: int) -> Optional[bytes]:
    incidente = "5494703"  # any value; STF only checks the host of the Referer
    session.headers["Referer"] = (
        f"https://portal.stf.jus.br/processos/detalhe.asp?incidente={incidente}"
    )
    r = _http_get_with_retry(session, url, config=ScraperConfig(), timeout=timeout)
    if not r.content.startswith(b"%PDF"):
        return None
    return r.content


def _run_provider(
    pdf_bytes: bytes, *, provider: str, api_key: str, timeout: int,
) -> tuple[Optional[int], Optional[int], float, Optional[str], Optional[str]]:
    """Returns (chars, pages_processed, wall, full_text, error).

    `full_text` is the provider's complete output so the caller can
    persist it for human side-by-side reading — the prior (preview-only)
    signature threw that away and made quality comparison impossible.
    """
    cfg_kwargs: dict[str, Any] = dict(
        provider=provider, api_key=api_key, timeout=timeout, languages=("por",),
    )
    if provider == "chandra":
        cfg_kwargs.update(mode="accurate", poll_interval=3.0, poll_max_wait=600.0)
    config = OCRConfig(**cfg_kwargs)

    t0 = time.monotonic()
    try:
        out = extract_pdf(pdf_bytes, config=config)
    except Exception as e:
        return (None, None, time.monotonic() - t0, None, f"{type(e).__name__}: {e}")
    return (len(out.text), out.pages_processed, time.monotonic() - t0, out.text, None)


def _read_sample(out_dir: Path, rel: Optional[str], limit: int = SAMPLE_CHARS) -> str:
    """Read the first `limit` chars of a per-provider text file.

    Returns an empty string if the file is missing or the path is None so
    the side-by-side section degrades gracefully on provider failures.
    """
    if not rel:
        return ""
    path = out_dir / rel
    if not path.exists():
        return ""
    return path.read_text(errors="replace")[:limit]


def _write_report(out_dir: Path, rows: list[dict[str, Any]], providers: list[str]) -> None:
    by_provider: dict[str, list[dict[str, Any]]] = {p: [] for p in providers}
    for r in rows:
        for p in providers:
            entry = r["providers"].get(p)
            if entry and entry.get("chars") is not None:
                by_provider[p].append({
                    "url": r["url"], "doc_type": r["doc_type"],
                    "cached": r["cached_chars"],
                    "chars": entry["chars"], "pages": entry["pages"],
                    "wall": entry["wall"], "lift": (
                        entry["chars"] / r["cached_chars"]
                        if r["cached_chars"] > 0 else None
                    ),
                })

    lines: list[str] = ["# OCR provider bakeoff", ""]
    lines.append(f"- candidates tested: **{len(rows)}**")
    lines.append(f"- providers: {', '.join(providers)}")
    lines.append("")

    lines.append("## Per-provider headline")
    lines.append("")
    lines.append("| provider | n_ok | total chars | total pages | sum wall (s) | $ spent |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for p in providers:
        ok = by_provider[p]
        if not ok:
            lines.append(f"| {p} | 0 | — | — | — | — |")
            continue
        total_chars = sum(e["chars"] for e in ok)
        total_pg = sum(e["pages"] or 0 for e in ok)
        total_wall = sum(e["wall"] for e in ok)
        spent = (
            estimate_cost("mistral", total_pg, batch=False) if p == "mistral"
            else estimate_cost("chandra", total_pg, mode="accurate") if p == "chandra"
            else estimate_cost("unstructured", total_pg) if p == "unstructured"
            else 0.0
        )
        lines.append(
            f"| {p} | {len(ok)} | {total_chars:,} | {total_pg:,} | "
            f"{total_wall:.1f} | ${spent:.2f} |"
        )
    lines.append("")

    lines.append("## Lift vs current cache (cached → provider chars)")
    lines.append("")
    lines.append("Median + p10 + p90 of `chars / cached_chars` ratio per provider, "
                 "restricted to candidates where `cached_chars > 0`.")
    lines.append("")
    lines.append("| provider | n with cache | median lift | p10 lift | p90 lift |")
    lines.append("|---|---:|---:|---:|---:|")
    for p in providers:
        with_lift = [e["lift"] for e in by_provider[p] if e["lift"] is not None]
        if not with_lift:
            lines.append(f"| {p} | 0 | — | — | — |")
            continue
        with_lift.sort()
        n = len(with_lift)
        med = with_lift[n // 2]
        p10 = with_lift[max(0, int(n * 0.1))]
        p90 = with_lift[min(n - 1, int(n * 0.9))]
        lines.append(f"| {p} | {n} | {med:.2f}× | {p10:.2f}× | {p90:.2f}× |")
    lines.append("")

    lines.append("## Per-PDF detail (first 30, sorted by ascending cached chars)")
    lines.append("")
    head = ["url", "doc_type", "cached"] + [f"{p}_chars" for p in providers]
    lines.append("| " + " | ".join(head) + " |")
    lines.append("|" + "|".join(["---"] * len(head)) + "|")
    for r in sorted(rows, key=lambda r: r["cached_chars"])[:30]:
        u = r["url"].split("id=")[-1].split("&")[0]
        cells = [u, r["doc_type"][:15], str(r["cached_chars"])]
        for p in providers:
            entry = r["providers"].get(p) or {}
            cells.append(str(entry.get("chars") or "ERR"))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    lines.append(f"## Side-by-side samples (first {SAMPLE_CHARS} chars per provider)")
    lines.append("")
    lines.append(f"Columns show cached baseline + each tested provider. Full text "
                 f"lives under `texts/<url_key>.<provider>.txt` — diff with "
                 f"`diff -u texts/<key>.mistral.txt texts/<key>.chandra.txt`.")
    lines.append("")
    for r in sorted(rows, key=lambda r: r["cached_chars"]):
        key = r["url_key"]
        lines.append(f"### `{key[:12]}…` — {r['doc_type']}  (cached={r['cached_chars']})")
        lines.append("")
        lines.append(f"- url: <{r['url']}>")
        lines.append(f"- files: `texts/{key}.cached.txt`, "
                     + ", ".join(f"`texts/{key}.{p}.txt`" for p in providers))
        lines.append("")
        lines.append(f"**cached** ({r['cached_chars']} chars):")
        lines.append("```")
        lines.append(_read_sample(out_dir, r.get("cached_text_file")) or "(empty)")
        lines.append("```")
        lines.append("")
        for p in providers:
            entry = r["providers"].get(p) or {}
            chars = entry.get("chars")
            if entry.get("error"):
                lines.append(f"**{p}**: FAIL — {entry['error']}")
                lines.append("")
                continue
            lines.append(f"**{p}** ({chars} chars, {entry.get('pages') or 0} pg, "
                         f"{entry.get('wall') or 0}s):")
            lines.append("```")
            lines.append(_read_sample(out_dir, entry.get("text_file")) or "(empty)")
            lines.append("```")
            lines.append("")

    (out_dir / "report.md").write_text("\n".join(lines) + "\n")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path, help="Output directory.")
    ap.add_argument("--cases-root", type=Path, default=Path("data/cases/HC"),
                    help="Walk this dir for judex-mini_*.json (default: data/cases/HC).")
    ap.add_argument("--providers", default="mistral,chandra",
                    help="Comma-separated providers to test "
                         "(unstructured,mistral,chandra). Default: mistral,chandra.")
    ap.add_argument("--min-chars", type=int, default=5000,
                    help="Skip candidates whose cached text already has >= this many chars.")
    ap.add_argument("--limit", type=int, default=55,
                    help="Cap on candidates tested (default 55, matches the famous-lawyer baseline).")
    ap.add_argument("--throttle-sleep", type=float, default=1.0,
                    help="Seconds between PDFs.")
    ap.add_argument("--timeout", type=int, default=180, help="Per-call HTTP timeout.")
    ap.add_argument("--dry-run", action="store_true", help="Count candidates, no API calls.")
    args = ap.parse_args(argv)

    load_dotenv()
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    keys_env = {"unstructured": "UNSTRUCTURED_API_KEY",
                "mistral": "MISTRAL_API_KEY", "chandra": "DATALAB_API_KEY"}
    api_keys: dict[str, str] = {}
    for p in providers:
        if p not in keys_env:
            print(f"unknown provider {p!r}", file=sys.stderr); return 2
        v = os.environ.get(keys_env[p], "")
        if not v and not args.dry_run:
            print(f"ERROR: {keys_env[p]} not set", file=sys.stderr); return 2
        api_keys[p] = v

    print(f"collecting candidates under {args.cases_root} (min_chars={args.min_chars})...")
    candidates = _collect_candidates(args.cases_root, min_chars=args.min_chars)
    candidates.sort(key=lambda c: c.cached_chars)  # worst-cached first
    print(f"  {len(candidates)} famous-lawyer + key-doc candidates with cached < {args.min_chars}")
    if args.limit and len(candidates) > args.limit:
        candidates = candidates[: args.limit]
        print(f"  limited to first {args.limit}")

    # By doc-type breakdown
    from collections import Counter
    breakdown = Counter(c.doc_type for c in candidates)
    for k, v in breakdown.most_common():
        print(f"    {v:3d}  {k}")

    if args.dry_run:
        return 0

    # Cost gate
    est_pg = len(candidates) * 5
    print()
    print(f"estimated pages (~5 pg/PDF avg): {est_pg}")
    for p in providers:
        c = (estimate_cost("mistral", est_pg, batch=False) if p == "mistral"
             else estimate_cost("chandra", est_pg, mode="accurate") if p == "chandra"
             else estimate_cost("unstructured", est_pg))
        print(f"  estimated cost {p}: ${c:.2f}")
    print()

    args.out.mkdir(parents=True, exist_ok=True)
    texts_dir = args.out / "texts"
    texts_dir.mkdir(exist_ok=True)
    results_path = args.out / "results.jsonl"
    failures_path = args.out / "failures.jsonl"
    results_path.write_text("")
    failures_path.write_text("")

    session = new_session()
    rows: list[dict[str, Any]] = []
    t_start = time.monotonic()
    for i, cand in enumerate(candidates, 1):
        elapsed = time.monotonic() - t_start
        key = _url_key(cand.url)
        print(f"[{i:>3}/{len(candidates)}] {elapsed:>5.0f}s  cached={cand.cached_chars:>5}  "
              f"{cand.doc_type[:20]:20s}  {cand.url.split('id=')[-1].split('&')[0]}  ({key[:8]})")

        cached_text = pdf_cache.read(cand.url) or ""
        (texts_dir / f"{key}.cached.txt").write_text(cached_text)

        try:
            pdf = _fetch_pdf(session, cand.url, timeout=args.timeout)
        except Exception as e:
            print(f"        FETCH FAIL: {type(e).__name__}: {e}")
            with failures_path.open("a") as fh:
                fh.write(json.dumps({"url": cand.url, "stage": "fetch",
                                     "error": str(e)}) + "\n")
            continue
        if pdf is None:
            print(f"        not a PDF (skipped)")
            continue

        per_provider: dict[str, dict[str, Any]] = {}
        for p in providers:
            chars, pg, wall, full_text, err = _run_provider(
                pdf, provider=p, api_key=api_keys[p], timeout=args.timeout,
            )
            if full_text is not None:
                (texts_dir / f"{key}.{p}.txt").write_text(full_text)
            preview = (full_text or "")[:200].replace("\n", " ")
            per_provider[p] = {
                "chars": chars, "pages": pg, "wall": round(wall, 2),
                "preview": preview, "error": err,
                "text_file": f"texts/{key}.{p}.txt" if full_text is not None else None,
            }
            tag = "ok" if err is None else "FAIL"
            print(f"        {p:12s} {tag:4s}  {chars or 0:>6}c  "
                  f"{(pg or 0):>2}pg  {wall:>5.1f}s"
                  + (f"  -> {err}" if err else ""))
            if err:
                with failures_path.open("a") as fh:
                    fh.write(json.dumps({"url": cand.url, "provider": p,
                                         "error": err}) + "\n")

        row = {
            "url": cand.url, "processo_id": cand.processo_id,
            "doc_type": cand.doc_type, "cached_chars": cand.cached_chars,
            "url_key": key,
            "cached_text_file": f"texts/{key}.cached.txt",
            "providers": per_provider,
        }
        rows.append(row)
        with results_path.open("a") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        time.sleep(args.throttle_sleep)

    print()
    _write_report(args.out, rows, providers)
    print(f"wrote {args.out / 'report.md'}")
    print(f"wrote {results_path}  ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
