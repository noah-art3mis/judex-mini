# Handoff — judex-mini perf/bulk-data work

Branch: `experiment/perf-bulk-data`
Status: landed locally, **not yet pushed**. Tip: `acac647` (or newer if this handoff has been committed). ~19 commits ahead of `main`.
PR: https://github.com/noah-art3mis/judex-mini/pull/new/experiment/perf-bulk-data

Start by reading `docs/perf-bulk-data.md` for the original investigation (DataJud dead-end, STF portal mechanics, 5.7×/~20× perf claim with caveats). Then skim `docs/superpowers/specs/2026-04-16-validation-sweep-design.md` for the sweep plan and `docs/sweep-results/` for what actually happened. This note only covers what's unfinished and why.

## Working conventions

- **`analysis/`** — git-ignored scratch folder for this-session exploration (notebooks, one-off scripts, raw JSON dumps you don't want in version control). Safe to fill freely.
- **All non-trivial arithmetic via `uv run python -c`** — never mental math. See `CLAUDE.md § Calculations`. The rate-budget doc (`docs/sweep-results/2026-04-16-D-rate-budget.md`) is the cautionary tale.
- **Sweeps write a directory**, not a file (`<out>/sweep.log.jsonl` + `sweep.state.json` + `sweep.errors.jsonl` + `report.md`). Old sweep A/B reports are single `.md` files from the pre-state driver; they stay as-is.
- **Calculations in this doc were re-run with python** as of the `acac647` commit. Any new numbers you add should follow the same rule.

## HC who-wins — investigation-strand layout (2026-04-17)

Reorganised the `analysis/` marimo notebooks around a hub-and-strand
pattern. `hc_explorer.py` is the hub (existing — case drilldown,
EB-shrunk lawyer/minister grant rates, affinity heatmap, narrative
deep dives on Gilmar's Súmula-691 exception and the Alexandre de
Moraes / Defensoria-MG archetypes). Four narrow sibling notebooks,
each answering one question, each pointing back at the hub:

| Notebook | Question |
| --- | --- |
| `hc_explorer.py` | Hub. Full treatment + case drilldown. Now carries an **Investigation index** cell near the top. |
| `hc_famous_lawyers.py` | Do marquee criminal-defense lawyers (Toron, Bottini, Kakay, …) show up in HCs, with what outcomes? |
| `hc_top_volume.py` | Who files the most HCs? HC-mill practices + Defensoria breakdown + OAB-state geography. |
| `hc_minister_archetypes.py` | Stacked wins / losses / procedural bar per minister — grantor vs denier vs gatekeeper at a glance. |
| `hc_admissibility.py` | Who reaches the merits? `nao_conhecido` rate per minister. |

`analysis/` is git-ignored scratch so these won't be on a fresh
checkout — recreate from this doc if needed. The earlier
`hc_deep_dive.py` is deleted (it duplicated the hub).

**How the slicing was chosen.** The lawyer-side splits into "famous
name matching" (curated list) and "volume-by-count" (raw impetrante
ranking) — different populations, different dedup strategies, so
different notebooks. The minister-side splits into "how do they
dispose of cases" (3-way disposition shape) and "do they reach the
merits" (admissibility gate) — orthogonal axes that jointly
generate the archetype story.

Ran against `output/sample/hc_*` — 8 954 HCs across the sampled
ranges (2023-vintage dominated).

**Findings (sample-conditional, write up with appropriate hedges):**

1. **Public defenders dominate volume.** DPU 591, DPE-SP 287, DPE-MG
   74. Any private lawyer is a rounding error against the Defensoria
   baseline.
2. **Top-volume *private* impetrantes are HC-mill practices, not
   marquee names.** Victor Hugo Anuvale Rodrigues tops the list at
   ~86 (solo + "E Outro" folded); Cicero Salum do Amaral Lincoln 70;
   Fábio Rogério Donadon Costa 50. Fav% near the corpus baseline.
3. **Marquee criminal-bar lawyers file in single digits** on this
   HC sample. Toron 11; Bottini 6; Pedro M. de Almeida Castro
   (Kakay firm) 2; everyone else ≤ 2. Famous ≠ volume at STF.
4. **Minister identity dominates lawyer identity for HC grant rate.**
   Once per-minister cells are restricted to ≥ 3 merits decisions,
   the famous list empties out entirely — only the Defensorias have
   enough volume to read a pattern per relator. What shows up there
   (see `hc_minister_archetypes.py` + `hc_admissibility.py`):
   - Fachin, Celso de Mello: 67–100 % for Defensorias.
   - Toffoli, Barroso: 70–80 % for DPU.
   - Gilmar, Lewandowski, Cármen: baseline (~25–50 %).
   - **Alexandre de Moraes: 5 % (2/38) for DPU, 7 % (1/14) for
     DPE-SP.** Same counsel, same pleadings, ~15× spread across
     ministers.
   Implication: at this sample size the relator draw is a larger
   factor than counsel. The famous-lawyer premium (if real) is
   invisible. Hub notebook `hc_explorer.py` already had the
   narrative treatment of this (archetype section + Alexandre
   opposite-of-Gilmar case study); the new sibling notebooks
   add a stacked-bar visualisation (`hc_minister_archetypes.py`)
   and the pure admissibility axis (`hc_admissibility.py`).
5. **Admissibility rate spans 4 %–98 % across relators.** Marco
   Aurélio engages on merits for ~96 % of his HCs; the Ministro
   Presidente bucket dismisses ~98 % procedurally. Same outcome
   label ("low grant rate") can mean completely different things
   — see `hc_admissibility.py`.
6. **Caveats bank**: ~68 % of STF HCs end in `nao_conhecido` (not
   heard on merits), so `N` overstates the decidable sample.
   Substring name-matching means "ALMEIDA CASTRO" picks up multiple
   lawyers at a firm; we narrowed to "PEDRO MACHADO DE ALMEIDA
   CASTRO". Selection bias uncontrolled — lawyers self-select into
   case types. Not causal.

**Doesn't block scraping**; the sample corpus is adequate for the
current question. Expanding to RHC or AP would give more coverage of
the marquee criminal bar (Toron, Bottini et al. more likely to appear
in criminal appeals than in HCs).

**Non-notebook utilities promoted out of `analysis/`** (2026-04-17):

- `scripts/class_density_probe.py` (was `analysis/class_density_probe.py`)
  — CLI probe; lives alongside `scripts/run_sweep.py`.
- `src/utils/hc_calendar.py` + `src/utils/hc_id_to_date.json`
  (were `analysis/hc_calendar.py` + `analysis/hc_id_to_date.json`)
  — importable calendar utility; `from src.utils.hc_calendar import
  id_to_date, year_to_id_range`.

`analysis/` now contains only marimo notebooks + `_stats.py` (shared
stats helpers for the notebooks).

**Still flagged, not acted on** — confirm before deleting:

- `analyse.ipynb` (334 KB), `andamentos.ipynb` (67 KB),
  `andamentos_cluster.ipynb` (35 MB) at the project root are
  **tracked in git** but look like pre-handoff exploration. The 35 MB
  andamentos_cluster.ipynb in particular is a big git-LFS-shaped
  problem. Candidates for either cleaning outputs + committing
  skinny versions, or moving to `analysis/`.

## What happened since the last handoff

**Validation sweeps A, B, C completed** (`docs/sweep-results/2026-04-16-{A,B,C}-*`):

- **A — shape-coverage smoke (12 processes, 6 classes).** 12/12 pass. No schema surprises; HC class exercised for the first time. One substitution: AI 828 didn't exist on STF → replaced with AI 500000.
- **B — throttle probe (50 ADIs, cold + warm).** 50/50 cold in 81 s, 0 retries. Warm pass p50 0.14 s — the ~60× cache speed-up `docs/perf-bulk-data.md` predicted.
- **C — full ADI 1–1000 sweep.** **STF blocked us at process #108** with HTTP 403 (not 429) from `listarProcessos.asp`. 107 ok; 893 fast-fail 403s. In the pre-ban window: **~0.79 s/process = 9.7× faster than Selenium's 7.65 s/process**. Selenium baseline for the same range: 77.6 min / 609 ok (measured from `extraido` timestamps in `output/judex-mini_ADI_1-1000.csv`). Selenium completed the range because it's 10× slower per process and stayed under the rate gate; HTTP at current posture tripped it.

**Robust sweep state/log machinery landed** (`scripts/sweep_state.py`, commit `018f26d`):

- Every sweep run writes an append-only `sweep.log.jsonl` (fsynced per record) + atomic `sweep.state.json` + derived `sweep.errors.jsonl`. Report at `report.md`.
- `--resume` skips already-ok processes. `--retry-from <errors.jsonl>` re-runs only failures from a prior sweep.
- SIGINT/SIGTERM stop cleanly after the in-flight process. Recovery path rebuilds `sweep.state.json` from the log if it's missing.
- `AttemptRecord` carries structured fields (`error_type`, `http_status`, `error_url`); report tables aggregate errors by bucket + endpoint.
- Opt-in flags: `--retry-403` (`ScraperConfig.retry_403`) treats 403 as a retriable throttle signal via tenacity; `--throttle-sleep <s>` paces between processes.
- **Breaking change**: `run_sweep.py --out` is now a directory, not a markdown file path. Old sweep A/B reports at `docs/sweep-results/2026-04-16-A-shape-coverage.md` are flat files from the pre-state driver; they stay as-is. New sweeps use the directory layout.

**Block-scope probe** (not committed, see conversation log): STF's sweep-C 403 block was session-agnostic and lifted within minutes. Non-browser UAs (`curl/*`) get permanent 403. Browser-shaped UAs all pass — our default Chrome UA is fine. Implication: the block isn't UA/cookie-based; it's rate/behavior-based.

## Next major goal — Habeas Corpus deep dive

**User's stated next step**: scrape all Habeas Corpus cases and take a deep dive on the resulting data.

Things to think through before launching:

- **Scale.** HC is the highest-volume class at STF. There are well over 200 000 HCs on file (sweep A confirmed HC 82959 and HC 126292 exist). At the current validated throughput (~3 s per process with defaults) a full backfill is **~170 hours of wall time** from one IP. That's an 8-day continuous run, assuming STF's WAF keeps tolerating the 2 s-paced + retry-403 posture at scale. Sweep E (below) is testing 1000 ADIs as a first proof point — if E completes cleanly, a 10× or 100× run becomes more credible.
- **Decomposition options**:
  1. **Time-sliced**: HCs filed in e.g. 2020–2025. Unknown up-front which `processo_id` ranges correspond; would need a probe sweep (one per year) to find boundaries, then backfill the range.
  2. **Sample-first**: a few thousand HCs across a range, enough for the deep dive's analysis. Ship the sweep tool + let the user re-run for more scale later.
  3. **Relator-sliced**: scrape HCs by relator. No current API for this — would need the listagem endpoint (`listarProcessos.asp` with different params) and is more work.
- **Deep dive needs**: not scoped here. Likely wants party-type breakdown, outcome distribution (see "Outcome derivation" below), relator patterns, timeline analysis. Ask before building.
- **Robots.txt**: still unresolved. HC is a much bigger footprint than ADI — posture question becomes more pressing.

**Size of the HC space (binary-searched + density-probed 2026-04-16)**:

| class | highest extant processo_id | measured / estimated count |
|-------|----:|----:|
| HC    | **270,994** | **~216,000** (measured, sweep G — 69 % density bimodal) |
| ADI   | 7,956       | ~4,800 (estimated from sweep C — 60.9 %) |
| RE    | 640,321     | ~380,000 (estimated — not yet density-probed) |

HC figure refined from the first pass estimate (~160k) via the
stratified density probe at `docs/sweep-results/2026-04-16-G-hc-density-probe.md`.
Density is **bimodal**: ≤47 % below 50k (older paper-era) and 87–93 %
above 50k. Full HC backfill = ~216k × 3.6 s = **~215 h (~9 days)** at
measured throughput — not viable from one IP without a posture change.

The 2026-04-16 morning ceiling of 270,071 moved to 270,994 by that
evening — ~923 new HCs filed in <12h, matching STF's ~1–2k/day HC
intake. Linear scan-down from 271,000 is a ~10-probe refresh.

Density probe for ADI or RE is a 3-minute run:
```bash
PYTHONPATH=. uv run python scripts/class_density_probe.py --classe ADI
PYTHONPATH=. uv run python scripts/class_density_probe.py --classe RE
```

Practical starting point: **probe sweep on HCs 1..1000** (first thousand, low-numbered historical cases) plus one near the top (269000..270000) to validate the parser holds across eras. ~50 min each with the validated defaults:
```bash
# generate CSV for HC 1..1000
uv run python -c "import csv; w=csv.writer(open('tests/sweep/hc_probe_1_1000.csv','w')); w.writerow(['classe','processo']); [w.writerow(['HC',n]) for n in range(1,1001)]"

PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/hc_probe_1_1000.csv --label hc_probe_1_1000 --wipe-cache \
    --out docs/sweep-results/<date>-F-hc-probe-1-1000
```
Scale decisions (full backfill vs 10 k sample vs whatever the deep-dive question wants) should follow the probe results.

**Binary-search technique** (use this whenever a class ceiling matters):
```python
# probe with resolve_incidente — 302 with Location = exists, 200 empty = missing.
# double an upper bound until it 404s, then binary-search between low and the confirmed bound.
# ~20 probes per class total (one request each). See conversation 2026-04-16 for the one-shot script.
```

## Rate-budget findings (D-runs)

Three 200-process sweeps on disjoint ADI slices (commit `c101310`, results at `docs/sweep-results/2026-04-16-D*`). Full analysis: `docs/sweep-results/2026-04-16-D-rate-budget.md`.

| run | pacing | retry-403 | ok/200 | first block | stall   | wall  |
|-----|-------:|:---------:|-------:|------------:|--------:|------:|
| R1  | 0      | ✓         | 199    | process 121 | 4.5 min | 7.3 min |
| R2  | 0.5 s  | ✗         | 30     | process 31 (hot start) | n/a | 2.1 min |
| R3  | 2.0 s  | ✗         | 175    | process 106 | 1.0 min (then resumed) | 9.8 min |

Headline findings:
- **STF's block threshold is ~100–120 processes at any pacing tested.** Pacing doesn't prevent blocks; it just changes their duration (4.5 min at zero sleep → ~1 min at 2 s).
- **Reactive retry is the better default.** R1's 199/200 vs R3's 175/200.
- **Warm-start measurements are meaningless.** R2 ran immediately after R1 and inherited a hot WAF counter; its 30/200 result doesn't tell us about 0.5 s pacing on a fresh IP.

**These are now the defaults** (commit `2a2833d`):
- `ScraperConfig.retry_403: True`
- `ScraperConfig.driver_max_retries: 20` (was 10)
- `ScraperConfig.driver_backoff_max: 60` (was 30)
- `run_sweep.py --throttle-sleep` default: `2.0` (was 0)
- `run_sweep.py` flag renamed `--retry-403` → `--no-retry-403` (opt-out)

Expected wall for 1000 ADIs: ~52 min (vs Selenium's 77.6 min) with near-perfect completion. Validated by sweep E (below).

## Sweep E — partial 1k validation (stopped early, defaults validated)

**Status**: stopped at **429/1000** via SIGTERM to free the WAF counter
for the G density probe. Clean shutdown; resumable via `--resume`. Full
write-up at `docs/sweep-results/2026-04-16-E-full-1k-defaults/SUMMARY.md`.

Headline: **429/429 ok, 0 errors**. Four WAF block cycles (ADI 104,
205, 301, 397 — ~90 s each) absorbed transparently by retry-403. Zero
leakage. Measured pace **3.60 s/process**, projecting ~60 min for full
1000 (vs handoff estimate of 52 min and Selenium baseline of 77.6 min
— HTTP ~22% faster end-to-end).

The partial is sufficient evidence that the shipped defaults (retry-403
+ 2 s pacing + 20/60 retry budget, commit `2a2833d`) are production-
viable. A 1000-process ceiling datapoint would be nice-to-have but not
necessary — the mechanism is clearly working.

**To finish the full 1000** (adds ~34 min wall from a cold WAF):
```bash
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/full_range_adi.csv \
    --label full_1k_defaults \
    --parity-csv output/judex-mini_ADI_1-1000.csv \
    --out docs/sweep-results/2026-04-16-E-full-1k-defaults \
    --resume
```

## The one thing still to decide

**STF's `robots.txt` disallows `/processos` for all user agents.** Sweep C made this real: the WAF enforces it with a 403 block at ~107 consecutive processes (but R1 contradicted this — threshold isn't constant). Three postures (unchanged from the previous handoff):

1. **Minimum professional floor** — custom `User-Agent` identifying the project with a contact email, `NOTICE.md` explaining LAI basis + LGPD obligations, keep scraping with adaptive pacing.
2. **Talk to STF first** — Ouvidoria. Brazilian courts sometimes grant whitelisted access. Slow, safe.
3. **Cache-first distribution** — ship as a parser. Users populate `.cache/` themselves; library never sweeps from one IP.

Still unresolved. No longer blocks the *mechanics* of long sweeps (`--retry-403` + `--throttle-sleep` + `--retry-from` handle it), only the posture question. Doesn't block Selenium retirement either (still internal cleanup).

## What works today

- `main.py --backend={selenium,http}` — default `selenium`. HTTP path additionally accepts `--fetch-pdfs/--no-fetch-pdfs` (default on).
- `src/scraper_http.py`:
  - `_http_get_with_retry` wraps every GET in tenacity (retries 429/5xx/connection errors via `ScraperConfig`; 4xx non-429 fails fast; `cfg.retry_403=True` adds 403 to the retriable set).
  - `run_scraper_http` mirrors `run_scraper` (same output shape, same missing-retry loop).
  - `scrape_processo_http` fetches detalhe + 9 tabs concurrently, derives `tema` from abaSessao, then hits the repgeral JSON endpoints for `sessao_virtual` and (when `fetch_pdfs=True`) fetches+extracts each Relatório/Voto PDF.
- `src/extraction_http_sessao.py` — pure parsers (`parse_oi_listing`, `parse_sessao_virtual`, `parse_tema`) plus the `extract_sessao_virtual_from_json` orchestrator. Fetchers are dependency-injected for testability.
- `src/utils/pdf_cache.py` — URL-keyed PDF text cache under `.cache/pdf/<sha1>.txt.gz`. ADI 2820 cold ≈ 12.9s → cached ≈ 0.18s.
- `src/data/missing.py` — `check_missing_processes` lives here now (was in `src/scraper.py`). Backend-neutral.
- `src/extraction/__init__.py` is intentionally empty — keeps the HTTP backend Selenium-free on import. `import src.scraper_http` loads 0 selenium modules (pinned by `tests/unit/test_http_backend_no_selenium.py`).
- `tests/unit/` — **48 unit tests** covering retry semantics (incl. 403 opt-in), CLI dispatch, PDF cache, sessao_virtual parsers, sweep state recovery + atomic writes, CSV parsing, exception classification. `uv run pytest tests/unit/`.
- `scripts/validate_ground_truth.py` — still the source of truth for HTTP parity. 4/5 MATCH; ACO_2652 shows two pre-existing diffs (assuntos drift on the live site, `pautas: null` vs `[]`). `sessao_virtual` is a SKIP field so it doesn't participate — parsers are validated by the unit tests instead.
- `scripts/run_sweep.py` + `scripts/sweep_state.py` — CSV-driven sweep driver with append-only log, atomic state, resume, retry-from, structured errors, 403 retry, throttle sleep. See the "Running sweeps" section below.

## Next steps, ordered

### 1. Close out sweep E

Check `docs/sweep-results/2026-04-16-E-full-1k-defaults/sweep.state.json` for final counts. Append a section to `docs/sweep-results/2026-04-16-D-rate-budget.md` (or its own file) comparing E's numbers with the 52-min projection and Selenium's baseline. Commit. See "Sweep E" section above for the one-liner to check status.

### 2. Circuit breaker for the sweep driver

Even with retry-403 + pacing, pathological WAF escalation could cascade. Should add: abort the sweep if error rate crosses X % in a rolling window of N processes.

Implementation sketch: maintain a `collections.deque(maxlen=N)` of recent statuses in `run_sweep.main`; after each process, if more than X % of the deque is non-ok, write errors, write state, exit with status 2 and a clear message. Tunable via two CLI flags. Minimum viable: N=25, X=50 %. ~15 min of work.

### 3. Scope the HC deep dive

See "Next major goal" at the top. Decide scope (time-sliced / sample-first / relator-sliced). Probe HCs 200000..201000 first to measure completion + rate before a bigger commitment. Ask the user what the deep dive wants to answer — that shapes what data matters.

### 4. Outcome derivation (new)

StfItem has no "winner"/"verdict" field. The data is there but scattered — determining the outcome requires:
- Parsing `sessao_virtual[-1].voto_relator` for verdict phrases (`julgo procedente|improcedente|procedente em parte|nego provimento|dou provimento|não conheço`).
- Checking `sessao_virtual[-1].votes` — if `diverge_relator` is empty AND `pedido_vista` is empty or resolved in a later session, the relator's vote is the outcome.
- Checking `andamentos` for `TRANSITADO(A) EM JULGADO` (final-and-unappealable) and event names like `JULGADO PROCEDENTE`, `EMBARGOS RECEBIDOS EM PARTE` — the `complemento` field on these often carries the full decision text.

Worth adding as a derived field during parse (`src/extraction_http_sessao.py`) OR as a post-processing pass. Brazilian legal vocabulary is richer than the table above (`prejudicado`, `extinto sem resolução de mérito`, `conversão em diligência`, …), so a first pass will have a meaningful `unknown`/`pending` tail. Needed by the HC deep dive if it wants outcome statistics.

### 5. Retry sweep C's 893 blocked processes

Sweep C's `docs/sweep-results/2026-04-16-C-full-1000.md` predates the robust driver — it wrote a flat markdown file, no `sweep.errors.jsonl`. So `--retry-from` can't be pointed at it directly. Two options:

- **Re-run the full range under the new driver** once the rate-budget posture is chosen. Uses `--resume` to skip the 107 already in cache.
- **Synthesise an errors.jsonl** from the C report's "status=error" rows (one-off script) to feed `--retry-from`.

Either works. The first is more honest about wall time; the second is faster to start.

### 4. Retire the Selenium path

After the measurement settles:

- Delete `src/scraper.py`, `src/utils/driver.py`, `src/utils/get_element.py`.
- Drop `selenium` from `pyproject.toml`.
- In `src/extraction/`: many extractors are still Selenium-bound (`extract_andamentos.py`, `extract_assuntos.py`, `extract_deslocamentos.py`, `extract_peticoes.py`, `extract_recursos.py`, `extract_partes.py` old bs4 path, `extract_primeiro_autor.py`, `extract_sessao_virtual.py`, `extract_orgao_origem.py`, `extract_data_protocolo.py`, `extract_numero_origem.py`, `extract_volumes_folhas_apensos.py`, `extract_origem.py`, `extract_incidente.py`, `extract_badges.py`). Pure-soup ones (`extract_classe.py`, `extract_meio.py`, `extract_numero_unico.py`, `extract_publicidade.py`, `extract_relator.py`) are imported by `src/extraction_http.py` — keep those.
- **Surfaced during sweeps**: `src/extraction/extract_recursos.py:39` emits `{"index": …}` but the ground-truth fixtures and HTTP extractor emit `{"id": …}`. This is a real Selenium-side inconsistency (see sweep B/C diffs). Deleting the Selenium path resolves it.
- `src/extraction/__init__.py` is already empty; no further `__init__` cleanup needed.

### 5. PDF extraction quality

Currently PDFs go through `pypdf.PdfReader.extract_text(extraction_mode="layout")`. You'll see warnings like `Rotated text discovered. Output will be incomplete.` — these are real: STF often stamps signed documents with rotated watermarks and the extractor drops content around them. Two options: (a) fall back to default mode on rotation, (b) use `pdfminer.six` or OCR for the problem documents. Worth investigating if downstream analysis needs the full text.

### 5. Pre-existing bugs in the Selenium side

Surfaced during the dedup review; untouched because the Selenium path has no automated coverage:

- `src/extraction/extract_peticoes.py:28-30`: `data_match` is assigned from `bg-font-info` on line 28, then immediately overwritten by `processo-detalhes` on line 30. The first match is dead.
- `src/extraction/extract_deslocamentos.py:113-152`: `_clean_extracted_data` looks dead — `_clean_data_fields` is the one called from `_extract_single_deslocamento`. Verify with grep.
- `src/data/types.py:47-78`: commented-out dataclasses. Git remembers; delete.

Not blocking. Clean up if you're already in those files. Safe to defer until Step 2 deletes these files anyway.

## Gaps in the sessao_virtual port

Worth knowing if you're debugging:

- **Vote categories are partial**: only `tipoVoto.codigo` 7 (diverge), 8 (acompanha-divergência), 9 (acompanha) land in the final `votes` dict. Codes 3 (impedido), 10 (acompanha-ressalva), 11 (suspeito), 13 (acompanha-ressalva-ministro) drop out for parity with the Selenium extractor's 5-category DOM scrape. If downstream needs these, extend `_VOTE_CATEGORY` in `src/extraction_http_sessao.py`.
- **documentos values are mixed types**: string containing extracted text (success) or the original URL (fetch failed). Consumers must check `startswith("https://")` to tell. Re-running the scraper picks up where failures left off via the URL-keyed PDF cache.
- **Tema branch has only one fixture test (tema 1020)**. If you see drift there, probe another tema + add a fixture.
- **No Sessão-branch support for "suspended" lists** — if STF ever returns a listaJulgamento mid-suspension with a different JSON shape, `parse_sessao_virtual` will pass through missing fields as empty strings. No known case.

## Non-obvious things (kept from previous handoff, still true)

- **The `abaX.asp` endpoints return 403 without three things**: valid session cookie (`ASPSESSIONID…` + `AWSALB`), `Referer: detalhe.asp?incidente=N`, and `X-Requested-With: XMLHttpRequest`. `requests.Session()` plus the two headers suffices.
- **STF serves UTF-8 without declaring a charset.** `requests` defaults to Latin-1 → mojibake. `scraper_http._decode` handles it; never bypass.
- **`extract_partes` has two possible sources** on `abaPartes.asp`: `#todas-partes` (full, 9 entries for ADI 2820) and `#partes-resumidas` (main parties, 4 entries). The HTTP path uses `#partes-resumidas` for parity with Selenium's `#resumo-partes`.
- **Ground-truth fixtures have inconsistent `sessao_virtual` schemas** across files (MI/RE/AI use `{data,tipo,numero,relator,status,participantes}`; ACO_2652 uses `{lista,relator,orgao_julgador,voto_texto,…}`; ADI_2820_reread uses `{metadata,voto_relator,votes,documentos,julgamento_item_titulo}`). The HTTP port emits the ADI schema — that's what the current code commits to.
- **PDF URLs live on `sistemas.stf.jus.br`, not `portal.stf.jus.br`.** Separate origin, separate throttle counter. Interleaving PDF fetches between tab fetches naturally slows the portal hit rate.
- **DataJud does not have STF.** `api_publica_stf` returns 404. Other tribunals work with the same public API key. Don't re-check.

## How to run things

```bash
# Unit tests (48 tests, <3s)
uv run pytest tests/unit/

# Ground-truth validation (HTTP parity against 5 fixtures)
PYTHONPATH=. uv run python scripts/validate_ground_truth.py

# HTTP scrape, one process, with PDFs
uv run python main.py --backend http -c ADI -i 2820 -f 2820 -o json -d output/test --overwrite

# HTTP scrape without the PDF fetch (faster, documentos stay as URLs)
uv run python main.py --backend http --no-fetch-pdfs -c AI -i 772309 -f 772309 -o json -d output/test --overwrite

# Selenium scrape (unchanged default path)
uv run python main.py -c AI -i 772309 -f 772309 -o json -d output/test --overwrite

# Wipe caches
rm -rf .cache  # HTML fragments, sessao JSON, PDF text
```

## Running sweeps

```bash
# One-shot sweep over a CSV of (classe, processo) pairs
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/shape_coverage.csv \
    --label my_sweep \
    --parity-dir tests/ground_truth \
    --out docs/sweep-results/<date>-<label>

# Long sweep with WAF-friendly pacing
PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/full_range_adi.csv \
    --label long_sweep \
    --throttle-sleep 1.0 \
    --retry-403 \
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
    --retry-403 --throttle-sleep 1.0 \
    --out docs/sweep-results/<date>-<label>-retry
```

Sweep output directory layout:
```
<out>/
    sweep.log.jsonl      append-only, one JSON line per attempt
    sweep.state.json     compacted state, atomic rewrite
    sweep.errors.jsonl   derived from state (non-ok only)
    report.md            human-readable summary
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
`sweep.log.jsonl` + `sweep.state.json` are always consistent and the run
is resumable via `--resume`, but `sweep.errors.jsonl` and `report.md`
won't be written. A `--resume` run (even one that skips everything)
regenerates both at its end.

## Files you probably need to touch first

- `src/scraper_http.py` — HTTP orchestrator, `fetch_process`, `scrape_processo_http`, retry helper (incl. 403 opt-in), PDF/sessão fetcher factories
- `src/config.py` — `ScraperConfig` including `retry_403` flag
- `src/extraction_http.py` — fragment parsers (re-exports Selenium pure-soup extractors)
- `src/extraction_http_sessao.py` — sessao_virtual parsers + orchestrator
- `src/utils/pdf_cache.py` — URL-keyed PDF text cache
- `src/data/missing.py` — backend-neutral check_missing_processes
- `src/extraction/_shared.py` — regex patterns + helpers shared by both paths
- `src/utils/html_cache.py` — gzip + incidente cache (also used for sessão JSON)
- `scripts/_diff.py` — shared field-by-field diff
- `scripts/run_sweep.py` — CSV-driven sweep driver (state/log/errors + resume/retry-from/signal handling)
- `scripts/sweep_state.py` — append-only log + atomic compacted state (independent of run_sweep, reusable)
- `main.py` — CLI

## Files that already work; don't break them

- `tests/ground_truth/*.json` — fixtures for `scripts/validate_ground_truth.py`
- `tests/fixtures/sessao_virtual/*.json` — captured JSON for the sessao_virtual unit tests
- `tests/unit/*.py` — 27 tests; run them before every change
- `src/data/types.py` — `StfItem` TypedDict (fixed Optional types; don't make them non-Optional again)
- `src/data/export.py` — write paths for CSV/JSON/JSONL output
