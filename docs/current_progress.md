# Current progress — judex-mini

Branch: `main`. Prior cycle archived at
[`docs/progress_archive/2026-04-19_2355_hc-2026-v8-pipeline-and-sharding-fixes.md`](progress_archive/2026-04-19_2355_hc-2026-v8-pipeline-and-sharding-fixes.md)
— marquee-lawyers Phase 0–5 pipeline (proxy-sharded bytes + pypdf text +
cleanup idempotency open question), blog-export tangent (Ghost-ready
`post.md` + great_tables HTML + Plotly fragment + kaleido PNG), schema
v8 DJe strip, CLI docs cycle, 475 tests green.

**Status as of 2026-04-19 ~24:00.** Corpus: **82,840 HC files** (+3,098
fresh 2026 v8+DJe re-scrapes this cycle; full 2026 range now content-
fresh, not just structurally v8). PDF cache: **1.5 GB / 10,841 PDFs**
(+2,849 fresh 2026 downloads). Dead-ID graveyard:
`data/dead_ids/HC.txt` (**3,348 confirmed pids**, 903 in 2026).
Warehouse: 2026 sub-warehouse at
`data/warehouse/judex-2026.duckdb` **rebuilt mid-session** (3,098 cases
/ 11,208 partes / 35,931 andamentos / 1,302 PDF URLs / 689 pautas /
34 MB / 3.1 s). **Main `judex.duckdb` still reflects pre-session 2026
content** — rebuild deferred (non-blocking; will happen as part of
the 2023/2024/2025 backfill end-of-cycle rebuild). Nothing executing.

**✅ HC 2026 scrape complete (2026-04-19).** Full year is content-
fresh v8+DJe on disk, dead-IDs graveyarded, PDFs downloaded. The only
loose end on 2026 is the warehouse rebuild, which is non-blocking and
folds into the next full-corpus rebuild at end-of-backfill.

Single live file covering the **active task's lab notebook**
(plan / expectations / observations / decisions) and the **strategic
state** across work-sessions. Convention at
`CLAUDE.md § Progress tracking`. Archive to
`docs/progress_archive/YYYY-MM-DD_HHMM_<slug>.md` when the active
task closes out or the file grows past ~500 lines.

For *conceptual* knowledge (how the portal works, how rate limits
behave, class sizes, perf numbers, where data lives), read:

- [`docs/data-layout.md`](data-layout.md) — where files live + the three stores.
- [`docs/stf-portal.md`](stf-portal.md) — URL flow, auth triad, field→source map, DJe flow.
- [`docs/rate-limits.md`](rate-limits.md) — WAF behavior, validated defaults, robots.txt posture.
- [`docs/process-space.md`](process-space.md) — HC/ADI/RE ceilings + density.
- [`docs/performance.md`](performance.md) — HTTP-vs-Selenium numbers, caching as the real lever.
- [`docs/warehouse-design.md`](warehouse-design.md) — DuckDB warehouse schema + build pipeline.
- [`docs/data-dictionary.md`](data-dictionary.md) — schema history v1→v8.

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration (marimo notebooks, one-off scripts, raw JSON dumps). Safe to fill freely.
- **`config/`** — git-ignored (credentials). Holds `proxies.{a..p}.txt` = 16 pools × 10 sessions = 160 proxies.
- **All non-trivial arithmetic via `uv run python -c`** — never mental math. See `CLAUDE.md § Calculations`.
- **Sweeps write a directory**, not a file. Layout in [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).

---

# Active task — lab notebook

## Task

**HC 2023/2024/2025 full-range backfill + 8-vs-16 shard experiment.**
Scrape every pid in each year's range (minus confirmed deads) — not
just the "gap" — because the ~44,926 already-on-disk cases are
structurally v8 but content-stale (truncated partes, empty pautas,
no `publicacoes_dje`), and we have no cheap programmatic way to
distinguish content-fresh-v8 from content-stale-v8 (`mtime` was
clobbered by the v8 renormalization pass — every file reads as
"recent"). Simplest-honest approach: re-scrape them all.

**Scope per year (as of 2026-04-20, after `--full-range` flag landed
on `generate_hc_year_gap_csv.py`):**

| Year | Range           | Width  | Dead   | **Scrape target** |
|------|-----------------|--------|--------|-------------------|
| 2025 | 250919..267118  | 16,200 |  2,445 | **13,755**        |
| 2024 | tbd             | tbd    | tbd    | tbd               |
| 2023 | tbd             | tbd    | tbd    | tbd               |

**PDF skip is free** — `baixar-pecas` short-circuits on `sha1(url)`
cache hit atomically, so only genuinely-new URLs (surfaced by the
wider v8+DJe extractor) trigger downloads. Expected net-new ratio
~0.9 PDFs/case based on 2026 (2,849 new / 3,098 cases).

Piggy-back a controlled experiment on the two largest years:
**run 2025 at 8 shards, 2024 at 16 shards**, same CLI path, same
proxy-dir (`config/`), same interleave default. Decide whether 16
is a net win over 8 or whether scrapegw's ASN-level reputation
decay makes the extra shards self-defeating. Order: 2025 (8) →
cooldown → 2024 (16) → 2023 (winner of the first two).

**Operational cost estimate.** 2026 did 3,098 cases in ~3 h
(with recovery). Linear extrapolation puts 2025 at **~12–15 h**
of case-scrape wall-clock — overnight-plus, not afternoon. Budget
accordingly.

## Experiment — 8 vs 16 shards

**Status:** not started. Carries forward Open Question #2
(ASN-vs-pool-level reputation decay) as a natural A/B since 2025 and
2024 are back-to-back eligible workloads of similar shape.

**Hypothesis.** If scrapegw's WAF reputation is **pool-level** (per
exit-IP-pool), 16 shards using 16 distinct pools should roughly halve
wall-clock vs. 8, at similar cliff rate. If reputation is
**ASN-level** (provider-wide), 16 shards will cliff ≥ as often as 8
and gain little wall-clock — because per-request volume concentrates
on the same degraded exit IPs twice as fast.

**Design.**

| Arm | Year | Shards | Pools                | Target                                                       |
|-----|------|--------|----------------------|--------------------------------------------------------------|
| A   | 2025 | 8      | `proxies.{a..h}.txt` | **13,755 pids** (`tests/sweep/hc_2025_full.csv`, 2026-04-20) |
| B   | 2024 | 16     | `proxies.{a..p}.txt` | tbd — regenerate `hc_2024_full.csv` immediately before arm B |

Same CLI (`judex varrer-processos --csv … --shards N --proxy-pool-dir
config/ --retomar --excluir-mortos`). Note: both CSVs are produced
with `generate_hc_year_gap_csv.py --full-range --dead-ids …` so
on-disk content-stale pids are included. Interleave default. 30–90
min cooldown between arms per `docs/rate-limits.md § Two-layer
model`. 2024 CSV regenerated immediately before arm B so both arms
see a fresh dead-ID filter (any deads confirmed during arm A are
excluded from B).

**Metrics to capture per arm** (read from each shard's
`sweep.state.json` + `sweep.log.jsonl` after completion):

- **Wall-clock** start → last-ok timestamp of the slowest shard.
- **Per-shard throughput** = `ok_count / shard_wall_s`. Report median
  + p95 across shards.
- **Cliff count** = shards with `stop_on_collapse` triggered (read
  `sweep.errors.jsonl` final event or `CliffDetector` log line in
  `driver.log`).
- **Session-rotation count** per shard (grep `"session_rotate"` in
  `sweep.log.jsonl`; high = WAF pressure even on non-cliffed shards).
- **403 count** total and per-shard (`grep -c '"status": 403'`
  `sweep.log.jsonl` or from the `tenacity` retry events).
- **NoIncidente rate** — should track the ~20% observed-dead-rate; a
  spike points to proxy soft-block bleeding into false NoIncidente
  signals (dead-ID confirmation requires ≥2, so 1-off soft-blocks
  don't poison the graveyard, but they do waste throughput).

**Decision criteria** (apply after arm B completes):

- **16 wins** if wall-clock_B < 0.65 × wall-clock_A **and**
  cliff_count_B ≤ cliff_count_A + 1. Use 16 for 2023.
- **16 loses** if wall-clock_B > 0.85 × wall-clock_A **or**
  cliff_count_B ≥ 2 × cliff_count_A. Use 8 for 2023.
- **Ambiguous** otherwise (between 0.65 and 0.85 wall-clock ratio) —
  report the numbers, default to 8 for 2023 (conservative; 8 is the
  known-good cadence), flag for follow-up with the external probe
  script from OQ #2.

**Confounds to note in the write-up.**

- **Time-of-day effects.** STF WAF behavior differs day/night (per
  `docs/rate-limits.md`). Run both arms in the same ~4 h window if
  possible. Avoid running B during US business hours if A ran late-
  evening Brazil time.
- **Year-level content variance.** 2024 vs. 2025 cases shouldn't
  differ in WAF pressure (same endpoints, same auth triad) but
  per-case HTTP budget differs slightly (pautas density). Track
  `mean_requests_per_case` per arm as a nuisance variable.
- **scrapegw baseline drift.** scrapegw's degradation state today vs.
  tomorrow is unobservable without the neutral-target probe (OQ #2,
  still not built). A single A/B doesn't separate "16 is bad" from
  "scrapegw was worse today." If results are ambiguous, consider
  repeating the 2024 arm at 8 shards to isolate.
- **Cooldown between arms.** 30–90 min is a minimum; ideally the gap
  between arm A end and arm B start is logged and reported alongside
  the wall-clock comparison.

**Analysis artifact.** After arm B, produce
`docs/reports/2026-04-XX_8-vs-16-shards.md` with: table of metrics
per arm, one plot of per-shard wall-time trajectories (read from
`sweep.log.jsonl`), and a decision statement against the criteria
above. Promote if results are conclusive; mark "inconclusive" if
not, and queue the external exit-IP probe (OQ #2) as the blocker.

## Observations from the just-closed cycle

- **HC 2026 main sweep** (`runs/active/2026-04-19-hc-2026-v8/`, 8
  shards × 500 pids). 5 healthy shards hit 500/500; **3 shards cliffed**
  (e at 438, f at 388, g at 20 / 500). All 3 collapses had the same
  signature: wall-times degrading 2s → 30s → 70s → 100s, session
  rotation attempts couldn't recover (22–40 rotations in f and e).
  Cause best-guessed at **scrapegw exit-IP-pool reputation decay** —
  not conclusively host/ASN-level vs. pool-wide degradation. Distinguishing
  those requires a second provider, which we don't have.
- **Recovery** (`runs/active/2026-04-19-hc-2026-v8-recovery/`, direct-IP
  single-thread with `--no-stop-on-collapse`). 654 ungrabbed pids, 492 ok
  + 162 dead, **0 errors**, ~45 min wall-clock. `--no-stop-on-collapse`
  was the key — direct IP saw the same WAF hiccups but CliffDetector
  was over-eager for a single-threaded run where pool-protection isn't
  the concern.
- **Dead-ID aggregation across all sweeps**: 23,233 NoIncidente observations
  → **3,348 confirmed dead HC pids** (≥2 observations, both with empty
  `body_head`). 903 confirmed dead in 2026 range = 22.6% of the candidate
  space (matches the observed ~20% dead-rate during the live scrape).
- **2026 items promotion**: 3,098 fresh v8 case JSONs promoted from
  `items/` into `data/cases/HC/` with a one-shot unwrap (list-wrap
  gotcha). Shortly after, `_write_item_json` was fixed at the source so
  this won't recur.
- **PDF download skew — and interleave's first live deployment.** 16-shard
  `baixar-pecas` on a sorted-by-pid CSV put 4 shards in a fresh-heavy
  state (700+ URLs each, ETA 52–79 min) and 12 in cache-only mode
  (finished in 6 min). Killed + rebuilt recovery CSV (774 HC cases) +
  relaunched 16-shard with the newly-shipped `--estrategia-shard
  interleave`. Every shard saw ~49 cases with balanced fresh/cached
  mix; whole sweep finished in ~6 min. **Freshly-downloaded 2,849 PDFs
  across both runs = exactly the dry-run prediction (2,849 expected)**,
  zero duplicates, zero errors.

## Decisions (this cycle)

- **Dead-ID confirmation threshold is ≥2 empty-body observations.** Single
  observations go to `<classe>.candidates.tsv` (audit trail). Non-empty
  `body_head` on NoIncidente suggests proxy soft-block, not STF
  unallocation — does not count toward confirmation. Makes the
  aggregator robust to false-positive tombstones.
- **Interleave is the new default** for both `varrer-processos --shards`
  and `baixar-pecas --shards`. Range retained as opt-in
  (`--estrategia-shard range`) for the narrow case where pid locality
  matters more than load balance.
- **`_write_item_json` writes bare dict** (commit `8fb855a`). The list-wrap
  was a legacy compat with `main.py -o json` — not worth the perennial
  promote-with-unwrap step. Reader tolerance
  (`peca_targets._load_case_records`, `reshape_to_v8`) kept intact so
  any old list-wrapped files still read.
- **Warehouse rebuild is per-cycle, not per-sweep.** Running
  `atualizar-warehouse --ano 2026` after Phase 4 got the fresh content
  into DuckDB for the mid-session PDF-URL target derivation; the full-
  corpus rebuild is a one-shot at the end of a pipeline cycle.

## Open questions carried forward

1. **Why does `clean_pdf_text` not reach a fixed point?** (From prior cycle.)
   Still unanswered — the 2026 HCs haven't had text extraction yet, so
   cleanup hasn't re-run. When we OCR 2026 via `extrair-pecas`, the
   fresh text is a good dataset to re-attack this on.
2. **Is scrapegw's reputation ASN-level or pool-level?** Today's cliffs
   don't distinguish; the diagnostic would be probing scrapegw's exit
   IPs against a neutral target during cooldown. Proposed as a small
   probe script; not built. **The 8-vs-16 experiment above gives an
   indirect answer** — if 16 shards roughly halves wall-clock, pools
   are independent; if not, ASN-level degradation is the better
   model. The probe script becomes the tiebreaker if A/B is
   ambiguous.
3. **`--excluir-mortos` on `baixar-pecas`?** Not currently plumbed
   (only `varrer-processos` has it). Minor win — baixar-pecas already
   naturally skips dead IDs because they have no case JSON → no URL
   targets. Arguably not worth a diff.

## Next steps

1. **Arm A — HC 2025 @ 8 shards.** CSV already regenerated at
   `tests/sweep/hc_2025_full.csv` (13,755 rows, via
   `--full-range --dead-ids`). Launch `judex varrer-processos --csv
   tests/sweep/hc_2025_full.csv --shards 8 --proxy-pool-dir config/
   --retomar --excluir-mortos --rotulo hc_2025 --saida
   runs/active/<date>-hc-2025 --diretorio-itens data/cases/HC`.
   Budget: ~12–15 h wall-clock (13,755 cases × 2026's per-case rate).
   Log wall-clock start/stop for the A/B.
2. **Cooldown** 30–90 min. Aggregate dead-IDs
   (`scripts/aggregate_dead_ids.py --classe HC`).
3. **Arm B — HC 2024 @ 16 shards.** Regenerate 2024 full-range CSV
   with fresh dead-IDs (same flags as 2025); same command with
   `--shards 16`. Log start/stop.
4. **Write up the A/B** to `docs/reports/2026-04-XX_8-vs-16-shards.md`.
   Decide 2023's shard count from the decision criteria.
5. **Arm C — HC 2023** at winner's cadence.
6. **PDFs for each year** via `judex baixar-pecas --csv … --shards 16
   --proxy-pool-dir config/ --retomar --nao-perguntar` — sistemas.stf
   is a separate WAF counter, 16 is safe there.
7. **`extrair-pecas`** on fresh bytes per year (zero HTTP; local CPU).
8. **DJe warehouse flatten** — still open; do after all years land so
   the fix benefits the full corpus at once.

### Deferred (non-blocking)

- **Full warehouse rebuild** (`uv run judex atualizar-warehouse`,
  ~168 s). Main `judex.duckdb` still reflects pre-session 2026
  content, but analyses over 2026 can use the
  `data/warehouse/judex-2026.duckdb` sub-warehouse in the meantime.
  Folds into the end-of-cycle full-corpus rebuild after arms A–C
  land, at which point a single rebuild picks up all four years'
  fresh content at once.

## Files touched this cycle (for the archive)

- **New**: `judex/utils/dead_ids.py`, `scripts/aggregate_dead_ids.py`,
  `tests/unit/test_dead_ids.py`, `tests/unit/test_shard_csv.py`,
  `tests/unit/test_atualizar_warehouse_cli.py`.
- **Modified**: `scripts/run_sweep.py` (bare-dict write),
  `scripts/shard_csv.py` (interleave default + `--strategy`),
  `scripts/generate_hc_year_gap_csv.py` (`--dead-ids`),
  `judex/sweeps/shard_launcher.py` (`strategy` param on both launchers),
  `judex/cli.py` (`--excluir-mortos` on varrer-processos,
  `--estrategia-shard` on both sharded commands),
  `tests/unit/test_sweep_items_dir.py` (bare-dict expectation),
  `tests/unit/test_generate_hc_year_gap_csv.py` (dead-ID exclusion),
  `README.md` (Fluxo completo + §7.3 proxy-dir + §8 cliff recovery).
- **Test count**: 475 → **527** (+52 this cycle counting prior unpushed
  changes).

---

# Strategic state

## What just landed (most recent cycle)

- **HC 2026 v8+DJe full re-scrape pipeline** (2026-04-19 end-to-end).
  3,098 cases refreshed with v8 content (untruncated partes, pautas,
  DJe), 2,849 fresh PDFs downloaded, zero errors cumulatively across
  ~3 h of sweeps. Exactly matches the dry-run prediction for new
  downloads.

- **Dead-ID tombstone infrastructure** (commit `5def7c8`).
  `judex/utils/dead_ids.py` aggregates NoIncidente observations from
  every `sweep.state.json` under `runs/`. Confirms dead after ≥2
  observations with empty `body_head` (the canonical STF-unallocation
  signal, distinguished from proxy soft-blocks). Outputs:
  `data/dead_ids/<classe>.txt` (operational) + `.candidates.tsv`
  (audit). Integrated into `varrer-processos` via `--excluir-mortos`
  and into `generate_hc_year_gap_csv.py` via `--dead-ids`.

- **Interleave CSV sharding as new default** (commit `6b9b3b5`).
  Range-partitioning concentrated correlated workload in early shards
  whenever the input CSV was sorted by a workload-correlated
  dimension. Round-robin `row_i → shard (i % N)` is distribution-
  invariant. Validated mid-session: a 774-case PDF recovery ETA'd at
  79 min under range finished in ~6 min under interleave. Flag:
  `--estrategia-shard {interleave,range}`, default `interleave`.

- **List-wrap gotcha fixed at source** (commit `8fb855a`).
  `_write_item_json` now writes bare dict, matching canonical
  `data/cases/<CLASSE>/` shape. `--diretorio-itens data/cases/HC` is
  safe to use directly — no promote-with-unwrap step. Reader
  tolerance (`_load_case_records`, `reshape_to_v8`) retained for
  legacy files.

- **README pipeline docs** (commits `ba75678`, `9761e58`). New §Fluxo
  completo with 5-step pipeline flow + skip-condition table + concrete
  2026 HC example. §7.3 documents the `proxies.<letter>.txt` directory
  convention. §8 troubleshooting gains CliffDetector collapse with 4-step
  recovery ladder.

- **Warehouse CLI test coverage** (commit `adc3d73`).
  `test_atualizar_warehouse_cli.py` pins the Typer wrapper plumbing so
  a future refactor can't silently break `--saida` / `--ano` /
  `--classe`.

## In flight

Nothing executing.

## Backlog — ordered

Most of the prior-cycle backlog (analysis segmentation, rescrape
cliff, operational hygiene) is unchanged. New and updated items:

### Warehouse

1. **DJe warehouse flatten.** `publicacoes_dje` ships in v7/v8 but the
   warehouse builder has no `_flatten_publicacoes_dje`. The 2026
   sub-warehouse confirms this gap — 0 DJe rows despite RTF content
   in the peca cache.
2. **Rename `pdfs` table → `pecas`.** Table holds all peças (PDF + RTF);
   the name is stale. Queue for the next full rebuild.
3. **`content_version` column on `cases`.** Derived from `reshape_to_v8`
   provenance so analyses can filter to the "content-fresh" slice
   without `LIKE '%E OUTRO%'` heuristics.
4. **Decide on `data_protocolo_iso` redundancy** under v8.

### Data recovery

1. **Repeat the 2026 pipeline for 2023/2024/2025.** ~44,926 cases
   remain structurally v8 but content-stale. The infrastructure is now
   mature (interleave shards + dead-ID filter + `--excluir-mortos`).
2. **`extrair-pecas` on the 2,849 fresh 2026 PDFs** — text coverage
   unblocks cross-case text analysis for 2026.

### Operational hygiene

- **Bytes-cache suffix rename** `<sha1>.pdf.gz` → `<sha1>.bytes.gz`.
  Full playbook in prior archive. Queued; safe now that no sweep is
  live.
- **`baixar-pecas --excluir-mortos`** — minor diff (dead IDs already
  naturally skipped via missing case JSON), arguably not worth it.
- **Pre-filter `baixar-pecas` by cache-hit** — build an opt-in helper
  that drops CSV rows whose URLs are all cached, so fresh-only shards
  don't wait for cache-only shards to exit. Alternative to interleave
  for this specific workload.
- **Fix `scripts/monitor_overnight.sh`** — scope stale-shard alerts to
  the currently-active tier (prior-cycle item).
- **Index `{processo_id → path}` in `peca_targets.py`** — ~2 min of
  `rglob` CPU before first HTTP on a 79k-file tree (prior-cycle item).

### Scraper optimization (not blocking)

Ordered by ROI from the 2026-04-19 request-footprint audit:

1. **Delete `abaDecisoes.asp` fetch** (free; −1 GET; no downstream reader).
2. **Class-gate `abaRecursos.asp`** (skip on HC/AI by default; −1 GET).
3. **Audit + gate `abaDeslocamentos.asp`**.
4. **Class-gate `abaPautas` / `abaPeticoes`** on monocratic classes.

## Known limitations

- **Stale-cache content residue** in the main warehouse for 2023–2025.
  ~44,926 cases structurally v8 but content-stale (partes truncated
  at `#partes-resumidas`, pautas empty). 2026 is now content-fresh.
  Author-based analyses over 2023/2024/2025 still need the
  "E OUTRO" sentinel filter; 2026 is clean.
- **Main `judex.duckdb` pre-session data.** The 2026 slice is stale
  until we run the next full rebuild. Sub-warehouse
  `data/warehouse/judex-2026.duckdb` is fresh.
- **Scrapegw ASN vulnerability.** When scrapegw is degraded, 16 pools
  of scrapegw sessions don't bypass it (today's cliff pattern). A
  second proxy provider is the only true redundancy; we don't have
  one configured.

## Known gaps

- **`publicacoes_dje` → warehouse** (see Backlog § Warehouse #1).
- **PDF enrichment status tracking** — no persisted field answers
  "has this case been through PDF enrichment?" Derivable from
  `extractor` slots; rollup script proposed but not landed.

---

# Reference — how to run things

```bash
# Unit tests (~15 s, 536 tests)
uv run pytest tests/unit/

# Live probe of a sharded sweep (rich table, throughput, ETA, regimes)
uv run judex probe --out-root runs/active/<dir>
uv run judex probe --out-root runs/active/<dir> --watch 30   # auto-refresh

# Ground-truth validation
uv run python scripts/validate_ground_truth.py

# Full pipeline for one year (HC class, as done for 2026 this cycle)
#   1. Metadata sweep (sharded, interleave default)
uv run judex varrer-processos -c HC -i <lo> -f <hi> \
  --rotulo hc_<year> --saida runs/active/hc-<year> \
  --diretorio-itens data/cases/HC \
  --shards 16 --proxy-pool-dir config/

#   2. Aggregate dead-IDs (run periodically, not per-sweep)
uv run python scripts/aggregate_dead_ids.py --classe HC

#   3. PDF bytes (uses data/cases/ as URL source)
uv run judex baixar-pecas --csv <case-list> \
  --saida runs/active/hc-<year>-pdfs \
  --shards 16 --proxy-pool-dir config/ --retomar --nao-perguntar

#   4. PDF text extraction (zero HTTP; local)
uv run judex extrair-pecas -c HC -i <lo> -f <hi> --nao-perguntar

#   5. Warehouse rebuild
uv run judex atualizar-warehouse --ano <year> --classe HC \
  --saida data/warehouse/judex-<year>.duckdb
# Or full corpus:
uv run judex atualizar-warehouse
```

## Recovery from CliffDetector collapse

```bash
# If one or more shards cliff mid-sweep:
xargs -a runs/active/<label>/shards.pids kill -TERM

# Identify ungrabbed pids from each cliffed shard's sweep.state.json
# → build a recovery CSV covering only those pids

# Relaunch on direct IP (bypasses the degraded proxy pool):
nohup uv run python scripts/run_sweep.py \
    --csv <recovery.csv> --label <label>_recovery \
    --out runs/active/<label>-recovery \
    --items-dir <items_dir> \
    --resume --no-stop-on-collapse \
    > runs/active/<label>-recovery/launcher-stdout.log 2>&1 & disown
```

## Data model — peças → cases

Unchanged from prior cycle. See [prior archive § Data model](progress_archive/2026-04-19_2355_hc-2026-v8-pipeline-and-sharding-fixes.md#data-model--how-pecas-tie-to-cases) for the full three-hop layout (case JSON → URL → sha1 → cache quartet).
