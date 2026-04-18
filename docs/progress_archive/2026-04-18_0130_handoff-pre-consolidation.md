# Handoff — judex-mini

Branch: `experiment/perf-bulk-data`
Status: landed locally, **not yet pushed**. Tip: `acac647` (or newer).
PR: https://github.com/noah-art3mis/edf-mini/pull/new/experiment/perf-bulk-data

This is the *temporal* doc — what's in flight, what's blocked, what's
next. For *conceptual* knowledge (how the portal works, how rate
limits behave, class sizes, perf numbers, where data lives), read:

- [`docs/data-layout.md`](data-layout.md) — where files live + the three stores.
- [`docs/stf-portal.md`](stf-portal.md) — URL flow, auth triad, field→source map.
- [`docs/rate-limits.md`](rate-limits.md) — WAF behavior, validated defaults, robots.txt posture.
- [`docs/process-space.md`](process-space.md) — HC/ADI/RE ceilings + density.
- [`docs/performance.md`](performance.md) — HTTP-vs-Selenium numbers, caching as the real lever.

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration (marimo notebooks, one-off scripts, raw JSON dumps). Safe to fill freely.
- **All non-trivial arithmetic via `uv run python -c`** — never mental math. See `CLAUDE.md § Calculations`. The rate-budget doc (`docs/sweep-results/2026-04-16-D-rate-budget.md`) is the cautionary tale.
- **Sweeps write a directory**, not a file. Layout in [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).

## What just landed

- **WAF-detection + proxy-rotation pipeline (2026-04-17 evening).**
  Four commits land the full Phase 1 / Phase 2 WAF-handling stack:
  - `b960568` — **CliffDetector** (rolling-window regime classifier) +
    **ProxyPool** (time-based proactive IP rotation, 270 s default,
    safely under STF's L1 window). Regime written into
    `sweep.log.jsonl` per record; stop-on-collapse replaces the
    circuit-breaker blind spot. `docs/rate-limits.md § Wall taxonomy
    and severity timeline` + operating-regime table documents the
    signal-to-response map.
  - `98ad84f` — **Credential redaction** in driver logs (`_redact_proxy`
    strips userinfo from every proxy URL before it hits stdout or
    `sweep.log.jsonl`) + **`.gitignore`** patterns for `/config/`,
    `proxies.txt`, `proxies*.txt`, `*.proxies`.
  - `6cde257` — **`--throttle-sleep` removed** from `run_sweep.py`
    CLI. D-data + V-evidence showed retry-403 + cooldowns dominate
    per-process pacing; proxy rotation addresses the binding
    constraint. Parameter retained in `iterate_with_guards()` for
    the PDF sweep (different host, real pacing effect).
  - **(in flight, this session)** — CliffDetector **WAF-shape fix**:
    the first proxy canary tripped false `collapse` because fast
    `NoIncidente` fails (HCs that don't exist in STF) were counted
    as WAF pressure. Fix narrows the fail-rate signal to records
    with `wall_s > 15 s` OR `http_status in {403, 429, 5xx}` OR
    non-empty `retries`. Plus a 30 s floor on reactive rotation so
    regime-driven rotations can't cascade into a panic drain of the
    pool. 221/221 unit tests green.
  - **Provider**: ScrapeGW, residential Brazilian IPs, 9-session
    pool rotating every 60 s in canary config. Stage 1 (curl) and
    Stage 2 (Python scraper) passed cleanly; Stage 3 canary run
    in progress after the fix lands. Bandwidth budget tracking is
    the binding economic constraint for full-backfill scale.
- **HC backfill sweeps Z / T / U / V** (2026-04-17 PM, same session). Total **+3,095 ok** this session (+ 510 from V partial = ~3,605 new HCs). All four used the new `--items-dir` flag (per-process JSONs native, no replay needed). Rows appended to `docs/sweep-results/2026-04-17-backfill-log.md`:
  - **Z** (2025, 258105..259104): 828 ok / 135 fail / 0 err — resumed after early SIGKILL; ~84 min wall.
  - **T** (2015, 128651..129650): 902 ok / 98 fail / 0 err — 61.7 min, first paper-era cohort, 2 WAF cycles absorbed.
  - **U** (2014, 123001..124000): 855 ok / 145 fail / 0 err — ~80 min, 3 WAF cycles absorbed (403×14 worst).
  - **V** (2013, 118201..119200): **partial** — 510 ok / 128 fail / 0 err at 638/1000, SIGTERM'd at ~57 min after persistent WAF pressure. Resumable via `--resume`.
- **Two-layer WAF model documented.**
  Sweep V's 15 403 cycles in 638 processes yielded enough data to separate the fast per-request throttle (layer 1, absorbable by retry-403) from the slow per-IP reputation counter (layer 2, only drained by no-request wall-clock time). Full analysis + cooldown parameter estimates + mitigation proposals (including IP rotation) in [`docs/rate-limits.md § Two-layer model (sweep V, 2026-04-17)`](rate-limits.md#two-layer-model-sweep-v-2026-04-17). Headline: **tighter throttle doesn't help, cooldowns between sweeps do**; 60–90 min between paper-era sweeps, overnight for full cold reset.
- **SSL cert verification bug fix + stranded-PDF recovery (2026-04-17 PM).**
  `src/utils/pdf_utils.py:88` narrowly whitelisted `sistemas.stf.jus.br` for
  `verify=False`, so `digital.stf.jus.br` (newer monocratic-decisions API, hit
  by 2023+ sweeps) silently failed SSL and dropped PDFs to URLs. Sweeps I, J, Z
  were affected. Broadened to any `*.stf.jus.br` host via `_is_stf_host()` +
  urlparse. Unit test `tests/unit/test_pdf_utils_ssl_hosts.py`.
  Separately found **3,700 PDF texts stranded in `data/pdf/<sha1>.txt.gz`**
  — post-sweep replay ran with `fetch_pdfs=False` so cached text didn't land in
  the JSONs. New `scripts/replay_sample_jsons.py` does surgical URL→cached-text
  substitution; healed all 3,700 across 1,484 sample JSONs in 15.6s.
  Remaining genuinely-missing from cache: 8 sistemas + 15 digital URLs.
- **Sweep driver writes per-process JSON natively.** New `--items-dir` flag on
  `scripts/run_sweep.py` eliminates the post-sweep cache-hot replay step
  (open TODO #1 in `docs/hc-who-wins.md`). On each ok result, atomic-writes
  `<items-dir>/judex-mini_<CLASSE>_<n>-<n>.json`. Tests in
  `tests/unit/test_sweep_items_dir.py`. 166/166 tests green.
- **First HC ground-truth fixture.** `tests/ground_truth/HC_158802.json` —
  Gilmar Mendes, 2018 vintage, 4 partes, 60 andamentos, non-empty
  sessao_virtual with votes. `validate_ground_truth.py` now covers 6 classes
  (ACO / ADI / AI / HC / MI / RE). Matched on first run.
- **Selenium retirement (phase 1).** 2026-04-17. 19 files moved to `deprecated/`, `main.py` defaults to `--backend http`, `--backend selenium` errors with a deprecation message, `selenium` moved to the `[selenium-legacy]` opt-in extra. 158/158 unit tests green post-move. Spec: `docs/superpowers/specs/2026-04-17-selenium-retirement.md`.
- **Validation sweeps A–E.** Full writeups under `docs/sweep-results/`. Highlights: C tripped the WAF at process 108 (surfaced the 403-not-429 behavior); D's three pacing probes produced the validated defaults; E ran 429/429 ok with the shipped defaults before being SIGTERM'd to free the WAF for G's density probe.
- **Robust sweep driver.** Append-only `sweep.log.jsonl` + atomic `sweep.state.json` + derived `sweep.errors.jsonl` + `report.md`. Resume, retry-from, signal-safe shutdown, circuit breaker. Shared primitives in `src/sweeps/shared.py`, reused by `src/sweeps/pdf_driver.py`.
- **Validated pacing defaults** (commit `2a2833d`). See [`docs/rate-limits.md § Validated defaults`](rate-limits.md#validated-defaults-commit-2a2833d).
- **HC class-size refresh (2026-04-16 evening).** Ceiling 270,994; ~216k extant. Bimodal density. Full numbers in [`docs/process-space.md`](process-space.md).
- **HC notebook-strand layout (2026-04-17).** Hub-and-strand pattern across five marimo notebooks. Full layout + findings in [`docs/hc-who-wins.md § Notebook layout`](hc-who-wins.md#notebook-layout--investigation-strands-2026-04-17).
- **FGV §b outcome rule adopted project-wide (2026-04-17).** Ported the *taxa de sucesso* definition from *IV Relatório Supremo em Números — O Supremo e o Ministério Público* (Falcão, Moraes & Hartmann, FGV DIREITO RIO, 2015, p. 50) into `src/analysis/legal_vocab.py` as `FGV_FAVORABLE_OUTCOMES` / `FGV_UNFAVORABLE_OUTCOMES`, plus a `CLASSE_OUTCOME_MAP` that declares which verdict labels can legitimately terminate each classe (writ / appeal / action families + universal terminators). Two test files pin the invariants: `tests/unit/test_legal_vocab_fgv.py` (exhaustive + disjoint partition), `tests/unit/test_classe_outcome_map.py` (every label is reachable, every classe set is a subset of `OUTCOME_VALUES`). Justification in [`docs/hc-who-wins.md § Research question`](hc-who-wins.md#research-question) — comparability with FGV's MP baselines, defensibility of a peer-reviewed rule, honest framing of `nao_conhecido` as a loss. Lit review updated at [`docs/hc-who-wins-lit-review.md § FGV IV Relatório`](hc-who-wins-lit-review.md). All five marimo notebooks under `analysis/` refreshed: `hc_explorer.py`, `hc_top_volume.py`, `hc_famous_lawyers.py` fully adopt the rule (imports + denominator swap from merits-only to final-only); `hc_admissibility.py`, `hc_minister_archetypes.py` keep their three-bucket decompositions (they're deliberately orthogonal to the FGV collapse) with added framing prose. 190/190 unit tests green. Semantic change readers will notice: `fav_pct` drops for advocates whose cases get heavy procedural rejection — `nao_conhecido` / `prejudicado` / `extinto` now count as losses instead of being excluded from the denominator.

## In flight

### HC backfill — V resume + W launch (NEXT UP)

**Current state after 2026-04-17 PM session**: 12 930 HCs scraped
across sweeps I–S (from earlier) + Z/T/U (full) + V (partial). Track 1
queue (pre-2016) is 1 done (T) + 1 done (U) + 1 partial (V) + W/X/Y
pending. Extension plan at [`docs/hc-backfill-extension-plan.md`](hc-backfill-extension-plan.md).

**Important: respect WAF cooldowns.** See [`docs/rate-limits.md § Two-layer model`](rate-limits.md#two-layer-model-sweep-v-2026-04-17) for the
full rationale. Short version: wait **≥30 min** before resuming V; wait
**60–90 min** between paper-era sweeps; prefer **overnight** before
launching W after V on the same IP. Tightening `--throttle-sleep`
doesn't help — cooldown is wall-clock time, not request spacing.

**Resume V** (completes HC 118743..119200):

```bash
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/hc_118201_119200.csv \
    --label hc_118201_119200 \
    --out docs/sweep-results/2026-04-17-V-hc-118201-119200 \
    --items-dir data/output/sample/hc_118201_119200 \
    --resume
```

**Launch W** (2012 fill, HC 113648..114647) — only after V is done *and* a
multi-hour cooldown:

```bash
uv run python -c "import csv; w=csv.writer(open('tests/sweep/hc_113648_114647.csv','w')); w.writerow(['classe','processo']); [w.writerow(['HC',n]) for n in range(113648,114648)]"
mkdir -p docs/sweep-results/2026-04-18-W-hc-113648-114647 data/output/sample/hc_113648_114647

PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/hc_113648_114647.csv \
    --label hc_113648_114647 \
    --out docs/sweep-results/2026-04-18-W-hc-113648-114647 \
    --items-dir data/output/sample/hc_113648_114647
```

### Sweep E close-out (deprioritized)

Sweep E stopped at 429/1000 via SIGTERM (clean) and is resumable. The
partial is sufficient evidence that the shipped defaults are
production-viable; a 1000-process ceiling datapoint is nice-to-have
but not necessary. The HC backfill takes priority over finishing E.

## Next steps, ordered

### 1. Resume V + launch W (Track 1 completion)

See § *In flight* above. Respect the cooldown windows. After V + W,
Track 1 pre-2016 coverage has 2013/2014/2015 all at ≥500 ok; the
original plan had X (2011) and Y (2010) as optional low-priority.
Revisit after V + W land.

### 2. Decide on IP rotation / mitigation

Based on session's two-layer WAF evidence, tighter throttle won't
shorten the remaining backfill. [`docs/rate-limits.md § Mitigation proposals`](rate-limits.md#mitigation-proposals) lists options ranked by cost:

- **Option 1** (cooldowns + schedule) is sufficient for the remaining
  queue spread over a few days.
- **Option 2** (proxy rotation) is the shortest path to reducing
  wall-clock; integration point is `src/scraping/http_session.new_session()`.
- **Option 5** (library-only distribution) is the posture-clean
  answer — keep parser + caching, ship without our IP doing the
  scraping.

Decision depends on whether the research question needs the full 216k
backfill or the current ~13k sample is sufficient. Hook back into
[`docs/hc-who-wins.md`](hc-who-wins.md) for the "does 1k cases answer
the question?" framing.

### 3. Circuit breaker blind spot for V-style patterns

Even with retry-403 + pacing, the V WAF pattern showed the existing
circuit breaker has a blind spot: it trips on `status=error`, but
tenacity-absorbed 403s stay `status=ok` regardless of wall time.

Implementation sketch for a secondary breaker: `collections.deque(maxlen=N)`
of recent `wall_s` values in `run_sweep.main`; trip if median of the
last N exceeds threshold (e.g. median wall > 20 s of recent 25 procs
= WAF engaged, stop). Keeps the `status=error` breaker from
`src/sweeps/shared.py` for the original failure mode. ~30 min of
work. Was called out in [`docs/rate-limits.md § Operational implications`](rate-limits.md#operational-implications).

### 4. Circuit breaker for the sweep driver (original note, superseded)

Even with retry-403 + pacing, pathological WAF escalation could
cascade. Abort the sweep if error rate crosses X % in a rolling
window of N processes.

Implementation sketch: `collections.deque(maxlen=N)` of recent statuses in
`run_sweep.main`; after each process, if more than X % of the deque is
non-ok, write errors, write state, exit 2 with a clear message.
Tunable via two CLI flags. Minimum viable: N=25, X=50 %. ~15 min of work.

### 3. Scope the HC deep dive

See "In flight" above. Probe HCs 200000..201000 first to measure
completion + rate before a bigger commitment. Ask the user what the
deep dive wants to answer — that shapes what data matters.

### 4. Outcome derivation

`StfItem` has no "winner" / "verdict" field. The data is scattered
and determining the outcome requires:

- Parsing `sessao_virtual[-1].voto_relator` for verdict phrases (`julgo procedente|improcedente|procedente em parte|nego provimento|dou provimento|não conheço`).
- Checking `sessao_virtual[-1].votes` — if `diverge_relator` is empty AND `pedido_vista` is empty or resolved in a later session, the relator's vote is the outcome.
- Checking `andamentos` for `TRANSITADO(A) EM JULGADO` and event names like `JULGADO PROCEDENTE`, `EMBARGOS RECEBIDOS EM PARTE` — the `complemento` field often carries the full decision text.

Worth adding as a derived field during parse (`src/scraping/extraction/sessao.py`)
OR as a post-processing pass. Brazilian legal vocabulary is richer than
the table above (`prejudicado`, `extinto sem resolução de mérito`,
`conversão em diligência`, …), so a first pass will have a meaningful
`unknown` / `pending` tail. Needed by the HC deep dive if it wants
outcome statistics.

### 5. Retry sweep C's 893 blocked processes

Sweep C's `docs/sweep-results/2026-04-16-C-full-1000.md` predates the
robust driver — flat markdown file, no `sweep.errors.jsonl`. So
`--retry-from` can't be pointed at it directly. Two options:

- **Re-run the full range under the new driver** once the posture is chosen. Uses `--resume` to skip the 107 already in cache.
- **Synthesize an errors.jsonl** from the C report's "status=error" rows (one-off script) to feed `--retry-from`.

First is more honest about wall time; second is faster to start.

### 6. Selenium retirement phase 2

Phase 2 (re-capture ground-truth fixtures under HTTP, audit
`deprecated/` self-containment) and phase 3 (CI check that no live
file imports from `src._deprecated`) still pending. Spec in
`docs/superpowers/specs/2026-04-17-selenium-retirement.md`.

### 7. PDF extraction quality

Currently PDFs go through `pypdf.PdfReader.extract_text(extraction_mode="layout")`.
You'll see warnings like `Rotated text discovered. Output will be incomplete.`
— STF stamps signed documents with rotated watermarks and the extractor
drops content around them.

**Unstructured-API OCR path** (`scripts/reextract_unstructured.py`,
2026-04-17) walks `pdf_targets` output, re-downloads cache entries
shorter than `--min-chars`, POSTs to Unstructured's SaaS API with
`strategy=hi_res`, overwrites `data/pdf/<sha1>.txt.gz` when the new
extract is longer. First production run:
`docs/pdf-sweeps/2026-04-17-famous-lawyers-ocr/`.

**Known gap**: the script does *not* route through
`src/sweeps/pdf_driver.run_pdf_sweep` — it runs an inlined loop, so
no `pdfs.state.json` / `pdfs.log.jsonl` / `requests.db` are produced.
Migration is a small follow-up (pass a PDF-+-OCR `FetcherFn` to
`run_pdf_sweep`). See the script's docstring for the full list.

### 8. Pre-existing cleanup (Selenium side)

Surfaced during the dedup review; untouched because Selenium path has
no automated coverage:

- `deprecated/extraction/extract_peticoes.py:28-30`: `data_match` assigned from `bg-font-info` then immediately overwritten by `processo-detalhes`. First match is dead.
- `deprecated/extraction/extract_deslocamentos.py:113-152`: `_clean_extracted_data` looks dead — `_clean_data_fields` is the one called from `_extract_single_deslocamento`. Verify with grep.
- `src/data/types.py:47-78`: commented-out dataclasses. Git remembers; delete.

Not blocking. Safe to defer.

## Known limitation — denominator composition and right-censoring

Under FGV's §b rule (now the project default — see the *FGV §b
outcome rule adopted* entry above), our `fav_pct` denominator is the
set of cases that have a recognized terminating verdict. Pending
cases are excluded, same as FGV's "excluindo interlocutórias e
liminares". This choice has real costs that matter more for us than
they did for FGV, because our vintage mix is more varied than theirs.

### What we do vs. what FGV did

| Dimension              | FGV IV Relatório (2015)                               | judex-mini                                                                      |
|------------------------|-------------------------------------------------------|---------------------------------------------------------------------------------|
| Denominator            | Decisões que encerram; exclui interlocutórias/liminares | Outcomes with a recognized verdict label; excludes `None` (`derive_outcome` returned None) |
| Pending cases          | Effectively absent — data cutoff Dec 2013 on 1988–2013 | Filtered out of the denominator, same as FGV in spirit                            |
| Vintage maturity       | Fully retrospective, uniform maturity                    | Mixed: sweep I (2023 HCs, mature) vs sweep H (April 2026 HCs, mostly pending)     |
| Parser-recall risk     | N/A — analytical DB, labels pre-assigned                 | `None` could mean "still pending" *or* "parser didn't recognize a real verdict"    |

### Pros of the current rule

1. **Interpretation is clean.** A rate computed over finished cases
   answers "of the cases that have been decided, what fraction went
   the filer's way?" — well-defined, defensible.
2. **Comparability with FGV.** Different denominators would force a
   methodology footnote every time we quote an FGV number next to ours.
3. **Matches lived experience.** An advocate whose case is still open
   hasn't lost it; classifying them as a loser penalizes them for
   STF queue time.
4. **Incrementally stable.** As pending cases resolve, the reported
   rate updates smoothly — no retroactive relabeling.

### Cons — why this bites us harder than it bit FGV

1. **Selection bias via processing speed.** This is the big one.
   STF decision latency is strongly outcome-correlated: `nego
   seguimento` monocráticas close in weeks, `concedido` on the
   merits typically requires a turma vote (6–18 months), contested
   plenary HCs can sit for years. At any snapshot, the finished
   sub-sample is **enriched in fast-processed outcomes** (denials,
   procedural rejections) and **depleted in slow-processed
   outcomes** (wins). Reported `fav_pct` on a fresh vintage
   systematically underestimates the eventual steady-state rate.
2. **Right-censoring thrown away.** A pending case is a classic
   *right-censored observation* — we know it has been open for T
   days without a terminating event, and T is informative about
   the hazard. Dropping it throws that information away.
   Kaplan-Meier on the "win curve" would use these cases properly.
3. **Denominator shrinkage on fresh data.** Sweep H (100 HCs from
   April 2026) has a huge `None` rate. Reporting `fav_pct` on
   that cohort means dividing by a tiny number — Wilson CIs are
   formally correct but point estimates read as meaningful when
   they aren't.
4. **Parser-gap pollution.** `None` conflates two different things:
   (a) **genuinely pending** (right-censored, real statistical
   phenomenon) and (b) **parser miss** (bug — a final verdict
   exists, we just don't recognize it). Improving the parser shifts
   reported rates without any change in the underlying population.
5. **Temporal incomparability within our own corpus.** Our 2023
   slice (mature) and our 2026 slice (fresh) have systematically
   different "fraction observed" rates. Any time-trend comparison
   is confounded with decision-latency trends unless (a) we
   equalize observation windows or (b) use survival methods.

### What FGV didn't have to worry about (and we do)

FGV analyzed a 25-year historical window with a hard cutoff five
months before publication — their pending fraction was tiny
relative to the population, and maturity was uniform across the
window. We run sweeps across vintages with very different
maturity. FGV's simple rule, ported naively, is **more biased for
us than it was for them**.

### Recommended mitigations (not yet implemented)

1. **Split `None` into `pending` vs `parser_gap`.** Heuristic: if
   the case has andamentos but none match VERDICT_PATTERNS *and*
   the last andamento is within the last 90 days → `pending`; else
   → flag for parser-gap review. Cleans up con (4) immediately.
2. **Report %-pending alongside every `fav_pct`.** Transparency:
   readers see "60 % final, 40 % pending — preliminary."
   Addresses con (3) without any methodology change.
3. **Sensitivity analysis via bracketing.** Report two bounds: one
   assuming all pending resolve favorably (upper), one assuming
   all unfavorably (lower). Narrow band → rate is stable; wide
   band → flag as under-determined. Standard in
   partial-identification work. Addresses cons (1) and (3).
4. **Kaplan-Meier win curves on mature vintages.** For the 216 k
   backfill where right-censoring will dominate, adopt a survival
   framework. Cox PH on andamentos timelines is the natural
   extension. Lit review §11 already flagged this.

Bottom line: we're doing exactly what FGV does — right choice for
comparability, wrong choice for rigor on fresh data. The four
mitigations above are the upgrade path when we publish the 216 k
backfill numbers.

## Known gaps in the `sessao_virtual` port

Worth knowing if you're debugging:

- **Vote categories are partial** — only codes 7/8/9 land in the final `votes` dict. See [`docs/stf-portal.md § sessao_virtual`](stf-portal.md#sessao_virtual--not-from-abasessao).
- **`documentos` values are mixed types**: string with extracted text (success) or original URL (fetch failed). Consumers must check `startswith("https://")`. Re-running the scraper picks up where failures left off via the URL-keyed PDF cache.
- **Tema branch has only one fixture test (tema 1020).** If you see drift there, probe another tema + add a fixture.
- **No Sessão-branch support for "suspended" lists** — if STF ever returns a listaJulgamento mid-suspension with a different JSON shape, `parse_sessao_virtual` will pass through missing fields as empty strings. No known case.

## How to run things

```bash
# Unit tests (48 tests, <3s)
uv run pytest tests/unit/

# Ground-truth validation (HTTP parity against 5 fixtures)
PYTHONPATH=. uv run python scripts/validate_ground_truth.py

# HTTP scrape, one process, with PDFs
uv run python main.py -c ADI -i 2820 -f 2820 -o json -d data/output/test --overwrite

# HTTP scrape without the PDF fetch (faster, documentos stay as URLs)
uv run python main.py --no-fetch-pdfs -c AI -i 772309 -f 772309 -o json -d data/output/test --overwrite

# Wipe caches
rm -rf data  # HTML fragments, sessao JSON, PDF text
```

### Marimo notebooks under `analysis/`

HC analysis lives in five marimo notebooks — see
[`docs/hc-who-wins.md § Notebook layout`](hc-who-wins.md#notebook-layout--investigation-strands-2026-04-17).

```bash
# interactive editor (opens a browser tab, full reactivity):
uv run marimo edit analysis/hc_famous_lawyers.py

# view-only:
uv run marimo run analysis/hc_famous_lawyers.py

# view-only, no auto-open browser — useful when running remotely
# (WSL/SSH/container). Marimo prints a localhost URL; forward the port first.
uv run marimo run --headless analysis/hc_famous_lawyers.py
```

Swap `hc_famous_lawyers.py` for any of `hc_explorer.py`,
`hc_top_volume.py`, `hc_minister_archetypes.py`, `hc_admissibility.py`.

#### Exporting notebooks to HTML for sharing

HTML export is the preferred artifact format: plotly charts stay
**interactive** (hover, zoom, pan) because marimo embeds plotly.js +
the figure JSON directly in the file. No server needed to open, no
extra deps (HTML export is built into marimo itself; PDF export was
tried and rejected — it rasterizes the charts and looks worse).

```bash
# all five notebooks → exports/html/*.html  (gitignored)
./scripts/export_notebooks_html.sh

# custom output dir
OUT_DIR=/tmp/share ./scripts/export_notebooks_html.sh

# one-off, single notebook
uv run marimo export html --force analysis/hc_explorer.py -o /tmp/x.html
```

Typical sizes: `hc_explorer.html` ~3.7 MB (hub, heaviest), others
90–145 KB. Each export runs the notebook from scratch in a headless
kernel — ~13 s per notebook on this machine, ~1 min for the full
batch. If you edit a notebook and need to re-share, re-run the
script; it regenerates in place (`--force`).

Known benign warning during export: `hc_explorer.py:40` emits a
`FutureWarning` about the deprecated `pd.option_context("mode.use_inf_as_na", True)`
call. Does not affect output; flagged here because you'll see it
scroll by.

## Running sweeps

```bash
# One-shot sweep over a CSV of (classe, processo) pairs
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/shape_coverage.csv \
    --label my_sweep \
    --parity-dir tests/ground_truth \
    --out docs/sweep-results/<date>-<label>

# Long sweep with proxy rotation (the WAF lever that actually helps)
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/full_range_adi.csv \
    --label long_sweep \
    --proxy-pool ~/.config/judex-mini/proxies.txt \
    --parity-csv output/judex-mini_ADI_1-1000.csv \
    --wipe-cache \
    --out docs/sweep-results/<date>-<label>

# Resume a sweep (skip already-ok processes)
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv <same-csv> --label <same> --out <same-dir> --resume

# Retry only the failures from a prior sweep
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --retry-from docs/sweep-results/<dir>/sweep.errors.jsonl \
    --label <label>_retry \
    --out docs/sweep-results/<date>-<label>-retry
```

**Stopping a running sweep cleanly.** The driver installs SIGINT/SIGTERM
handlers (`scripts/run_sweep.py:517-524`). On signal it finishes the
in-flight process, breaks the loop, then writes `sweep.errors.jsonl` +
`report.md` and exits with its normal status code.

```bash
# find the python process
ps -ef | grep run_sweep | grep -v grep

# clean stop (preferred) — finishes the in-flight process, writes all files
kill -TERM <pid>

# or Ctrl-C if the sweep is in the foreground (same SIGINT path)
```

`SIGKILL` (`kill -9`) is a last resort: per-record writes are atomic so
`sweep.log.jsonl` + `sweep.state.json` are always consistent and the
run is resumable via `--resume`, but `sweep.errors.jsonl` and
`report.md` won't be written. A `--resume` run (even one that skips
everything) regenerates both at its end.
