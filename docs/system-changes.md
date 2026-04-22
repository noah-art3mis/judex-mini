# System-changes timeline — STF-side + judex-mini internal

Things that changed either on STF's side (forcing our hand) or on
ours (in response or for our own reasons). Consolidated from
`docs/data-dictionary.md § Schema history`, `docs/stf-portal.md`,
`docs/rate-limits.md`, and the `docs/progress_archive/` series.
Ordered most-recent-first. Each entry: what changed, when, why we
noticed, what we did, current status.

---

## STF-side changes (external, forced response)

These are things STF did that broke or altered our scraping contract.

| date        | change                                                                 | how we noticed                                                                | our response                                                                             | status                             |
|-------------|------------------------------------------------------------------------|-------------------------------------------------------------------------------|------------------------------------------------------------------------------------------|------------------------------------|
| **2022-12-19** | **DJe platform migration** — post-migration DJe content moved to `digital.stf.jus.br/publico/publicacoes`; old `portal.stf.jus.br/servicos/dje/listarDiarioJustica.asp?incidente=N` now serves only migration-redirect stubs ("Para consultar essa publicação, acesse https://digital.stf.jus.br/..."). | 2026-04-21 warehouse build-stats validation flagged `publicacoes_dje: 0.0% (threshold ≥ 5.0%)`. Manual browser verification of HC 267809 confirmed the new platform has the data. | **Diagnosed, not yet fixed.** `publicacoes_dje = []` across all 2023–2026 scrapes. Fix paths (see § DJe capture in `current_progress.md`): (1) andamentos-side DJe metadata regex (1–2 h), (2) Playwright for `digital.stf.jus.br` past AWS WAF (1–2 d), (3) AWS WAF reverse-engineering (don't). | ⚠ open; 0% DJe capture until fixed |
| *(unknown, post-2022-12-19)* | **AWS WAF challenge on `digital.stf.jus.br`** — new platform fronted by `token.awswaf.com` JS challenge. `requests` GET returns `202` + `challenge.js`. | Same 2026-04-21 investigation that caught the DJe migration. | Blocker for path 2 of DJe fix. Playwright or equivalent needed. | ⚠ blocking DJe Option 2 |
| *(ongoing)* | **`/processos/*` WAF on `portal.stf.jus.br`** — AWS WAF fronted by ALB, returns **403** (not 429) for rate-limit / bot signals. `python-requests/*` UA gets permanent 403. L2 per-IP reputation decays ~25 min per IP with sustained scraping; L3 cross-sweep reputation persists ≥ 21 h. | First-day scraping, then deepened by sweeps T/U/V analyses (see `docs/rate-limits.md § Wall taxonomy`). | Multi-layer response: Chrome UA, `retry-403` tenacity, `AWSALB` + `ASPSESSIONID` cookie handling, proxy pool with 270s session rotation, CliffDetector stop-on-collapse, cross-sweep cooldown discipline, dead-ID graveyard to skip unallocated pids. | ✅ mitigated; revisit when scaling past 16 shards |
| *(ongoing)* | **`abaSessao.asp` → JS-driven sessaoVirtual** — the `abaSessao.asp` fragment is a **JavaScript template**; actual session data served by `sistemas.stf.jus.br/repgeral/votacao?oi=<inc>&sessaoVirtual=<id>&tema=<N>` JSON endpoints. | Observed during sessao_virtual extractor work (pre-v7). | `extraction/sessao.py` hits the JSON endpoints directly (not `abaSessao.asp`). Captures `metadata`, `voto_relator`, `votes`, `documentos` from JSON source-of-truth. | ✅ wired via JSON path |
| *(ongoing)* | **`AWSALB` cookie is IP-bound** — STF's load balancer sticky-session cookie ties to exit IP. Changing IP mid-request invalidates it; cases need consistent IP across their 5–8 HTTP calls. | 2026-04-21 discussion around scrapegw sticky-session duration. | Driver rotates session IDs every 270s **by time, not per-request**. `--sticky-session=5min` on scrapegw is the safe floor (must exceed driver rotation window). | ✅ understood + encoded |
| *(pre-2026-04-17)* | **`#partes-resumidas` truncation artifact** — STF's partes-tab renders multi-lawyer IMPTEs as `"NOME E OUTRO"` on the "resumidas" variant; `#todas-partes` shows full list including all advogados + amici curiae + PROC. | v2 schema work (ad7cafa 2026-04-17). | Extractor switched to `#todas-partes`; `"E OUTRO"` became the stale-content sentinel for detecting pre-v2 JSON. | ✅ fixed at v2 |
| *(ongoing)* | **STF serves UTF-8 without declaring charset** — `requests` defaults to Latin-1 → mojibake on any non-ASCII content. | Early sweeps showed corrupt Portuguese text. | `scraper._decode` forces `r.encoding = "utf-8"` before reading `r.text`. Never bypass. | ✅ pinned; tests enforce |
| *(ongoing)* | **Host-counter split** — `portal.stf.jus.br` (case tabs) and `sistemas.stf.jus.br` (sessao_virtual, PDFs) have **independent WAF buckets**. Burning one doesn't burn the other. | Observed load-testing. | `baixar-pecas` (sistemas) runs independently of `varrer-processos` (portal); can run 16 shards of PDFs during/after portal throttling. | ✅ architectural gift; exploited |
| *(ongoing)* | **RISTF 2022 revision** — docket-handling rules changed for cases filed pre/post-revision. Affects classe codes and procedural movements. | Classification work (`docs/stf-taxonomy.md § Pre/post-RISTF 2022`). | Noted; no current blocker for scraping, relevant for downstream analysis. | ✅ documented in taxonomy |
| *(ongoing)* | **DataJud / `api_publica_stf` has no STF data** — returns 404 for STF cases. | Tried early, confirmed empty. | Don't re-check. We scrape STF's portal directly; CNJ's public API isn't a fallback. | ✅ known-dead; pinned |

## Internal schema migrations (our side, versioned)

| version | date           | what changed                                                                 | migration path                                               | status                                  |
|---------|----------------|------------------------------------------------------------------------------|--------------------------------------------------------------|-----------------------------------------|
| v1      | pre-2026-04-18 | Initial shape — raw HTML embedded, loose types, partes from `#partes-resumidas`. | —                                                            | retired                                 |
| v2      | 2026-04-18     | 6 breaking commits: HTML removed, `numero_origem: List`, `#todas-partes` for partes, TypedDicts for sessao/andamento, `schema_version` field added. | `scripts/renormalize_cases.py` re-runs extractors on cached HTML | retired (superseded by v3+)             |
| v3      | 2026-04-18     | Nested TypedDicts throughout, `*_iso` companions on dates, `outcome: OutcomeInfo` dict (not string), `status` → `status_http`, canonical `url` surfaced, bare dict on disk (not 1-element list). | Same renormalizer                                            | retired (superseded by v4+)             |
| v4 / v5 / v6 | 2026-04-18/19 | Extractor provenance on each Documento / andamento / DJe slot: `{text, extractor}`. Enables "which OCR produced this text?" queries. | Shape-only renormalize                                       | retired (superseded by v7)              |
| v7      | 2026-04-19     | `publicacoes_dje: List[PublicacaoDJe]` added. Nested types: `PublicacaoDJe{numero, data, secao, …, decisoes: List[DecisaoDJe]}`. Hit `portal.stf.jus.br/servicos/dje/*` URL family. | `reshape_to_v7` seeds empty list; full rebuild needs fresh DJe fetch. | **discovered 2026-04-21 to have been 0% functional on post-2022 data** — see DJe migration row above |
| **v8**  | 2026-04-19     | Strip inline `.text` / `.extractor` from every Documento slot in JSON; peca_cache becomes single source of truth. ~40% on-disk size reduction. | `reshape_to_v8` shape-only strip; no cache writes            | ✅ current                               |

## Internal infrastructure changes (our side, not schema)

| date        | change                                                                 | why                                                                        | status                                    |
|-------------|------------------------------------------------------------------------|----------------------------------------------------------------------------|-------------------------------------------|
| 2026-04-21  | **CliffDetector axis-B window-full gate**                              | Shard-o arm-B cliffed at 20/899 on a single 66.67s HTTP record where `p95==max` for n=MIN_OBS. | ✅ landed (this session)                  |
| 2026-04-21  | **Single `--proxy-pool FILE` flag in all modes** (consolidated `--arquivo-proxies` + `--proxy-pool-dir`) | UX: paste one file, launcher splits round-robin into N per-shard pools at `<saida>/proxies/`. One flag, one mental model, no mutually-exclusive pairing. | ✅ landed; `--proxy-pool-dir` and `--arquivo-proxies` removed from CLI + launcher |
| 2026-04-21  | **Warehouse build-stats validation**                                   | Silent `publicacoes_dje=0` regression went 3 days undetected. Threshold-driven warnings + `--estrito` gate for CI. | ✅ landed (and immediately caught the DJe regression) |
| 2026-04-21  | **16 shards + fresh proxies + sticky=5 as default** for year-backfills | 8-vs-16 A/B: 16 wins on wall-clock (0.17×) and cliffs (3 vs 8). H4 + H6 confirmed. | ✅ default; 8 retired for sustained jobs  |
| 2026-04-19  | **Interleave CSV sharding as default** (was range-partition)           | Range concentrated correlated workload (e.g. cached-vs-fresh URLs) in early shards. | ✅ default; `--estrategia-shard range` opt-in |
| 2026-04-19  | **Dead-ID tombstone infrastructure**                                   | ~15–20% of candidate pid space is unallocated (STF never assigned). Graveyarding them saves ~20% of per-sweep budget. | ✅ landed; 5,182 confirmed HC deads       |
| 2026-04-19  | **v8 DJe content path** (landed but broken for post-2022, see above)   | Capture full DJe index per case.                                           | ⚠ extractor-side broken by STF migration  |
| 2026-04-17  | **Selenium retired** — HTTP backend becomes only first-class path      | 16 Selenium extractors → 5 HTTP extractors + `http.py` dispatch. ~5× faster, no browser process overhead. | ✅ Selenium code frozen under `deprecated/`; `--backend selenium` errors out |
| *(ongoing)* | **HTML cache: dir → tar.gz**                                           | Per-case dirs with ~15 files each hit inode limits on the 80k-file corpus. | ✅ migrated; old format tolerant-read for cold backups |

## Known-gap graveyard

Things we know about but have actively decided not to fix, or can't fix without infrastructure we don't have.

| gap                                                               | why un-fixable / un-fixed                                                        | workaround                                                |
|-------------------------------------------------------------------|----------------------------------------------------------------------------------|-----------------------------------------------------------|
| Post-2022-12-19 DJe content                                       | New platform behind AWS WAF; needs Playwright (queued).                          | `andamentos` carry `"PUBLICADO O ACÓRDÃO, DJE N"` as structured rows with dates → ~80% of DJe-level metadata queries answerable without fixing. |
| Pre-2022 DJe re-fetch                                             | Old listing endpoint no longer returns server-rendered entries.                  | Frozen at what we have (~10 cases with DJe captured during the window the old endpoint still worked). |
| Playwright / browser automation                                   | Not set up; no current use.                                                      | Queued as prerequisite for DJe fix path 2.                |
| Second proxy provider                                             | Not contracted. scrapegw ASN degradation is single point of failure when it happens. | 16-pool spread within scrapegw; overnight cooldown discipline. |
| `api_publica_stf` (CNJ DataJud)                                   | Genuinely doesn't have STF data — 404s.                                          | Don't re-check. Scrape STF portal directly.               |
| `robots.txt` on `/processos/*`                                    | STF's `robots.txt` disallows crawling `/processos/*`. We operate in gray area.   | `NOTICE.md` acknowledges; one-sweep-per-day discipline; request-reduction backlog. |
| STF internal structure (endpoints + JSON shapes) as documentation | No public spec. Everything reverse-engineered.                                   | `docs/stf-portal.md` captures what we've figured out; update when we discover more. |

---

## How to use this doc

- **When you see unexpected 0% or 100% in warehouse stats**: scan the "STF-side changes" table first — a recent STF migration is the most common silent-regression cause. The `publicacoes_dje=0%` lesson of 2026-04-21 was a week-late detection; the build-stats validator now catches this class of issue, but knowing what *kinds* of STF changes to suspect shortens the triage.
- **When a scrape endpoint suddenly returns different content**: check if STF has split into `portal.*` vs `digital.*` or moved from server-rendered to JS-rendered. The pattern is recurring; they've migrated DJe, sessao (to JSON), and will likely do more.
- **When adding a new extractor**: write it against the cached HTML so schema bumps can replay offline via the renormalizer. `extraction/*.py` extractors take (html_str, …) and return structured data — never call fetchers directly.
- **When making a change that could land silently**: consider whether the warehouse build-stats validator's thresholds catch it. If not, add a new rate to `MIN_POPULATION_RATES` in `builder.py`.
