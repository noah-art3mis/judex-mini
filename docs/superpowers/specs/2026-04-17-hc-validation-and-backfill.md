# HC validation & scoped backfill

Date: 2026-04-17
Owner: autonomous session (Claude Opus 4.7)
Status: **revised** — original plan duplicated existing work; see § Revision below.

## Revision (2026-04-17, after reading the docs)

The original spec below proposed HTTP-vs-Selenium parity on 10 HCs and
two fresh probe sweeps before scoping a backfill. Reading
`docs/sweep-results/2026-04-17-backfill-log.md` and
`docs/hc-backfill-extension-plan.md` showed that:

- **9 909 HCs already scraped** across sweeps I–S. Zero `status=error`
  in any sweep. Parser quality is **empirically validated at scale** —
  Selenium parity on 10 cases adds no signal.
- Outcome distribution is non-degenerate and matches historical priors
  (3.9 % concedido, 67.9 % nao_conhecido). A silent parser bug that
  produced plausible outcomes at this scale is implausible.
- **Sweep Z (2025 fill) was launched this morning** but died at 38/1000
  (killed externally, no SIGTERM cleanup — no errors.jsonl / report.md).
- **Sweep T (2015 pre-era) is queued** as the next sweep per the
  extension plan.
- **One real bug surfaced in sweep Z's driver.log**:
  `src/utils/pdf_utils.py:88` whitelisted only
  `sistemas.stf.jus.br` for SSL-verify-off. `digital.stf.jus.br`
  (newer monocratic-decisions API, only hit by 2023+ sweeps) was
  failing SSL cert verification and silently dropping PDFs to URLs.
  Sweeps I / J / Z hit this; sweeps K–S (2016–2022) did not hit the
  host at all.

### Revised phases

1. **Fix SSL bug.** ✅ `_is_stf_host()` hostname-based check covers
   all `*.stf.jus.br` subdomains. Unit test added
   (`tests/unit/test_pdf_utils_ssl_hosts.py`). 162/162 tests green.
2. **Inventory impact.** Count HCs in `data/output/sample` whose
   `documentos` entries are still stored as `digital.stf.jus.br` URLs.
   Decide whether to reprocess sweeps I/J via cache-hot replay.
3. **Add HC ground-truth fixture.** `tests/ground_truth/` still has
   zero HCs. Pick one mature modern HC from the cached corpus,
   freeze as `tests/ground_truth/HC_<N>.json`, extend
   `validate_ground_truth.py` coverage.
4. **Resume sweep Z** via `--resume`. Completes HC 258143..259104.
5. **Launch sweep T** (HC 128651..129650, 2015 fill) per extension
   plan Track 1.
6. **Continue Track 1 sweeps U / V / W** (2014 / 2013 / 2012) as the
   12h budget permits, with health-gate checks between each.

The **structural canary in the sweep driver** (original L4) is still
a valid follow-up but deferred — existing health gates in
`docs/hc-backfill-extension-plan.md § Health gates` and retry-403
coverage are adequate for the pre-2016 extension.

---

## Original spec (below — kept for audit trail)


## Problem

The user wants to mass-download HCs for the `docs/hc-who-wins.md` deep
dive. The full HC corpus is ~216k extant (`docs/process-space.md`) —
roughly **9 days wall-time from one IP** at validated pacing defaults
(`docs/rate-limits.md`). Before committing that budget we need evidence
that the HTTP parser produces **correct** output for HCs across vintages.

Current evidence is weak:

- `tests/ground_truth/` has **zero** HC fixtures (5 fixtures: ADI, ACO,
  AI, MI, RE). Parity harness (`scripts/validate_ground_truth.py`) has
  never validated an HC end-to-end.
- STF overhauled portal HTML at least twice between paper-era
  digitization and modern cases. Existing fixtures skew modern.
- Silent failure modes (parser returns empty string instead of None;
  WAF serves partial HTML on soft-block) aren't caught by unit tests.

Thesis: **don't burn 9-day WAF budget on a corpus we've never
parity-tested.** Five cheap-first validation layers, then scoped backfill
gated on their outcome.

## Strategy — five layers, cheapest first

### L1 — Differential validation (HTTP vs Selenium)

Strongest independent bug-finder: Selenium is a second implementation
(DOM-after-JS vs. raw XHR replay). Any field where they disagree is a
parser bug in one of them.

- Install extra: `uv sync --extra selenium-legacy`.
- Sample ~10 HCs stratified by vintage:
  - Paper-era: HC 100, HC 5000
  - Transition: HC 80000, 120000, 180000
  - Modern: 5 spread across 200000..270000
- Confirm each returns 200 via HTTP first (skip 404s, pick replacements).
- Scrape each via both backends, diff JSON (reuse `scripts/_diff.py`).
- Extend `SKIP_FIELDS` only where truly schema-divergent
  (e.g. `sessao_virtual` shape mismatch already documented).
- Exit: table of (field, disagreements) written to
  `docs/sweep-results/2026-04-17-F-hc-parity/parity_report.md`.
- **Decision gate:** any unexpected disagreement halts the plan and
  writes findings for the user.

### L2 — Probe sweeps + structural QA

Run the two probe sweeps from `docs/current_progress.md`, then compute
per-field populated-rate tables by vintage.

- HC 1..1000 (`hc_probe_1_1000.csv`) → ~50 min wall.
- HC 269000..270000 (`hc_probe_269_270k.csv`) → ~50 min wall.
- Structural QA script (new, `scripts/hc_field_coverage.py`):
  - % of records with each `StfItem` field populated
  - Stratified by decade (inferred from `data_autuacao` or number range)
  - Flag: `partes` empty, `andamentos` length < 3, `numero_unico` fails
    CNJ check-digit, `relator` empty, `documentos` still-URL count
- Output: `docs/sweep-results/2026-04-17-F-hc-probe/field_coverage.md`.
- **Decision gate:** any field with populated-rate <50% in modern
  vintage halts the plan. Paper-era sparsity is expected; a 5% hole
  in modern output is a parser bug.

### L3 — Draft HC ground-truth fixtures

Pick 3 interesting cases from L2 output (one paper-era, one
transition, one modern with crowded `sessao_virtual`), hand-verify
spec-inspectable fields against the live portal, freeze at
`tests/ground_truth/HC_<N>.json`.

- I draft the fixture files from scraper output.
- Flag for the user: 2–3 fields per fixture to eyeball in browser.
- User step (async, after autonomous run): confirm and merge.

### L4 — Live structural canary in the sweep driver

Augment `scripts/run_sweep.py` with a rolling-window structural check:

- Every N=50 processes, compute populated-rate on recent window.
- If any field's rate drops below a vintage-adjusted floor, trip the
  existing circuit breaker (write errors + state + exit 2).
- Distinguishes WAF-partial-HTML (global crater) from parser bug
  (one specific field drops).
- Tunable floors via CLI flag.

### L5 — Scoped backfill: stratified 5000-HC sample

After L1–L4 pass:

- Ten 500-HC slices, one per decade (or equivalent vintage bins).
- ~4 h wall at validated pacing + structural canary live.
- Output at `docs/sweep-results/2026-04-17-G-hc-stratified-5k/`.
- **Not** a full backfill. 9-day commitment stays pending user review
  of the 5k sample.

## Safety envelope

- **WAF budget cap**: 6000 total process fetches (1k paper probe +
  1k modern probe + 10 Selenium parity + 5k stratified sample = 7010;
  round down to 6000 hard cap, trim stratified sample if needed).
- **Circuit breakers**:
  - Existing: retry-403 + tenacity backoff.
  - New: L4 structural canary.
  - Decision gates at L1, L2 boundaries.
- **Won't do autonomously**:
  - `git push` / PR open / PR comment
  - Modify existing `tests/ground_truth/*.json` (only append new `HC_*.json`)
  - Wipe caches beyond per-process `--wipe-cache`
  - Install anything beyond `uv sync --extra selenium-legacy`
  - Commit to the 9-day full backfill
- **Failure mode**: on any decision-gate failure, write a findings
  report at the phase's output dir and stop. Do not escalate WAF
  pressure to try to recover.

## Execution order

1. Write this spec. ✅
2. Check project state, install selenium-legacy, confirm Selenium
   backend still imports.
3. L1: pick sample, confirm HTTP 200, scrape both backends, diff.
4. Write L1 parity report. Decision gate.
5. L2: generate both probe CSVs, run both sweeps, compute coverage.
6. Write L2 coverage report. Decision gate.
7. L3: draft 3 HC fixtures; flag user for hand-verification.
8. L4: implement structural canary; add unit test; run tests.
9. L5: generate stratified CSV, run sample sweep.
10. Writeup + spot-check candidates for the user.

## Output artifacts

- `docs/sweep-results/2026-04-17-F-hc-parity/parity_report.md` (L1)
- `docs/sweep-results/2026-04-17-F-hc-probe-1-1000/` (L2a)
- `docs/sweep-results/2026-04-17-F-hc-probe-269-270k/` (L2b)
- `docs/sweep-results/2026-04-17-F-hc-probe/field_coverage.md` (L2 combined)
- `tests/ground_truth/HC_*.json` (L3, pending user confirmation)
- Sweep driver changes (L4)
- `docs/sweep-results/2026-04-17-G-hc-stratified-5k/` (L5)
- Final summary update to `docs/current_progress.md`.
