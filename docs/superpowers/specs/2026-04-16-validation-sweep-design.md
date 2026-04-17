# Validation sweep — design

Date: 2026-04-16
Branch: `experiment/perf-bulk-data`
Context: `docs/handoff.md` § "Next steps, ordered" #1.

## Goal

Exercise the HTTP backend at a footprint above the 5-fixture ground-truth set, in two stages:

- **Sweep A — Shape-coverage smoke.** 12 processes across 6 classes. Catch schema surprises (unusual `partes`, missing PDF links, Tema branches, HC class never exercised before).
- **Sweep B — Throttle + parity probe.** 50 ADIs sampled from the existing Selenium-scraped `output/judex-mini_ADI_1-1000.csv`. Measure steady-state throughput, 429 rate, cache effectiveness on a warm second pass, and field-by-field parity against the Selenium CSV.

Full regression (step 1c in the handoff) stays deferred pending the robots.txt posture decision. Sweeps A and B do not require it — A is a tiny footprint, B re-covers ground the Selenium run already covered.

## Non-goals

- No changes to the scraper itself. This is measurement + validation, not optimisation.
- No decision on robots.txt posture — that's a separate thread.
- No Selenium-side work (step 2).
- No attempt to close the ACO_2652 pre-existing diffs (assuntos drift, `pautas: null` vs `[]`) — documented as known-diff baseline.

## Process selection

### Sweep A — 12 processes, 2 per class

**Anchors (5, already have ground truth).** Diffs must not grow vs the current baseline.

| classe | processo |
|--------|----------|
| AI     | 772309   |
| MI     | 12       |
| RE     | 1234567  |
| ACO    | 2652     |
| ADI    | 2820     |

**New (7, no ground truth — manual review of output shape).** I curate these by browsing STF to pick 1 more per existing class plus 2 HCs. Selection criteria:

- Mix of old (pre-2010) and recent (post-2020) autuação.
- At least 1 with a populated `sessao_virtual`; at least 1 without.
- At least 1 with a Tema branch that is not 1020.
- Prefer processes with non-trivial `partes` counts.

Target fill: RE × 1, AI × 1, ADI × 1, ACO × 1, MI × 1, HC × 2.

CSV lives at `tests/sweep/shape_coverage.csv` with columns `classe,processo,source` where `source ∈ {ground_truth, curated}`.

### Sweep B — 50 ADIs, Selenium parity

Sample 50 rows from `output/judex-mini_ADI_1-1000.csv` using `random.Random(42).sample(...)`. Seeded for reproducibility. Each row gives us a Selenium-scraped baseline to diff HTTP output against.

CSV lives at `tests/sweep/throttle_probe.csv` with columns `classe,processo` (all `ADI`).

## Driver

New script: `scripts/run_sweep.py`.

```
uv run python scripts/run_sweep.py \
    --csv tests/sweep/shape_coverage.csv \
    --label shape_coverage \
    [--parity-dir tests/ground_truth] \
    [--parity-csv output/judex-mini_ADI_1-1000.csv] \
    [--warm-pass] \
    [--out docs/sweep-results/2026-04-16-A-shape-coverage.md]
```

Responsibilities:

1. Parse CSV → list of (classe, processo, source?) tuples.
2. One `requests.Session` for the whole run via `new_session()`.
3. For each process:
   - `t0 = perf_counter()`, call `scrape_processo_http(classe, processo, use_cache=True, session=session)`.
   - Record wall time, exceptions, `None` returns.
   - Look up parity source:
     - `--parity-dir`: load `tests/ground_truth/<CLASSE>_<N>.json` if present → `diff_item(http, gt, allow_growth=True)`.
     - `--parity-csv`: find row by `(classe, processo)` → field-by-field diff against CSV columns. Skip fields not in the CSV schema.
   - Shape-probe checks regardless of parity: required top-level fields populated (`incidente`, `classe`, `numero`, `relator`, etc. per `StfItem`), `sessao_virtual` either populated dict or empty `{}`, `documentos` values are str.
4. Optional `--warm-pass`: repeat the entire sweep without wiping cache. Used for sweep B to measure cache-hit throughput.
5. Retry instrumentation: count tenacity retries by patching `_http_get_with_retry` via a wrapper that increments counters keyed on HTTP status. Exposed via `scraper_http` or hooked at the tenacity level.
6. Write a Markdown report per run to `--out`:
   - Header: label, CSV path, start/end timestamps, cold/warm, commit SHA.
   - Per-process table: `classe | processo | wall_s | retries_429 | retries_5xx | diffs | shape_anomalies | status`.
   - Aggregate: totals + percentiles (p50, p90, max) for wall time, total retries, cache hits/misses, parity pass rate.
   - "Recurring divergences" section: any field that diffs in ≥ 2 processes.

## Success criteria

**Sweep A:**

- 12/12 complete without exception.
- 5 anchors: no new diffs vs current baseline (ACO_2652's 2 known diffs allowed).
- 7 curated: no exception, all shape-probe checks pass, any recurring divergence logged.

**Sweep B (cold pass):**

- ≥ 48/50 complete (allow up to 2 genuinely-gone process IDs).
- Aggregate 429 rate ≤ 5 % (tenacity absorbs a handful; >5 % means we're hitting the throttle hard enough to motivate step 3).
- Per-process wall time p90 within 2× of the current single-process benchmark (~12s cold per ADI).

**Sweep B (warm pass):**

- All previously-successful processes complete with 0 network retries.
- p90 wall time ≤ 2s (cache-only path).

## Outputs

- `tests/sweep/shape_coverage.csv`, `tests/sweep/throttle_probe.csv` — inputs, committed.
- `scripts/run_sweep.py` — driver, committed.
- `docs/sweep-results/2026-04-16-A-shape-coverage.md` — A results, committed.
- `docs/sweep-results/2026-04-16-B-throttle-probe.md` — B results, committed.

Cache artifacts under `.cache/` stay local (already `.gitignore`d).

## Risks

- **STF throttling.** If sweep B trips `robots.txt`-originated blocks (not just 429s but IP-level bans), stop and escalate. Mitigate by running B during off-peak Brazil hours (evening UTC-3) and keeping tenacity's default backoff.
- **Selenium CSV schema mismatch.** The CSV columns may not map 1:1 to `StfItem` fields. Driver must gracefully skip unmapped fields rather than flagging every row as a diff.
- **Curated process unavailability.** If an HC I pick turns out to be sealed or 404, swap for another. Log the substitution in the results doc.

## Rollback

Everything lives under new paths (`tests/sweep/`, `docs/sweep-results/`, `scripts/run_sweep.py`). Deleting those three and the design doc rolls the work back with zero impact on existing code.

## Addendum (2026-04-16) — Sweep C: full 1000-ADI sweep

After A and B passed with zero throttling and a genuine field-level parity story in place, the user asked for a full 1000-case sweep to benchmark against the recorded Selenium baseline. Documenting it here so the change shows up next to the A/B design.

### Selenium baseline (measured)

Read `extraido` timestamps from `output/judex-mini_ADI_1-1000.csv`:

- 609 rows with `status=200` (the other 391 IDs in 1..1000 either 404 on STF or errored out on the Selenium side).
- First: `2025-10-26T21:23:02`, last: `2025-10-26T22:40:36`.
- **Wall span: 77.6 min / ≈ 4655 s**, giving **~7.6 s / successful process** on Selenium.
- User's recollection was "~2h"; actual is ~1h18m — still the number we're trying to beat.

### Projection from sweep B

50 ADIs took 81 s cold at 4-tab concurrency, 0 retries. Straight scaling: 1000 × 1.62 s ≈ **27 min**, i.e. **~2.9× faster** than Selenium.

Open questions the sweep answers:
- Does STF throttle at ~1000 sequential requests when it didn't at 50? Retry counters + wall tail will reveal this.
- Do the remaining 391 "missing" Selenium IDs 404 on HTTP too, or does HTTP pick up processes Selenium dropped?
- Does the `recursos` key mismatch from sweep B recur on every non-empty recursos row? Expected yes — structural.

### Scope

- **Input**: `tests/sweep/full_range_adi.csv`, classe=ADI, processo=1..1000 (generated once, committed).
- **Parity source**: `output/judex-mini_ADI_1-1000.csv` (Selenium baseline).
- **Cache posture**: `--wipe-cache` so every process is cold. Sweep B's ~52 pre-warmed rows would otherwise distort the wall-time comparison.
- **Passes**: cold only. Warm pass adds no new signal over sweep B's cache numbers.
- **Output**: `docs/sweep-results/2026-04-16-C-full-1000.md`.

### Success criteria

- ≥ 95 % completion on the IDs Selenium got (580+ of 609). If HTTP picks up 404s Selenium had, that's a bonus.
- HTTP total wall ≤ 40 min (gives headroom over the 27 min projection for throttling).
- 429 rate ≤ 2 % of requests across the sweep. Higher motivates handoff step #3.
- Parity diffs other than the `recursos` key mismatch: ideally zero, recurring-divergence table documents anything else.

### Risks and posture

- **This is the first sustained-volume run against STF from this tool.** `robots.txt` still disallows `/processos`. User-explicit instruction to proceed is logged above. Mitigation: single concurrent scraper (no parallel runs), tenacity keeps retries polite, abort if the 429 rate trips 20 % on a rolling window.
- Wall-clock run will take ~30 min and hold a single session open. No side effects beyond the portal hits and the `.cache/` fill.

