# Performance — where the real lever is

What dominates wall-clock time in a sweep, and why caching (not raw
per-request speed) is the only knob worth tuning at scale.

The Selenium backend was retired 2026-04-17 — `--backend selenium`
errors out. The historical HTTP-vs-Selenium bench that motivated the
retirement is preserved at
[`docs/reports/2026-04-17-http-vs-selenium-benchmark.md`](reports/2026-04-17-http-vs-selenium-benchmark.md);
this doc covers HTTP-only operating regimes.

See also:
- [`docs/stf-portal.md`](stf-portal.md) — per-tab latencies live there too.
- [`docs/rate-limits.md`](rate-limits.md) — the ceiling at scale.
- [`docs/data-layout.md`](data-layout.md) — cache locations.

## TL;DR

The scraper's wall-clock has **two regimes** with different ceilings:

1. **Cold per-request floor.** A fresh case is ~0.87 s on HTTP
   (incidente lookup + detalhe + 9 tabs in parallel). A cache hit on
   the same case is ~0.27 s. This number doesn't extrapolate to a
   sweep — see #2.
2. **WAF ceiling at sweep scale.** STF's WAF throttles per-IP
   reputation over 100+ consecutive requests; throughput collapses
   to a ceiling well below the cold floor, regardless of client
   choice. The actual production lever is **proxy rotation across
   shards** (4-shard validated at zero-403 over 20.1 h continuous;
   see [`rate-limits.md § 4-shard proxy-rotation validation`](rate-limits.md#4-shard-proxy-rotation-validation-2026-04-18))
   and **caching everything that's been fetched once**.

**Practical implication**: the `data/raw/` cache (HTML fragments and
peça bytes, both content-addressed) is what makes iteration fast.
Once a case's HTML is on disk, re-extraction is free — and that's
where development time actually lives.

## Cold vs cache hit — the production lever

| Operation            | Cold     | Cache hit | Ratio |
|----------------------|---------:|----------:|------:|
| Full HTTP scrape     | 0.87 s   | 0.27 s    |  3.2× |
| Andamentos re-parse  | ~0 (from fragment) | 3.5 ms | — |
| PDF text (ADI 2820)  | ~12.9 s  | 0.18 s    | ~70× |

The HTML fragment cache (`data/raw/html/<CLASSE>_<N>.tar.gz`) is a
~60× speedup on re-scrapes of the same process. The URL-keyed peça
text cache (`data/derived/pecas-texto/<sha1(url)>.txt.gz`) is a ~70×
speedup on re-reads of the same PDF. **Iterating on extractor code
against a cached corpus runs effectively at local-CPU speed**; the
scraper never has to talk to STF.

This is why CLAUDE.md insists the cache contracts are load-bearing
and why sweeps wipe-cache explicitly rather than by default.

## OCR pass (provider-selectable via `extrair-pecas`)

Image-only scans in the andamentos PDFs (older decisões monocráticas
and acórdãos pre-2020 are frequently stamped scans, not text-born
PDFs) need OCR to be usable. `extrair-pecas --provedor <name>` reads
bytes from `data/raw/pecas/<sha1>.<ext>.gz` (populated by
`baixar-pecas`), dispatches via `judex.scraping.ocr.extract_pdf`,
writes text + `<sha1>.extractor` sidecar back to the cache.

After the **2026-04-30 OCR bakeoff** (see
[`docs/reports/2026-04-30-ocr-bakeoff.md`](reports/2026-04-30-ocr-bakeoff.md))
**Tesseract on Modal CPU is the production-scale recommendation**:
1.04 % median CER overall, 0.82 % on scanned, 14× cheaper than
Mistral, opt in via `--provedor tesseract_modal`. The CLI default
remains `pypdf` until the cutover lands.

The **improvement signature** is consistent across providers: pypdf
returns ~2 000–5 000 chars (headers + stamps + stray running text)
for a scanned PDF; OCR returns ~10 000–40 000 chars of body text, a
4–10× per-doc gain. PGR manifestações tend to be text-born and pypdf
reads them cleanly — they don't benefit from OCR (and one verify-pass
showed OCR strictly shorter than pypdf on such a doc).

For per-provider cost / wall trade-offs at sweep scale, see
[`docs/cost-estimates.md § OCR provider tradeoffs`](cost-estimates.md#ocr-provider-tradeoffs).

## Field coverage on the HTTP path

All ~27 fields the Selenium scraper emitted are reachable from the
same HTML fragments the browser eventually renders — we just fetch
them directly instead of letting jQuery do it. The field-to-source
map lives in [`stf-portal.md § Field → source map`](stf-portal.md#field--source-map).

Validated against `tests/ground_truth/*.json`:

| Fixture              | Wall  | Result                             |
|----------------------|------:|------------------------------------|
| ACO_2652             | 0.81s | 2 diffs (both non-bugs, see below) |
| ADI_2820_reread      | 0.76s | MATCH                              |
| AI_772309            | 0.48s | MATCH                              |
| MI_12                | 0.49s | MATCH                              |
| RE_1234567           | 0.51s | MATCH                              |

The two ACO 2652 diffs are **not scraper bugs**:

1. `assuntos` text drift — live site has `'... CADIN/SPC/SERASA/SIAFI/CAUC'`, fixture captured `'... CADIN'`. STF updated the assunto taxonomy since the fixture was recorded.
2. `pautas: []` vs `null` — fixture inconsistency. ACO has `null`; the other four have `[]`. Current HTTP path produces `[]`, matching 4/5 fixtures and the former Selenium behavior.

Run yourself: `uv run python scripts/validate_ground_truth.py`.

## Sweep-scale throughput — HTTP-only

Small = AI 772309–shaped (2 andamentos, 4 partes). Heavy = a case
with full docket depth.

| Approach                                  | Per process (small) | Per process (heavy) | 100 processes | 1000 processes |
|-------------------------------------------|-------------:|-------------:|--------------:|---------------:|
| HTTP serial                               | ~2.5 s       | ~5 s         | ~8 min        | ~1.4 h         |
| HTTP, tabs parallel                       | ~1.5 s       | ~2 s         | ~3 min        | ~33 min        |
| HTTP, 1 worker + retry-403 (sweep E)      | ~3.6 s       | ~3.6 s       | ~6 min        | ~60 min        |
| **HTTP, 4-shard + proxy rotation** (measured, 2026-04-18) | ~0.98 s aggregate | ~0.98 s aggregate | ~1.5 min | ~16 min |
| HTTP, tabs + processes ‖8 (aspirational)  | ~0.2 s amort.| ~0.3 s amort.| ~25 s         | ~4 min         |

The **per-process speedup is larger on heavier cases**. Click-gated
tabs (`andamentos`, `peticoes`, `recursos`) are where the cost
historically concentrated; HTTP+parallel pays nothing for those.

**The 4-shard row is empirically validated** at full-sweep scale —
**20.1 h continuous** across two sessions (8.5 h on 2026-04-17 +
11.6 h on 2026-04-18), zero HTTP 403/429/5xx, 54 841 ok / 72 646
processed (real-fail rate 0.016 %). See `rate-limits.md § 4-shard
proxy-rotation validation`. Aggregate throughput is ~0.98 s/case
(~1.02 rec/s) across 4 workers running on disjoint ScrapeGW proxy
pools; per-worker rate is ~0.19 ok/s, essentially unchanged from
single-worker sweep E. **Rotation doesn't make individual workers
faster — it lets them run in parallel without cross-blocking on a
shared WAF counter.** Scaling is linear in shard count so long as
each shard has its own proxy pool.

The "processes ‖8" row remains aspirational because it assumed
no WAF ceiling at all; we'd need to verify that 8-way concurrency
on 80+ proxy sessions still holds the 0 × 403 invariant. At
4× validated, the pace is ~3.6× the single-worker rate — a
linear speedup worth taking.

> **Note on the unified pipeline.** The numbers above were measured
> on the legacy `varrer-processos` shard launcher (per-process
> `--shards N --proxy-pool FILE`). Under `judex executar`
> ([ADR-0005](adr/0005-unified-pipeline.md)), the same posture is
> in-process per-Pool round-robin; the WAF-ceiling math is unchanged
> (per-IP reputation is the load-bearing physics, not the launcher
> mechanism). A re-bench under `executar` is on the slice-6 list.

## What this does NOT fix

- **Server-side rate limiting.** More workers hit the ceiling faster, not past it. See [`rate-limits.md`](rate-limits.md).
- **PDF parsing cost.** `pypdf.PdfReader.extract_text(extraction_mode="layout")` and the OCR providers run at local-CPU / external-API speed. HTTP doesn't move that number.
- **Site ToS and courtesy.** Faster scraping without proper caching is the same load concentrated in time. The cache does the ethical work, not the client choice.

## What we intentionally didn't do

- **Playwright instead of Selenium.** Both drive a real browser; the floor cost (startup + full page render) is the same. Playwright would have bought maybe 1.5–2×, not the 10× HTTP delivered. Moot now that Selenium is retired and HTTP is the only first-class backend.
- **UA spoofing.** Gray-area legally, brittle technically, and the Chrome UA plus residential-proxy session already presents as a normal user.
- ~~**IP rotation**~~ *is now the canonical approach* — `--proxy-pool` with ScrapeGW residential sessions, validated at 4-shard concurrency over **20.1 h cumulative continuous load** with zero HTTP 403/429/5xx. See [`rate-limits.md § 4-shard proxy-rotation validation`](rate-limits.md#4-shard-proxy-rotation-validation-2026-04-18). The `robots.txt` posture question in [`rate-limits.md § The unresolved policy question`](rate-limits.md#the-unresolved-policy-question--robotstxt) still applies.
- **Chase a bulk dataset.** STF is not on DataJud; Corte Aberta is aggregates-only; commercial aggregators are paid and inappropriate for research. Scraping the portal is the only path.
