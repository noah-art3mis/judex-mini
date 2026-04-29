# Current progress — judex-mini

Branch: `main`. Prior cycle archived at
[`docs/progress_archive/2026-04-21_0805_hc-2025-arm-a-8-shard-cliff-cascade.md`](progress_archive/2026-04-21_0805_hc-2025-arm-a-8-shard-cliff-cascade.md)
— arm A of the 8-vs-16 experiment: HC 2025 @ 8 shards, full-range
re-scrape (13,755 pids). Cliffed cascade overnight — 8/8 shards,
53.5% coverage (7,356 records), 6,399 pids in recovery queue. First
direct L3-per-exit-IP reputation gradient data.

**Status as of 2026-04-29 21:05 BRT.** Corpus: 90,762 cases.
PDF cache: **~86k `.pdf.gz`** (HC 2024 closed 15,997 ok / 0 fails;
HC 2023 closed 15,318 ok + 74 cached / 0 fails after a 34-URL
SSL-retry pass). Text cache: ~86k `.txt.gz` baseline; pypdf
extract resumed 2026-04-29 21:02 BRT (PID 559405) to absorb the
HC 2024 tail + HC 2023 new bytes. Warehouse rebuilt 2026-04-26
22:50 BRT, 286s wall-clock — needs another rebuild after extract
finishes.

**Active cycle: HC 2024 + HC 2023 peça backfill — closed.** See
[`docs/completion-tracker.md`](completion-tracker.md) for the
canonical per-year coverage table and priority queue (HC 2022
cases is the next backlog item, but needs proxy-pool refresh
first per CLAUDE.md).

The lab-notebook below this banner (§ Active task — lab notebook)
is the **prior cycle's writeup** (8-vs-16 shard A/B from
2026-04-21, closed). Overdue for archival; left in place until
session-boundary cleanup.

## Active task — HC 2024 + HC 2023 peça backfill (2026-04-26 → 2026-04-29)

### What landed this cycle

- ✅ **HC 2025 retry direct-IP** (2026-04-26 evening): closed the
  residual gap from 2026-04-22/24 substantive resume. **234 new
  bytes**, 12 min wall-clock, monolithic, zero failures. The
  warehouse said "7,488 missing"; case-JSON-walk dry-run said
  "234". 33× over-count. **New caveat pinned in the tracker
  (§ Warehouse-vs-case-JSON drift).**
- ❌ **HC 2025 retry sharded sweep** (2026-04-26, 2h10m wasted,
  killed): `config/proxies` was 5 days old; auth had expired;
  every fresh fetch hit `407 Proxy Authentication Required`. Zero
  bytes landed. **Lesson:** before any sharded launch, smoke-test
  the proxy pool with a 1-URL `curl --proxy <one-line>` — would
  have caught this in 30s. Forensic record at
  `runs/active/2026-04-26-hc-pecas-2025-retry/`.
- ✅ **HC 2024 main pass direct-IP + tail closeout** (2026-04-26
  22:08 → 2026-04-27 23:47): main pass landed **15,439 new bytes**
  across ~14h 56m overnight (53,745s elapsed). **22 SSLErrors
  (~0.14%); zero 403s** on `portal.stf.jus.br` — direct IP held
  WAF reputation cleanly all night. Latency flat: p50 801ms, p90
  1182ms. Throughput trajectory: 2.85 rec/s honeymoon → 0.54
  rec/s mid → 0.245 rec/s late. Tail (324 URLs) closed in a
  separate 311-second resume run 2026-04-27 23:42 UTC. **Final
  state: 15,482 ok + 515 cached + 0 fails (100% coverage).**
- ✅ **HC 2023 peça sweep direct-IP** (2026-04-29 03:33 → 16:28
  UTC, ~12h 55m): **8,218 new bytes** landed (resumed from a
  partial start of 7,066 cached). Hit a TLS-handshake degraded
  tail at hour 8 — 25 fails / 19 ok over 6h with each fail eating
  864s on SSL EOF; throttle controller demoted to `collapse`
  regime. **Self-healed in ~30 min with no intervention** —
  controller backed off frequency, IP cooled at the TLS layer,
  `under_utilising` regime resumed. Final main-pass state: 15,284
  ok / 74 cached / 34 SSL fails. 34-URL retry pass at 2026-04-29
  21:00 UTC cleared all 34 in 131s. **Final state: 15,318 ok + 74
  cached + 0 fails (100% coverage).** 0 × 403, 0 × 5xx across
  16,213 requests.
- ✅ **`extrair-pecas --provedor pypdf`** corpus-wide backfill
  (2026-04-26 20:55 → 2026-04-27 12:23, stopped manually):
  **5,132 new `.txt.gz` files extracted**. Walked 88,544 / 120,578
  substantive URLs (73%); the unwalked 27% are mostly `no_bytes`
  for years not yet downloaded. 42 `unknown_type` edge cases.
  Local-only, zero HTTP. **Resumed 2026-04-29 21:02 UTC** (PID
  559405, detached) to absorb the HC 2024 tail + HC 2023 new
  bytes; expected to flip ~24k `no_bytes` records to `ok`.

### Resume command for `extrair-pecas` corpus-wide backfill

State file at
`runs/active/2026-04-26-hc-extract-2025-retry/pdfs.state.json`
has 88,544 records done. To continue iterating the remaining
~32,000 corpus URLs (mostly `no_bytes`, will surface text files
for any new bytes that land between now and resume):

```bash
uv run judex extrair-pecas \
    --provedor pypdf \
    --saida runs/active/2026-04-26-hc-extract-2025-retry \
    --nao-perguntar
```

Local-only, zero HTTP, zero throttle. Cheap to leave running
while doing other work. After landing more bytes (e.g. HC 2024
tail or HC 2023 sweep), re-running `extrair-pecas` picks them
up automatically; the state file's "no_bytes" records get
re-checked and flip to "ok" once their bytes are present.

### Next priority (per refreshed tracker)

1. **`extrair-pecas` already running** (PID 559405, detached).
   Will flip ~24k `no_bytes` records to `ok` as it walks the new
   HC 2024 tail + HC 2023 bytes. Cheap to leave; check back in
   ~1h with `pgrep -af extrair-pecas` or
   `tail -f runs/active/2026-04-26-hc-extract-2025-retry/launcher-stdout-2.log`.
2. **Warehouse rebuild** — once `extrair-pecas` finishes (or at
   any natural stopping point), `uv run judex atualizar-warehouse`
   to fold the HC 2023 + HC 2024-tail text into the DuckDB.
3. **HC 2022 case sweep** — 11,900 missing cases, ~25 min at
   16-shard fresh-pool (after proxies refreshed). **Mandatory
   30-second proxy smoke-test before launch** — see lesson below.
   Once cases land, 2022 peça population becomes enumerable.
4. **Session-boundary cleanup**: archive this writeup to
   `docs/progress_archive/2026-04-29_*_hc-2024-2023-backfill.md`
   and start a fresh active-task block for HC 2022 / next cycle.

### Lessons pinned (this cycle)

- **SSL-EOF tail-storms self-heal in 30–40 min — don't kill,
  wait.** HC 2023's hour-8 tail saw 25 fails / 19 ok over 6h with
  each fail eating ~864s on `SSLEOFError(8, '[SSL:
  UNEXPECTED_EOF_WHILE_READING]')`. Effective rate dropped to
  0.002 rec/s. The throttle controller correctly demoted to
  `collapse` regime; backed off frequency; the IP cooled at the
  TLS layer; controller promoted back to `under_utilising` and
  the run finished cleanly with 0 final fails after a 34-URL
  retry pass. **Default action for SSL-EOF storms in `collapse`
  regime: wait 30 min, re-check.** Killing the worker would have
  thrown away the cooling that had already happened (TLS-layer
  reputation goes with the worker's connection state) and
  possibly re-tripped immediately on restart. This is **two-data-
  point pattern now** (HC 2024 had 22 SSL fails / 14h, HC 2023
  had 34 / 13h, both 0 × 403). SSL-EOF storms are a TLS-layer
  effect, completely separate from the 403 rate-limit
  behavior — different timescale, different recovery path.
- **Warehouse `pdfs_substantive` over-counts the operational fetch
  tail** by N× due to `sessao_virtual[]` fan-out (one sha1 → many
  warehouse rows). Always size sweeps from `--dry-run` output's
  "a baixar:" line, not from the warehouse "missing %" column.
  Lives now in `docs/completion-tracker.md § Warehouse-vs-case-JSON
  drift`.
- **A 5-day-old proxy file is an unverified proxy file.** 30-second
  smoke test before fanning out: `curl --proxy "$(head -1
  config/proxies)" -I https://portal.stf.jus.br/processos/`.
- **SIGTERM is honored cleanly when the worker is in active HTTP**;
  it's queued behind tenacity retry-backoff sleeps. Last night's
  sharded sweep needed SIGKILL because workers were stuck in
  ProxyError retry loops; tonight's direct-IP sweep took TERM
  immediately and wrote a clean `report.md` on exit.
- **`pkill -f "baixar_pecas"` (underscore) silently misses
  monolithic Typer launches.** The CLI form's argv reads
  `judex baixar-pecas …` (hyphen); only sharded children running
  `scripts/baixar_pecas.py` directly carry the underscore. The
  right pattern is `pkill -f "baixar[-_]pecas"` (or kill by PID
  from the launcher's stdout / `pdfs.state.json` directory).
  Tripped this once tonight: an earlier `pkill` no-op'd silently;
  caught only on the next status check when the same PIDs were
  still alive ~50 min later.
- **Don't extrapolate sweep ETA from the first 10 minutes.** The
  pre-WAF-engagement honeymoon throughput is structurally
  optimistic. Tonight: 2.85 rec/s in min 1–10 → 0.245 rec/s by
  hour 13. ~12× drop.

---



Single live file covering the **active task's lab notebook** and the
**strategic state** across work-sessions. Archive to
`docs/progress_archive/YYYY-MM-DD_HHMM_<slug>.md` when the active
task closes out or the file grows past ~500 lines.

For *conceptual* knowledge (how the portal works, how rate limits
behave, class sizes, perf numbers, where data lives), read:

- [`docs/data-layout.md`](data-layout.md) — where files live + the three stores.
- [`docs/stf-portal.md`](stf-portal.md) — URL flow, auth triad, field→source map, DJe flow.
- [`docs/system-changes.md`](system-changes.md) — timeline of STF-side + internal changes (DJe migration, schema v1→v8, Selenium retirement, known gaps).
- [`docs/rate-limits.md`](rate-limits.md) — WAF behavior, validated defaults, robots.txt posture.
- [`docs/process-space.md`](process-space.md) — HC/ADI/RE ceilings + density.
- [`docs/performance.md`](performance.md) — HTTP-vs-Selenium numbers, caching as the real lever.
- [`docs/warehouse-design.md`](warehouse-design.md) — DuckDB warehouse schema + build pipeline.
- [`docs/data-dictionary.md`](data-dictionary.md) — schema history v1→v8.

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration (marimo notebooks, one-off scripts, raw JSON dumps). Safe to fill freely.
- **`config/`** — git-ignored (credentials). Canonical proxy input is `config/proxies` (flat file, one URL per line; `#` comments + blank lines OK). Sharded launchers split it round-robin into N per-shard pools at `<saida>/proxies/proxies.<letra>.txt` at launch time. Older `config/proxies.{a..p}.txt` files are leftovers from the prior dir-based mode and can be deleted.
- **All non-trivial arithmetic via `uv run python -c`** — never mental math. See `CLAUDE.md § Calculations`.
- **Sweeps write a directory**, not a file. Layout in [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).

---

# Active task — lab notebook

## Task

**HC 2023/2024 backfill + 8-vs-16 shard experiment arm B + arm-A
recovery.** Three concrete deliverables from this cycle:

1. **Arm B — HC 2024 @ 16 shards.** The A/B's treatment arm. Generate
   `hc_2024_full.csv` via `--full-range --dead-ids`; launch all 16
   pools `proxies.{a..p}.txt`. Cooldown since arm A's last cliff is
   ~7h40m — past the overnight reset threshold per
   `docs/rate-limits.md § Two-layer model`. **With arm A's data in
   hand, the revised prediction is that 16 may cliff *less* than 8**
   (smaller per-shard slices → less time past L2 engagement horizon).
2. **Arm-A recovery** — 6,399 ungrabbed 2025 pids from cliffed
   shards. Build recovery CSV from each shard's `sweep.state.json`
   (pids present in input CSV but missing from state); relaunch
   direct-IP single-thread with `--no-stop-on-collapse`. Yesterday's
   2026 recovery did this in ~45 min for 654 pids — so ~7–10h for
   6,399 is the budget. Queue **after** arm B to avoid confounding
   pool state.
3. **Arm C — HC 2023** at the winner's cadence. Only after the A/B
   writeup.

## Experiment — 8 vs 16 shards (arm B pending)

Arm A is complete; see archive 2026-04-21_0805 for the full
writeup. **Cliff cascade forced a metric recast** — instead of
"wall-clock to finish 13,755 pids", compare arms on: (i) records
landed per hour of productive work, (ii) coverage at fixed
wall-clock (e.g. at the 3h mark), (iii) cliff count per shard-hour.

**Revised hypothesis** (the key recalibration from arm A): the
original framing missed a third axis — **per-shard workload size vs.
L2 engagement window**. Arm A's 1,720-pid-per-shard slice kept shards
in the post-L2 danger zone 4.4× longer than 2026's 387-pid slices.
At 16 shards, per-shard workload roughly halves, so each shard may
finish before sustained axis-B engagement. The A/B now tests three
competing effects:
(i) pool-independence gain (favors 16),
(ii) per-pool request-rate penalty (favors 8 if ASN-level),
(iii) per-shard-time-in-danger-zone (favors 16 on large workloads).

**H4 — Pool-headroom-vs-workload budget model.** A new,
falsifiable prediction derived from arm A's cliff-ordering data.

A shard cliffs iff its *workload_time* exceeds its pool's
*effective_budget*:

  workload_time      ≈ slice_size / rps                   (observed rps ≈ 0.15)
  effective_budget   ≈ N_proxies × T_L2 − residual_L3_debt (N=10, T_L2≈25 min)

The pool's fresh theoretical budget is 10 × 25 min ≈ **4h 10m**.
Residual L3 debt from yesterday's session scales linearly with how
much scraping each IP in the pool absorbed the day before —
empirically estimated from arm A's cliff-order data:
- Pools that finished yesterday clean (`a`): **~3h effective**
- Pools that finished yesterday seasoned (`b`, `d`): **~2h effective**
- Pools that finished yesterday hot (`c`, `e`, `f`, `g`): **~1–2h effective**
- Pools that finished yesterday already-cliffed (`h`): **~35 min effective**

**Predicted cliff behavior per arm:**

| Arm | Shards | slice | workload_time | typical budget | cliff? |
|-----|--------|-------|---------------|----------------|--------|
| A (observed)    | 8  | 1,720 | ~3h 10m | 0.5–3h after debt | **8 / 8 cliffed** ✓ |
| B (prediction)  | 16 |   899 | ~1h 40m | ~2–3h after 36h-idle (fresh ~160 IPs) | **≤ 3 / 16 cliffed** |
| 2026 (observed) | 8  | 387   | ~45m    | ~3–4h (fresh-ish)          | **3 / 8 cliffed** (workload borderline) ✓ |

Arm B scrape target confirmed at **14,387 pids** (range
236,529..250,915, 11,113 on disk, 0 confirmed deads in range). The
total workload is only ~5% larger than arm A's 13,755 — so any
cliff-count improvement on arm B is attributable to per-shard
slice size (899 vs 1,720), not less total work. Controlled
comparison.

Arm B's 16 pools will have had ~36h idle by launch (21h overnight
gap + another ~15h from arm A ending to arm B starting). That's
closer to the "overnight full reset" threshold than arm A got, so
residual-L3 should be lower per pool than arm A saw — further
favoring the "≤ 3 cliffs" prediction.

**H4 falsification test.** If arm B at 16 shards / ~860 pids
cliffs ≥ 6 of 16 shards, the headroom-budget model is wrong (or
missing a term, e.g. request-rate-density effects, WAF time-of-day
behavior, or pool-independence violation via ASN-level
degradation). If arm B cliffs ≤ 3, the model is supported and
becomes the operational planning heuristic for arm C and future
backfills ("size per-shard slice ≤ 70% of pool's effective budget,
accounting for residual debt").

**H5 — Sticky session duration: 10 min → 5 min.** Piggyback
experiment on arm B. Scrapegw's sticky-session knob controls how
long a session ID holds an exit IP reserved before the sticky
expires. Our driver rotates session IDs every 270s (~4.5 min) by
time-based rotation, so:

- **sticky=10** (current): IP is held for the full 10 min; after
  we rotate off at 4.5 min, the IP sits idle-reserved to our
  account for another 5.5 min. Any residual reputation debt
  ages during that idle window but the IP can't be re-leased
  to someone else mid-sticky.
- **sticky=5** (proposed): IP is released ~30s after we rotate
  off at 4.5 min. Over a 3h sweep, each IP holds a tighter
  residency → scrapegw can recycle it out of our pool sooner →
  the "IPs that are ours today" set changes faster within the
  sweep, potentially spreading L3 reputation accumulation
  across more distinct upstream IPs.

**Hypothesis.** sticky=5 shortens the per-IP sustained-load
window by a factor of ~10/5 = 2× in steady-state, which should
modestly reduce per-IP L2 engagement at the cost of slightly more
session-cookie re-establishment overhead (first few requests on a
new IP are slower while auth triad warms).

**Confound.** Arm B changes **both** shard count (8 → 16) and
sticky duration (10 → 5) from arm A. A cleaner cliff count on
arm B can't cleanly attribute to either change alone. Two ways to
de-confound if results are interesting:

1. **Arm C — HC 2023 with sticky reverted to 10 min** at the
   shard count the A/B picks. Compare cliff rate vs arm B → shows
   sticky effect in isolation.
2. Or: run a small targeted A/B on the 6,399-pid arm-A recovery
   CSV, one half at sticky=5 and the other at sticky=10 — closer
   sample size, same pool state. Cheaper.

**Falsification.** If arm B's cliff count is indistinguishable from
the H4-predicted range (≤ 3), sticky change likely didn't help or
hurt. If arm B cliffs ≤ 1 (meaningfully better than H4 predicts),
sticky=5 is plausibly contributing. If arm B cliffs ≥ 6 with
sticky=5 while H4 predicted ≤ 3, sticky=5 may actually hurt.

**H6 — Proxy freshness dominates throughput, not shard count or
sticky duration.** Live evidence from arm B (2026-04-21, 13.5 min
in): cluster throughput 10.52 rec/s vs arm A's peak 1.24 rec/s
(~8.5×). Decomposition:

- 2× from shard count (8 → 16), linear parallelism.
- **4.4× from per-shard throughput (0.15 → 0.66 rec/s)** —
  dominant factor.

The 4.4× per-shard gain traces almost entirely to **tenacity
retry-403 chains not firing** on fresh IPs. Arm A driver logs
show records returning `ok` with walls of 5–13s (tenacity
absorbing 403s and averaging in exponential backoff). Arm B
driver logs show walls of 0.5–1.5s (one HTTP call per record, no
retries). Per-IP L1 reputation (~80–100 req / 5-min window) is
at zero for freshly-fetched proxies, so requests don't nudge
into 403 territory → no retries to absorb → ~5–10× faster
per-request walls.

**Operational consequence (high confidence, landed as ops
heuristic):** the highest-leverage knob for sweep throughput is
**refreshing proxies before every sustained scrape**. Proxy
freshness > shard count > sticky duration > everything else. A
fresh 160-IP batch from scrapegw before each year's backfill
gets us arm-B-equivalent speed; reusing yesterday's pool gets us
arm-A-equivalent cascade.

**Falsification / controlled follow-up.** Can't cleanly isolate
proxy-freshness from (i) time-of-day effects (arm A ran evening
BRT vs arm B's early morning) and (ii) sticky-5 vs sticky-10.
Clean test: run arm-A's remaining 6,399-pid recovery CSV twice —
once with yesterday's `config/proxies.{a..h}.txt` (sticky-10, old
IPs) and once with `config/proxies` (fresh, sticky-5), at the
same time of day. If freshness dominates, the fresh run is ≥ 3×
faster per-shard regardless of time match. Queue under § Data
recovery below.

**Decision rule** (updated for the recast metrics) — apply after
arm B completes:
- **16 wins** → 16-arm coverage at 3h is ≥ 1.3× 8-arm's **and**
  cliff_count_B ≤ cliff_count_A. Use 16 for arm C.
- **16 loses** → 16-arm coverage at 3h is < 0.8× 8-arm's **or**
  cliff_count_B ≥ 1.5× cliff_count_A. Use 8 for arm C.
- **Ambiguous** → default to 8 conservatively, flag for follow-up.

## Next steps

**Completed this session:** arm B (HC 2024 @ 16 shards, 92% in ~32 min),
arm C launched (HC 2023 @ 16 shards, in flight from 09:16 BRT). A/B
decision landed: **16 wins, 8 retired for sustained jobs.** Full
writeup: [`docs/reports/2026-04-21-8-vs-16-shards.md`](reports/2026-04-21-8-vs-16-shards.md).

**What's still ahead** (HC 2025 PDF sweep stopped at ~58% for a
reboot — resume command in § In flight; parallel-safe zero-HTTP
queue also listed there):

a. ✅ **Arm-A + arm-B + arm-C recovery pass** — *landed 2026-04-21*.
   7,672-pid union-recovery at 16 shards; 96.0% / 1 cliff / 43.5 min
   wall-clock. See § In flight § Recently completed for the H6
   lesson (non-refreshed pool cost 3.6× throughput). 305-pid
   shard-k residue deferred per § Data recovery #3.
b. **`baixar-pecas` for 2023/2024/2025** — new PDFs from v8 content
   path (arms A/B/C + recovery fresh case JSONs now have accurate
   `documentos[]` link lists). Separate WAF counter on
   `sistemas.stf.jus.br`, 16 shards safe (doesn't share reputation
   with `/processos/*`). **Refresh proxies first** per H6 — don't
   repeat today's 3.6× cost of skipping the preflight.
c. **`extrair-pecas` on newly-downloaded PDFs** — zero HTTP, local
   CPU. Provider choice (`pypdf` cheap / `mistral` | `chandra` high
   quality) decided per-tier.
d. **Full warehouse rebuild** at end-of-cycle. One atomic swap picks
   up all fresh content from arms A/B/C + recovery + PDFs +
   extraction. Build-stats validation now catches silent regressions
   (DJe at 0% will show as WARN, loud signal if any other field
   regresses).
e. **DJe content re-capture (not warehouse flatten).** Warehouse
   flatten turned out to already exist; the real gap is the
   extractor regression — STF migrated DJe to `digital.stf.jus.br`
   on 2022-12-19 and our scraper still hits the stub-serving old
   endpoint. Pick **§ Backlog DJe capture path 1** (andamentos-side
   metadata, 1–2h) for a cheap 80% unblock; **path 2** (Playwright
   for the new platform, 1–2 days) when full DJe index is worth
   the infra cost. Full diagnosis in § What just landed.

## Practical tips from today's experiments (landed as ops discipline)

These are the reusable rules extracted from the 8-vs-16 A/B. The
*situational* numbers live in the report; the *rules* live here.

1. **Proxy freshness is the single highest-leverage knob** (H6,
   strongly supported). The 4.4× per-shard throughput jump from arm A
   to arm B traces almost entirely to tenacity retry-403 chains *not*
   firing on fresh IPs. Refresh the pool before every sustained
   sweep — this dominates shard count and sticky duration combined.
   **Preflight step, not a tweak.**
2. **16 shards + fresh pool + sticky=5 is the default** for
   year-backfill workloads. 8-shard config retired for sustained
   jobs (remains available for small/ad-hoc sweeps).
3. **H4 sizing heuristic** (confirmed by arm B). Size per-shard slice
   so `workload_time ≤ 0.3 × effective_budget`. Practical shortcut:
   **keep each shard ≤ ~800 pids on a freshly-fetched pool.** The
   ~7,546-pid recovery at 16 shards = 472 pids/shard, ratio 0.08 —
   safe by a wide margin.
4. **One proxy file, one flag.** Both `varrer-processos` and
   `baixar-pecas` take `--proxy-pool FILE` (a flat list, one URL per
   line; `#` comments + blank lines tolerated). In sharded mode the
   launcher round-robin-splits the file into N per-shard pools at
   `<saida>/proxies/proxies.<letra>.txt` automatically. Paste a fresh
   scrapegw batch into `config/proxies` once; never maintain
   per-pool files by hand.
5. **L3-per-IP reputation persists across days.** Arm A's cliff
   ordering matched each pool's state at the *prior day's* 2026 sweep
   end — overnight idle partially clears but not fully. Consequence:
   a "rested but used" pool is not the same as a fresh one. When in
   doubt, refresh.
6. **CliffDetector axis-B window-full gate** (landed this session).
   p95 is only consulted once the rolling window fills (n = window
   size, default 50). Axis-A (WAF-shaped fail rate) stays un-gated
   so V-style collapse still catches early. Eliminates the n=20
   false-positive class arm B's shard-o hit.
7. **Unmeasured confounds to stay honest about:** time-of-day (arm A
   evening BRT vs arm B morning BRT) and ASN-level WAF thresholds
   above 16 shards (~63 STF req/s on arm B; 32 shards would push
   ~125 req/s). **Land § Backlog Request-footprint reduction items
   before any 32-shard experiment** — each cuts 15–20% of per-case
   STF HTTP calls; stacked, they buy a 30–50% politeness cushion.
8. **A second proxy provider is the only true redundancy** against
   scrapegw L3-per-IP decay. Not acted on yet; logged as the one
   structural hedge against today's single-provider fragility.

## Throughput + regime baselines (anchor for future predictions)

Empirical numbers from today's runs + prior validations. Use these
to set expectations *before* a sweep launches; deviations are the
signal that something's off (pool fatigue, time-of-day, WAF policy
shift). All "per-shard rec/s" are steady-state medians, not peaks;
cluster rec/s = per-shard × N_shards. Regime % = share of records
in the named regime over the whole sweep.

### `varrer-processos` (case JSON, `portal.stf.jus.br`)

| config                                          | per-shard rec/s | cluster rec/s | typical regime mix              | cliff rate    |
|-------------------------------------------------|-----------------|---------------|---------------------------------|---------------|
| 1 worker, no proxy (sweep E baseline)           | ~0.28           | ~0.28         | 90% good, 10% warn              | n/a (1 worker)|
| 4 shards + aged proxies (sweep V validation)    | ~0.26           | ~1.02         | 75% good, 20% warn, ~5% l2      | low           |
| **8 shards + aged proxies** (arm A)             | **0.15**        | **1.24**      | 60% good, 30% warn, 10% l2      | **8 / 8 (cascade)** |
| **16 shards + fresh proxies** (arm B)           | **0.66**        | **10.52**     | 95% good, 5% warn, 0% l2        | 2 / 16 (genuine) |
| **16 shards + fresh proxies** (arm C, smaller)  | **0.65**        | **9.0**       | 96% good, 4% warn, 0% l2        | 0 / 16        |
| **16 shards + 8h-cooled-not-refreshed** (recovery) | **0.22**     | **3.45**      | 78% good, 12% warn, 1.6% l2     | 1 / 16        |

Rules-of-thumb derived:
- **Per-shard floor ≈ 0.15 rec/s** when retry-403 chains are firing
  (aged pool + portal-WAF-fatigue). Anything below this means proxies
  are exhausted; investigate before continuing.
- **Per-shard ceiling ≈ 0.7 rec/s** on a fresh batch — bottlenecked
  by the 5-XHR-fan-out per case + proxy wall, not WAF.
- **Cluster throughput is roughly linear in shard count** as long as
  per-shard stays in the green; sub-linear when individual shards drop
  into warn/l2.
- **`good` < 80% over a full sweep** = the pool is no longer fresh
  for this host; refresh it or expect a cliff cascade.

### `baixar-pecas` (PDF bytes, mostly `portal.stf.jus.br`)

| config                                              | per-shard rec/s | cluster rec/s | typical regime mix    | cliff rate |
|-----------------------------------------------------|-----------------|---------------|-----------------------|------------|
| 16 shards + portal-fatigued pool (HC 2025, 2026-04-21) | **0.06–0.17** | **2.14**      | mostly ok, sparse fail/http_error | none observed yet |
| 16 shards + fresh pool against `sistemas` host (no clean datapoint) | (projected) ~0.7 | (projected) ~12 | (projected) all ok    | n/a        |

`baixar-pecas` is bytes-only (one GET per PDF, no XHR fan-out), so on
a fresh-vs-host pool it should outpace `varrer-processos` per shard.
The current 2025 sweep is much slower because andamento attachments
come from `portal.stf.jus.br/processos/downloadPeca.asp` — the same
WAF bucket as case JSONs, which our pool already exhausted today.
**The fresh-host projection is unmeasured** — the next 2024 PDF run
on a refreshed batch is the cleanest opportunity to nail it down.

### Regime ladder reference

Source: `docs/rate-limits.md § Operating regimes`. CliffDetector
classifies each rolling window of records into one of:

| regime              | meaning                                            | typical fail-rate | action                       |
|---------------------|----------------------------------------------------|-------------------|------------------------------|
| `under_utilising`   | wastefully polite; pool has slack                  | 0–5%              | could push harder            |
| `healthy`           | steady scraping, L1 absorbed, L2 not engaged       | 5–10%             | nothing — this is the target |
| `l2_engaged`        | Pareto frontier; as fast as WAF tolerates pre-block | 10–20%           | fine for short bursts        |
| `approaching_collapse` | adaptive block firing; retry budget at risk     | 20–30%            | rotation; consider stopping  |
| `collapse`          | V-style cliff; gaps < 15 records between cycles    | > 30%             | stop, cool down ≥ 60 min     |

Decision is the worse of axis A (WAF-shape-filtered fail rate) and
axis B (p95 wall_s). Both axes are window-full-gated as of
2026-04-21 to suppress the n=20 false-positive class.

## Per-year completion tracker (HC)

Moved to [`docs/completion-tracker.md`](completion-tracker.md) —
reference table for per-year HC coverage (cases / peça bytes / text),
the cache-integrity caveat (bytes ∪ text is larger than either alone),
and the backfill priority queue. Refresh the table using the snippet
at the bottom of that doc.

**Quick summary (2026-04-24, end-of-cycle):**
- ✅ Cases: 2026/2025/2024/2023 all content-fresh
  (3,099 / 13,365 / 12,014 / 11,129 in the warehouse).
- ✅ Peça bytes, 2025: **68% of substantive URLs** (16,685 / 24,414).
  Resume run finished 14:46 BRT in 5h 14m, 7,159 new PDFs, zero
  failures.
- ✅ Peça text, 2025: **97% of substantive URLs** (23,735 / 24,414).
  `extrair-pecas --provedor pypdf` ran in ~6 min, 6,740 new `.txt.gz`,
  419 corrupt-bytes parse failures (pre-existing tail).
- ✅ Warehouse rebuilt with streaming-chunks refactor: 309.7s, 1.3 GB,
  `n_pdfs = 49,406`, fits in <1 GB RAM (old list-accumulation peaked
  at 11 GB and OOM-killed WSL2).
- ❌ Peça bytes, 2023/2024: ≤2% of substantive URLs; no dedicated
  peça sweep yet. Text coverage (~28%) comes from legacy pre-split
  scrapes of sessão-virtual Relatórios/Votos.
- ❌ **Next backfill target: HC 2022** (~11,900 missing cases).

---

# Strategic state

## What just landed (most recent cycle)

- **Canonical lawyer classifier + judge↔lawyer network notebook**
  (this session, 2026-04-22). Extended
  `judex/analysis/lawyer_canonical.py` from a pure name canonicalizer
  into the project-canonical party classifier: new
  `LawyerKind` enum (`sentinel / placeholder / pro_se / institutional
  / juridical / court / with_oab / bare`), `LawyerEntry` NamedTuple,
  and `classify(nome) → (kind, key, oab_codes)` built on
  `canonical_lawyer()`. Accent-insensitive institutional-prefix match
  is the load-bearing fix — `DEFENSORIA PUBLICA DA UNIAO` (4,766 rows,
  no acute accents) was slipping past every ad-hoc `DEFENSORIA
  PÚBLICA` prefix check as a "bare" lawyer. Now it lands in
  `institutional`. Also catches OAB codes outside parentheticals
  (`OAB/SP 148022`, `OAB-PE 48215`) via `_extract_oab_anywhere`.
  +17 pinning tests; 568 total. Full-corpus bucket distribution
  (HC ADV): institutional 5,254 rows (70%), with_oab 1,405,
  sentinel 181, bare 579, placeholder 74, pro_se 4, juridical 2,
  court 0. On IMPTE: sentinel 3,012 (the "phantom IMPTE" rows the
  docstring warned about), institutional 8,726, with_oab 64,111,
  bare 18,470.

  CLAUDE.md `§ Non-obvious gotchas` now points all future notebooks
  at `judex.analysis.lawyer_canonical` — the failure-mode catalog
  (accent variants, non-parenthetical OABs, law firms, courts-as-
  parties, sentinel typos) is one call away instead of one regex
  per notebook away.

  Also shipped: `analysis/hc_judge_lawyer_network.py` — Marimo
  notebook with three reactive views. **(1) pyvis bipartite with
  Barnes-Hut physics** (Obsidian-style), sandboxed in an
  `iframe srcdoc` to stop pyvis's dark-theme CSS from bleeding
  into the host page. Plain-text tooltips (vis-network renders
  `title` via `innerText`, so `<b>` / `<br>` showed as literal
  text — switched to `\n` delimiters). **(2) log₂(lift) heatmap**
  clipped to ±4 to avoid outlier saturation. **(3) minister ↔
  minister cosine projection** on lawyer-distribution vectors.
  Reactive filters: top-N (default 60), min-pair edge count
  (default 2), year range (default 2015–2026), `LawyerKind`
  multiselect (default `[with_oab]` — the critical default,
  dropping `institutional` from the defaults because it swamps
  minister-cosine into 0.99-everywhere meaninglessness).

  Self-describing filter banner renders the active state + the
  universe size + the edge count at the top, so the exported
  snapshot documents itself. Snapshot shipped to
  `analysis/reports/2026-04-22-hc-judge-lawyer-network.html`
  (~200 KB with `with_oab`-only default).

  **Substantive finding:** `ADV.(A/S)` is ~72% institutional in
  the HC corpus — the banca-de-renome (Toron, Bottini, etc.) lives
  in `IMPTE.(S)`, not `ADV.(A/S)`. The two roles capture different
  institutional facts (filer vs. lawyer-of-record after possible
  DP takeover). For private-bar coverage use
  `analysis/hc_famous_lawyers.py`; this notebook is the ADV-rep
  map.

  **Old-vs-new `partes` format check** (by year): `"E OUTRO(A/S)"`
  tail prevalence dropped from ~3% in 2017–2021 to <1% in 2022+,
  confirming the scraper's split-row migration. Partes-per-case
  mean rose 1.03 → 1.13 in 2023–2024 (splitting visible in
  aggregate). `LawyerKind` bucket shares are stable across years
  (institutional 77-86%, with_oab 13-25%) — classifier is
  era-robust. Cross-year trend analysis on co-lawyers-per-case is
  NOT reliable without controlling for rescrape vintage though —
  an older case rescraped under the new scraper will suddenly
  show more ADV rows than it did before.

- **Warehouse build-stats validation** (this session). Added
  population-rate thresholds per case-level field (`partes`,
  `andamentos`, `pautas`, `sessao_virtual`, `publicacoes_dje`) to
  `judex/warehouse/builder.py` as `MIN_POPULATION_RATES`. After
  every build, the stats print to stdout + threshold misses produce
  warnings that show up in `BuildSummary.validation_warnings`. New
  `--estrito` flag (`judex atualizar-warehouse --estrito`) promotes
  warnings to a non-zero exit for CI. **Caught the DJe-regression
  immediately on a live 2023 build**: `0.0% (threshold ≥ 5.0%) [WARN]`.
  Prevents the silent field-wide regression pattern that went
  undetected from 2026-04-19 through 2026-04-21. +4 tests; 547
  total.

- **DJe extractor regression — full diagnosis, no fix yet** (this
  session, via manual browser verification of HC 267809).

  **Root cause:** STF migrated DJe on **2022-12-19** (per the footer
  note on the old portal: *"Até o dia 19/12/2022, o Supremo Tribunal
  Federal mantinha dois Diários de Justiça Eletrônicos com conteúdos
  distintos"*). New DJe content lives at
  **`digital.stf.jus.br/publico/publicacoes`**, an entirely different
  host. Our scraper hits `portal.stf.jus.br/servicos/dje/listarDiarioJustica.asp`
  — which now serves only migration-redirect stubs for post-2022 DJe
  ("Para consultar essa publicação, acesse https://digital.stf.jus.br/…").
  Those stubs are rendered client-side via JS, so `requests` gets an
  empty shell; browsers show the redirect placeholders.

  **Other endpoints explored + ruled out:**
  - `portal.stf.jus.br/servicos/dje/pesquisarDiarioJustica.asp` —
    historical (pre-2022-12-19) archive. **403 on GET**, and the
    form expects `Número DJ/DJe` or `Período` (date range) — not
    incidente-keyed, so can't be used as a drop-in fix even for old
    cases.
  - `abaDecisoes.html` (cached as part of each case scrape) — lists
    *internal* STF decisions (5 "Decisão" mentions in HC 228072) but
    **0 DJe URLs**. Not a fallback.
  - `digital.stf.jus.br/publico/publicacoes` (the real post-2022
    source) — returns `202` + AWS WAF challenge JS from
    `token.awswaf.com`. Requires a headless browser to pass.

  **Consequence:** 0 of 3,118 2026 HCs + 0 arm A/B/C = 0% DJe capture
  across all 2023–2026 content. HC 125290's 4 DJe entries (and the
  other ~10 pre-2022 cases with DJe) are pre-migration carry-forward
  via `reshape_to_v8`, not live capture — those files were written
  when the old endpoint still returned server-rendered DJe content.
  Pre-2022 DJe is effectively frozen at what we already have; no
  systematic re-fetch is possible via GET.

  **What we still get without fixing DJe:**
  - `andamentos` already capture each `"ACÓRDÃO PUBLICADO, DJE N"` /
    `"DECISÃO PUBLICADA"` event as a structured row with date — so
    "when did this case get a DJe publication?" is answerable from
    andamentos alone.
  - `sessao_virtual[].documentos[]` still capture the Voto / Relatório
    PDFs → `baixar-pecas` + `extrair-pecas` already ingest the full
    decision texts. The missing piece is the *DJe index envelope*
    (DJE number, section, divulgation date) as a separate structure,
    not the decision texts themselves.

  **Three viable paths forward, queued (not picked):**
  1. **Andamentos-side DJe metadata extraction** (cheap). Parse
     `"DJE 123 de 05/02/2025 ..."` patterns from andamento strings,
     emit structured `{dje_numero, dje_data, secao}` alongside the
     existing andamento row. Small regex + schema addition; gets
     ~80% of DJe-level warehouse queries working without touching
     the external endpoint.
  2. **Playwright integration for `digital.stf.jus.br`** (real fix).
     Headless browser loads the page, solves the AWS WAF challenge,
     captures the `aws-waf-token` cookie, then `requests` uses that
     cookie for the actual API calls (the new platform is a SPA
     backed by a JSON API — once past WAF, direct-to-hit). New
     dependency, ~1–2 days of integration work, most reliable
     long-term.
  3. **AWS WAF challenge reverse-engineering** (brittle). Python
     libraries exist (`aws-waf-token` solvers) but STF can flip the
     challenge type (reCAPTCHA, Turnstile) at any time. Not
     recommended.

  **Build-stats validation will keep this visible.** Every future
  warehouse build will print `publicacoes_dje: 0.0% (threshold ≥ 5.0%)
  [WARN]` until path 1 or 2 lands. Don't silence — the warning is
  load-bearing.

- **CliffDetector axis-B window-full gate** (this session). Axis B
  (p95 wall_s) was firing false positives at n=MIN_OBS=20 because
  `int(0.95 * 20) = 19` made p95 equal to the max element — a single
  slow HTTP record with no retries/no fails could trip collapse. Fix:
  `p95` is only consulted once the rolling window is full (n == 50
  for default window size). Axis A (WAF-shaped fail rate) remains
  un-gated so V-style collapse still catches early. Caught by arm B's
  shard-o which cliffed at 20/899 on a single 66.67s HTTP record with
  zero WAF signal. +2 tests; 1 existing test updated to use 55 targets
  so the window actually fills. **Arm B's shard-o is officially
  flagged as a detector false-positive**, not a genuine cliff, for
  the A/B writeup's honesty.

- **Arm A — HC 2025 @ 8 shards cliff cascade** (full details in
  archive `2026-04-21_0805`). 53.5% coverage at 3h03m productive
  wall-clock; 8/8 shards cliffed across a 2.5h window. First direct
  L3-per-exit-IP reputation gradient measurement — cliff order
  matched pool state at yesterday's 2026 end.

- **`judex probe` CLI** (commit `865f6d9`). Rich-table live view of
  sharded sweeps — done/target, %, rec/s, min pid, severity-ordered
  colored regimes, elapsed/ETA. `--watch N` auto-refresh.
  Canonical monitoring surface; replaces the ad-hoc
  `scripts/probe_sharded.py` invocations. +7 tests.

- **`--full-range` mode on `generate_hc_year_gap_csv.py`** (same
  commit). Keeps on-disk pids in the output — only confirmed deads
  are filtered. Used for year re-scrapes where content-staleness of
  existing files can't be cheaply detected (`mtime` was clobbered by
  v8 renorm). +2 tests.

- **Progress doc refactor** (commit `08b19b0`). Marked 2026 ✅,
  spec'd 8-vs-16 experiment, archived prior cycle.

Tests: **538 green**. Cumulative cache: 1.5 GB PDFs, 90,196 HC cases.

## In flight

**HC 2022 case-JSON backfill — three direct-IP cycles, 69.4%
coverage, cycle 4 awaiting cooldown decision** (snapshot
2026-04-25 21:12 BRT). Range mode `HC 210825..223881` (13,057
pids; 1,160 already on disk pre-launch). Run dir:
`runs/active/2026-04-24-hc-cases-2022-direct/`. Items land directly
in `data/source/processos/HC/` via `--diretorio-itens` — no copy step.

**Three-cycle pattern (all axis-B p95-wall_s collapses, none from
hard 403-fails — tenacity absorbs 403s as `status=ok` records with
inflated walls; axis-B trips on the wall p95):**

| cycle | cooldown before        | wall    | fresh ok records | end records / coverage |
|-------|------------------------|---------|------------------|------------------------|
| 1     | n/a (cold)             | 3h 28m  | +2,454           | 2,833 / 27.7%          |
| 2     | 6.2 h                  | 6h 49m  | +3,904           | 7,912 / 51.2%          |
| 3     | 1.0 h (driver minimum) | 3h 47m  | +2,375           | 10,857 / 69.4%         |

**Empirical rule (new — pin into throughput baselines).** Cooldown
duration scales productive volume roughly linearly at **~400
records per hour of cooldown** for direct-IP `varrer-processos`
against `portal.stf.jus.br/processos/*`. Confirms H6's "L3-per-IP
reputation persists across days" tip — partial recovery yields
proportional productive window.

**State as of cycle 3 cliff:**
- ok records on disk: **9,063 / 13,057 ≈ 69.4% of HC 2022 width**
- NoIncidente fails accumulated: **1,794** (all single-observation
  candidates in `HC.candidates.tsv`; will promote to confirmed
  `HC.txt` on the next *independent* HC 2022 sweep)
- 142 cumulative 403-retry chains absorbed across three cycles
- 3 SSLErrors in cycle 2 (cliff-aligned WAF connection drops with
  `SSL: UNEXPECTED_EOF_WHILE_READING` — same RST-injection
  signature as the 2025 PDF sweep stop on 2026-04-23)
- remaining unvisited: **2,200 pids** (HC 218737 .. 223881 minus
  cliff residue from cycles 1–3)

**Aggregator same-sweep-dedup gotcha (newly discovered this
session).** `scripts/aggregate_dead_ids.py` counts at most ONE
NoIncidente observation per pid per source sweep dir. So
in-session re-probes (which `--retomar` does for `status=fail`
rows) don't help promotion. The 1,794 candidates will only
graduate when a **different** sweep (different `runs/active/<X>/`)
independently observes them as NoIncidente. Consequence:
`--excluir-mortos` is a no-op for the cycle 4 resume; remaining
2,200 pids must be re-probed even though many will return
NoIncidente again. Concrete numbers from cycles 1–3:
- pre-sweep `HC.txt`: 6,980 confirmed deads, none in 2022 range
- after cycle 1 + aggregator run: 6,980 → 7,602 (+622, none in
  2022 range — the +622 were 2023+ candidates from prior runs that
  finally crossed threshold via this run as the "second" sweep)
- after cycle 3 + aggregator run: still 7,602 (in-session re-probes
  don't bump the per-sweep observation counter)

**Cycle 4 resume options** (pick before relaunching):

1. **Wait overnight (~8h) → single cleanup cycle finishes 2022.**
   Per the empirical rule, 8h cooldown projects ~3,200 productive
   records — well over the remaining 2,200, so cycle 4 should
   finish without cliffing. **Recommended.**
2. **60-min cooldown → cycle 4 likely cliffs at ~99% with a tiny
   cycle 5 mop-up.** Per the rule, 1h yields ~400 records; 2h
   yields ~800 — short of 2,200. Two-cycle finish.
3. **Sharded fresh-pool resume.** Requires (i) refreshing
   `config/proxies` from scrapegw (currently 4 days stale; only
   159 IPs — H6 says non-refreshed is 3.6× slower) and (ii)
   building a CSV from the unvisited remainder (sharded mode
   requires `--csv` per Typer help). Then 16 shards finishes 2,200
   pids in ~3–4 min wall. Costs one fresh proxy batch.

**Cycle 4 launch command** (identical to cycles 2 + 3; `--retomar`
skips the 9,063 ok rows; will start by re-probing the 1,794
NoIncidente fails — fast burst at ~0.07s each — then advance to
fresh new pids):

```bash
cd /home/noah-art3mis/projects/judex-mini
nohup uv run judex varrer-processos \
    --classe HC --processo-inicial 210825 --processo-final 223881 \
    --saida runs/active/2026-04-24-hc-cases-2022-direct \
    --rotulo hc_2022_direct \
    --diretorio-itens data/source/processos/HC \
    --retomar \
    >> runs/active/2026-04-24-hc-cases-2022-direct/launcher-stdout.log 2>&1 &
disown
```

**Health-check snippet** (since `judex probe` doesn't apply to
single-process direct-IP runs):

```bash
# pid alive?
pgrep -af 'varrer-processos.*hc_2022_direct' | grep -v 'pgrep\|grep'
# aggregate counts (per-pid keyed state — NOT {ok,fail,total} shape)
uv run python -c "
import json, collections
s = json.load(open('runs/active/2026-04-24-hc-cases-2022-direct/sweep.state.json'))
c = collections.Counter(v.get('status') for v in s.values() if isinstance(v, dict))
print('records:', sum(c.values()), '·', dict(c))
"
# regime trajectory (cliff is imminent if recent windows show
# approaching_collapse > 50% of last-200)
uv run python -c "
import json, collections
from pathlib import Path
recent = []
with Path('runs/active/2026-04-24-hc-cases-2022-direct/sweep.log.jsonl').open() as f:
    for line in f:
        recent.append(json.loads(line).get('regime'))
print('last-200 regime:', dict(collections.Counter(recent[-200:])))
"
```

**Lessons-learned (pin):**
- `--nao-perguntar` is a `baixar-pecas`-only flag; `varrer-processos`
  is non-interactive by default. Crashed the first launch attempt.
- `sweep.state.json` is per-pid keyed (`HC_<pid>` → record), not
  the `{ok,fail,total}` aggregate shape `agent-sweeps.md` documents
  — monitor by tallying `.values()`, not by reading aggregate keys.
- Driver-side ETA is unreliable mid-cycle: it averages over both
  ~0.05s dead-pid re-probes (when `--retomar` is replaying fails)
  and the ~0.17 rec/s sustained productive rate. Trust the sustained
  number, not the driver's printout.
- `--retomar` skips `status=ok` rows but RE-PROBES `status=fail`
  rows. Cycle-startup is therefore a fast burst through prior fails
  before reaching truly fresh pids. Useful for confirming dead pids
  but doesn't help confirmed-dead promotion (see same-sweep-dedup).

---

**Stopped 2026-04-22 ~19:52 BRT for a host reboot — resume after
boot.** `baixar-pecas` HC 2025 direct-IP sweep was halted with
SIGTERM → SIGKILL after the graceful handler hung on a stuck HTTP
request. State file (`pdfs.state.json`, 12.8 MB) parses cleanly;
per-URL atomic writes mean at most one in-flight URL was lost.

**Final stop snapshot:**
- run dir: `runs/active/2026-04-22-hc-pecas-2025-direct/`
- URLs in state: **29,326** (15,418 cached · 13,902 ok · 6 http_error)
- launcher counter at stop: **~29,330 / 50,526 (≈ 58%)**
- cases visited: **7,198 / 13,755 (52.3%)** — ~6,557 cases remain
- recent throughput: 0.50 rec/s (60s window) / 0.34 rec/s (long run)
- error pattern: 5 SSLError + 1 ConnectionError, **zero 403s** —
  direct host IP showed no WAF pushback all day; this is the first
  clean datapoint that contradicts yesterday's "portal-fatigued"
  baseline (see § Throughput baselines, `baixar-pecas` row).

**Resume command** (after reboot — single-process, identical to
the launch invocation; `--retomar` skips everything in
`pdfs.state.json` and continues from the next CSV row):

```bash
cd /home/noah-art3mis/projects/judex-mini
nohup uv run judex baixar-pecas \
    --csv tests/sweep/hc_2025_full.csv \
    --saida runs/active/2026-04-22-hc-pecas-2025-direct \
    --retomar --nao-perguntar \
    >> runs/active/2026-04-22-hc-pecas-2025-direct/launcher-stdout.log 2>&1 &
disown
```

**Verify resume took** (within 30s of relaunch — state size should
keep growing, launcher counter should advance past 29,330):

```bash
tail -5 runs/active/2026-04-22-hc-pecas-2025-direct/launcher-stdout.log
pgrep -af 'baixar-pecas' | grep -v 'pgrep\|grep'
```

**Estimated remaining work** (revised 2026-04-24 after measuring
bytes-landed properly via disk join, not text-present). Earlier
revisions conflated two different signals:

- The pre-filter estimate (`~21,200 URLs`, 12.8–17 h) was the full-
  tipos target list from the sweep's launcher banner. Still accurate
  if you resume under `--todos-tipos`.
- An intermediate revision said ~8,800 URLs / 5–7 h — that came from
  `pdfs_substantive.text IS NOT NULL` as the downloaded-proxy, which
  counts **extracted text**, not **landed bytes**. Those diverge
  wildly here because 31k+ sha1s in the cache have text without
  bytes (pre-split legacy extractions).

**Authoritative bytes-based estimate:** join `pdfs_substantive.sha1`
to the `.pdf.gz` filesystem set. 2025 tier-A: 9,776 of 24,174 URLs
have bytes (40%). **Remaining ≈ 14,400 tier-A URLs.** At 0.34–0.50
rec/s observed, wall-clock ≈ **~8–12 h**. Resume under the new
`--apenas-substantivas` default (on since commit `e7ce6af`,
2026-04-23) so the sweep only targets tier-A/B. If the host IP is
still as clean post-reboot as it was today, expect the lower end.
If the WAF starts pushing back (any 403s in the first 200 records),
abort and switch to the proxy-pool path per § Reference.

See [`docs/completion-tracker.md`](completion-tracker.md) for the
per-year bytes/text breakdown and refresh snippet.

**Why no shards:** this is a single-process direct-IP sweep — the
launch invocation didn't include `--shards` / `--proxy-pool`, so
`judex probe` (which enumerates `shard-*` dirs) doesn't work on
this run. Probe equivalents:
`tail launcher-stdout.log` (true done/total counter),
`wc -l pdfs.log.jsonl` (rate),
`jq -s 'group_by(.status) | map({status: .[0].status, n: length})' pdfs.state.json`
(status breakdown).

**Follow-up: 22 http_error URLs to retry after main run finishes.**
On 2026-04-23 morning the workstation's captive-portal network
session expired, causing ~16 URLs to fail with `SSL:
UNEXPECTED_EOF_WHILE_READING` (RST-injection into long-running
TLS streams) before re-auth restored the network. Combined with
the 6 pre-stop errors, state now holds **22 `http_error`** (vs
15,418 cached · 14,152 ok at the time of note). These will NOT be
retried within the current run — the read-head has already passed
them. After the current sweep terminates and `pdfs.errors.jsonl`
is rewritten, drain them with:

```bash
uv run judex baixar-pecas \
    --retentar-de runs/active/2026-04-22-hc-pecas-2025-direct/pdfs.errors.jsonl \
    --saida runs/active/2026-04-22-hc-pecas-2025-direct \
    --nao-perguntar
```

`--retentar-de` skips the CSV entirely and processes only those
URLs, so the cost is ~22 HTTP requests, not a full re-scan.
Anything that stays in errors.jsonl after this retry is a real
permanent failure worth inspecting case-by-case.

### Parallel-safe queue (zero-HTTP, no WAF share)

Content-freshness for HC 2023–2025 covers 7,367 + 13,240 + 10,926
+ 7,356 = 38,889 fresh case JSONs via arms B/C + recoveries (arm A
initial 7,356, then 7,367 of its 7,672-pid recovery queue landed
across 2023/2024/2025 union). Corpus-wide freshness status moves
from "~half of 2025" to "~96% of 2023–2025 + 100% of 2026."

### Parallel-safe queue (zero-HTTP, no WAF share)

These can run **right now** alongside the active `baixar-pecas`
without touching `portal.stf.jus.br`. Ordered by ROI. Interference
model: all four read from local disk / warehouse only; none emit
HTTP to STF or any proxy provider.

1. **`extrair-pecas --provedor pypdf`** — drains the extraction
   backlog. Current cache: 38,232 `.pdf.gz` vs 32,529 `.txt.gz` →
   **~5,703 PDFs with no extracted text yet**, and the active sweep
   is growing the gap as it lands fresh `ok` bytes. pypdf is local
   CPU, single-threaded, ~free; won't contend with the sweep for
   bandwidth. Obvious consumer of what `baixar-pecas` produces.
2. **`atualizar-warehouse`** — full rebuild of
   `data/derived/warehouse/judex.duckdb` from case JSONs + text cache.
   Atomic swap, zero HTTP, a few minutes. Will land arms A/B/C +
   recovery freshness + whatever extraction #1 produces. Build-stats
   validation from this cycle will flag `publicacoes_dje: 0.0% [WARN]`
   (expected — DJe path 1/2 not done) and any other silent regression.
3. **Analysis work on the current warehouse** — Marimo notebooks,
   SQL queries, the `analysis/hc_judge_lawyer_network.py` snapshot
   refresh on whatever warehouse build is current, the unit test
   suite (`uv run pytest tests/unit/`, 568 green). All file-bound.
4. **`validar-gabarito`** — re-run parity check against the 5
   hand-verified cases in `tests/ground_truth/`. Zero HTTP; reads
   the case JSONs on disk. Cheap smoke test that the scraper output
   format hasn't drifted.

**Unsafe while the current sweep runs** (would share the host IP's
WAF counter): a second `baixar-pecas` direct, any `varrer-processos`
direct, `sondar-densidade`. A *proxy-pool* sweep is safe because
egress IPs don't overlap, but it doubles proxy burn for the duration.

### Recently completed (today)

**Peça tipo classification + `pdfs_substantive` view + `--apenas-substantivas` default — 2026-04-23.**
Built a three-tier classification of HC peça PDFs: tier A =
substantive argumentation (keep), tier B = length-gated mixed
(keep if >1500 chars for `DESPACHO`), tier C = procedural boilerplate
(skip). By document count, tier C is **55% of the HC corpus** (132k of
241k andamentos PDFs). Validated with min/median/max sampling per
tipo (both random and length-extreme); calibration bumped the
`MANIFESTAÇÃO DA PGR` length gate 500 → 1000 after finding CIENTE
stamps at 567 chars.

Shipped:
- `judex/sweeps/peca_classification.py`: `TIER_A_DOC_TYPES`,
  `TIER_B_DOC_TYPES`, `TIER_C_DOC_TYPES`, `KNOWN_DOC_TYPES` constants
  + `filter_substantive()` + `summarize_tipos()`. Matching is
  case- and accent-insensitive (NFKD fold + combining-strip +
  uppercase + trim); fail-open on genuinely new tipos.
- `scripts/baixar_pecas.py` + `judex/cli.py`: **`--apenas-substantivas`
  default ON** with `--todos-tipos` opt-out. Filter runs after
  `resolve_targets` before `--limite`, so CSV / range / filter-fallback
  paths all benefit. Sharded mode threads the flag through to children.
  Pre-flight banner prints top-5 tipos and warns on any unseen tipo
  (not in `KNOWN_DOC_TYPES`) so operators catch labeling drift at
  sweep launch.
- `judex/warehouse/builder.py`: `CREATE VIEW pdfs_substantive` added
  to `_SCHEMA_SQL` — unions andamentos + session-virtual documentos,
  tier-labeled, drops tier-C. `MANIFESTAÇÃO DA PGR` length gate
  calibrated 500 → 1000 from expanded sampling.
- `docs/peca-tipo-classification.md`: full tier definitions, per-tipo
  content notes, flag usage, insensitive-match policy, fail-open
  policy, pre-flight banner format, validation sampling log.
- `tests/unit/test_peca_classification.py`: 7 behavior tests
  (drop tier-C, keep unknown, case/accent-insensitive match, fail-open
  on genuinely new tipos, summarize top+unseen, variant-not-flagged,
  high-volume stubs present).

All **575 unit tests green** (568 + 7 new; warehouse tests exercise
the view via `_SCHEMA_SQL`).

**Empirical validation on current corpus:** 17 distinct tipos, zero
case/accent variants, zero silent misses from the insensitive fold
— the insensitive match is pure future-proofing against STF labeling
reforms.

**End-to-end dry-run** on HC 250000–250050 (185 targets):
`--apenas-substantivas` dropped 117 (63%); top tipos:
DECISÃO MONOCRÁTICA (46), INTEIRO TEOR DO ACÓRDÃO (18), DESPACHO (4);
zero unseen tipos flagged.

**Sweep impact** — next `baixar-pecas` run silently drops ~55% of
URLs before HTTP (prints a "dropped N tier-C targets" banner + top
tipos + unseen warning if any). Proportional wall-clock + WAF-exposure
savings. Opt-out with `--todos-tipos` if ever needed.

**HC recovery pass — 2026-04-21 afternoon** (task (a) from prior
next-steps). 7,672-pid union-recovery CSV (arms A/B/C target minus
ok-landed minus deads). 16 shards, interleave-sharded, reused proxy
batch (not refreshed — 8.5h cooldown since arm C). 7,367/7,672
landed (**96.0%**), **1 cliff (shard-k at 174/479)**, 305 pids for
residue. Wall-clock **43.5 min** vs 12-min fresh-pool prediction —
3.6× slowdown traces to L3 residual debt on reused batch. H6 tip #1
"refresh before every sustained sweep" now supported with **inverse
evidence**: skipping refresh cost 3.6× throughput even after 8.5h
idle. Run dir: `runs/active/2026-04-21-hc-recovery/`. H4 cliff
prediction (0–1) held (1 observed). The CliffDetector axis-B
window-full fix explicitly earned its keep — shards l (warn=133)
and p (warn=211) both made it to 100% despite elevated stress; under
the pre-fix detector they would have false-positive-cliffed.

**Arm C — HC 2023 @ 16 shards — completed.** 12,644/12,644 at 100%,
**0 cliffs**, 23.4 min productive wall-clock. Validated the new
default (16/fresh/sticky=5) on a third workload.
`runs/active/2026-04-21-hc-2023/`.

**A/B decision landed (2026-04-21 ~09:16): 16 wins decisively.**
Wall-clock 0.17×, cliffs 3 vs 8, coverage 1.72×. Full writeup:
[`docs/reports/2026-04-21-8-vs-16-shards.md`](reports/2026-04-21-8-vs-16-shards.md).
**16 shards + fresh proxies + sticky=5 is the new default** for
year-backfill workloads; 8 shards retired for sustained jobs.

**Arm B — HC 2024 @ 16 shards — completed.** 92.0% coverage
(13,240/14,387) in 31.5 min productive. 3 cliffs (1 detector
false-positive now fixed + 2 genuine late-stage). Residue folded
into the recovery pass above. `runs/active/2026-04-21-hc-2024/`.

## Backlog — ordered

### DJe capture — three paths (post-diagnosis, 2026-04-21)

STF migrated DJe to `digital.stf.jus.br` on 2022-12-19; our scraper
hits the old (stub-serving) endpoint. See § What just landed for
the full diagnosis. Pick **1** for fast metadata-level repair; pick
**2** when full DJe index is worth the infrastructure cost. Don't
pick **3**.

1. **Andamentos-side DJe metadata extraction** (1–2 hours of work).
   Regex-parse strings like `"ACÓRDÃO PUBLICADO DJE-N DIVULG.
   DD/MM/YYYY PUBLIC. DD/MM/YYYY"` from existing `andamentos` rows.
   Emit a new `dje_events` table in the warehouse: `{processo_id,
   dje_numero, divulgado_iso, publicado_iso, secao}`. Doesn't need
   any new HTTP; works on the corpus we already have. Gets ~80% of
   DJe-metadata-level queries unblocked.
2. **Playwright for `digital.stf.jus.br`** (1–2 days). Headless
   browser loads the new DJe platform, passes the AWS WAF challenge,
   captures the `aws-waf-token` cookie, then reverse-engineered API
   calls with that cookie get full DJe index including decision
   texts. New dependency but only used for the DJe tab, not the main
   scrape. Best long-term.
3. ⛔ **AWS WAF challenge reverse-engineering** — not recommended.
   STF can flip challenge type (reCAPTCHA / Turnstile) anytime;
   maintenance nightmare.

### Warehouse

1. **Rename `pdfs` table → `pecas`.** Holds all peças (PDF + RTF).
2. **`content_version` column on `cases`.** Enable cheap skip of
   content-fresh pids in future year re-scrapes — avoids the need
   for `--full-range` indiscriminate re-scraping.
3. **Decide on `data_protocolo_iso` redundancy** under v8.
4. ✅ **DJe warehouse flatten** — *landed* (this cycle's investigation
   confirmed `_flatten_publicacoes_dje` already exists in
   `builder.py`). The warehouse ingests DJe correctly; the problem is
   that `publicacoes_dje=[]` in the source JSONs due to the extractor
   regression above, not the builder.

### Data recovery

1. ✅ **Arm-A + arm-B + arm-C recovery** — *landed 2026-04-21*.
   Union-recovery CSV approach (targets minus ok minus deads)
   produced 7,672 pids; 16-shard pass at 96.0% / 1 cliff; see
   § In flight § Recently completed.
2. ✅ **Arm C — HC 2023** — *landed 2026-04-21*. 100% / 0 cliffs.
3. **Second-pass recovery for shard-k residue** (305 pids). Tiny
   queue; one shard, direct-IP or single small pool. Low priority —
   those 305 pids are a 0.3% tail across 2023–2025; doesn't
   materially change downstream warehouse/analysis quality. Defer
   unless a specific analysis needs them.
4. **PDFs + text extraction** per year once case-JSON scrapes land.
   Now unblocked — all four years content-fresh enough for peça
   fan-out. See § Next steps (b) / (c).

### Cliff detector hardening (partially done + future)

- **`--cliff-require-sustained K` flag** (still open). Arm A's
  shard-h cliffed on one 70s record after proxy rotation had briefly
  cleared the walls — genuine WAF pattern but the single-sample trip
  lost throughput. K=3 ("regime must be at collapse for K consecutive
  observations") would absorb rotation-forgiveness patterns on
  already-full windows. Distinct from the window-full-gate fix
  (which addressed arm-B's shard-o false positive at small n).
- ✅ **Axis-B window-full gate** — landed this session. Prevents
  false-positive collapse at n=MIN_OBS=20 where p95 ≡ max element.

### Operational hygiene

- **Bytes-cache suffix rename** `<sha1>.pdf.gz` → `<sha1>.bytes.gz`.
  Full playbook in 2026-04-19_2355 archive. Queued; safe now that no
  sweep is live.
- **`baixar-pecas --excluir-mortos`** — minor diff (dead IDs already
  naturally skipped via missing case JSON).
- **Pre-filter `baixar-pecas` by cache-hit** — opt-in helper that
  drops CSV rows whose URLs are all cached.
- **Fix `scripts/monitor_overnight.sh`** — scope stale-shard alerts
  to the currently-active tier.
- ✅ **`peca_targets._find_case_file` no longer walks the tree** —
  *landed 2026-04-21*. Was calling `r.rglob(name)` once per pid, so
  baixar-pecas startup was O(N_pids × N_files) per shard. Production
  layout is `<root>/<CLASSE>/judex-mini_*.json` flat under the
  bucket; replaced rglob with `(root/classe/name).is_file()` plus a
  fallback for callers that pass the classe-bucket directly. +1
  perf-guard test (asserts a buried case file is invisible to the
  direct probe). Stale: the running PDF sweep launched before the fix
  already paid the rglob tax; future invocations cold-start in seconds.
- **`pgrep` self-match gotcha in sweep-wait loops.** A background
  `until [ "$(pgrep -c -f <rotulo>_shard_)" = "0" ]; do sleep … done`
  never exits because the bash waiter's own command line contains
  the literal `<rotulo>_shard_` substring, so `pgrep -f` matches the
  waiter itself. Bit us on the 2026-04-21 recovery (~30 min of false
  "still running" state until manually killed). Correct patterns:
  (i) match the actual script path, e.g.
  `pgrep -f 'scripts/run_sweep\.py.*<rotulo>_shard_'`; or (ii) poll
  each shard's `sweep.state.json` + check for a terminal `done`/
  `collapse` marker; or (iii) use `pgrep -f <pattern> | grep -v $$`
  to exclude the shell running the check. Worth a one-paragraph
  addition to `docs/agent-sweeps.md` § Detached-sweep pattern.

### Request-footprint reduction (re-prioritized — STF-politeness hedge)

**Motivation change as of 2026-04-21.** These items were previously
queued as "scraper optimization" / perf tweaks. After seeing arm-B
land at 10.52 rec/s (×6 URLs per case = ~63 STF HTTP req/sec) and
projecting scale to 32 shards (~125 req/sec), the right framing is
no longer throughput — it's **reducing our observable footprint on
STF's `/processos/*` endpoint** before we decide to scale aggressively.
Each item below cuts 15–20% of HTTP calls per case without losing
data. Stacked, they reduce per-case STF load by 30–50%, which is a
stronger guarantee of STF comfort than any after-the-fact throttle
alarm. **Promoted from "not blocking" to operational priority before
any scale-up past 16 shards.**

1. **Delete `abaDecisoes.asp` fetch** (−1 GET; no downstream reader).
   Highest-ROI: free win, zero data impact.
2. **Class-gate `abaRecursos.asp`** — skip on HC/AI by default; −1 GET
   per case for the classes that dominate our workload.
3. **Audit + gate `abaDeslocamentos.asp`** — check downstream readers
   before cutting; probably gateable by class.
4. **Class-gate `abaPautas` / `abaPeticoes`** on monocratic classes
   (HC decisions often monocratic → pautas empty → skip safe).

**Companion observability (V1 only, to measure the impact of the
cuts above + catch STF gradual-throttle):** add a `clean_p50` column
to `judex probe` — rolling p50 of `wall_s` filtered to
`status=ok AND retries={}`. That's the pure STF-response-time
signal, isolated from our own retry-chain latency. No thresholds,
no alarms yet — just the number, visible. After arm B + arm C give
us 2–3 data points for the "normal" range, we decide whether to
add V2 (color-coded ratio) or V3 (auto-throttle). V1 is ~20 lines
of code; V3 is a design session.

**Not doing (out of scope):** a proxy-provider change, a UA-
identification scheme, or coordinated outreach to STF. Those are
policy moves, not technical ones; queue separately if ever needed.

### Refactoring sweep — 2026-04-26 (queued)

Read-only review surfaced a punch list. Items are grouped **quick
wins** (≤30 min, low risk, do first), **structural** (file splits +
DRY-up, medium risk, do after the in-flight regime change lands),
and **architectural** (questions to settle, not edits to schedule).
The single biggest leverage move is collapsing `cli.py`; the single
biggest *risk* avoided by ordering is leaving the in-flight
`RegimeReading` change alone until the structural items start.

Each item carries `file:line` refs so a cold session can land it
without re-deriving the diagnosis.

**Quick wins**

1. ✅ **Drop unused import** `tempfile` from `judex/cli.py:34` —
   *landed 2026-04-26.* (`sys` *is* used at `cli.py:953-958, 1012-1017`
   for the `sys.argv` save-and-restore around script dispatch — the
   original review was wrong; verified before editing.)
2. ✅ **Extract atomic-write helper** — *landed 2026-04-26.* New
   module `judex/utils/atomic_write.py` (`atomic_write_text(path, text,
   *, fsync=False)`) replaces the inlined `tmp + os.replace` blocks at
   `judex/sweeps/store.py:127,136`, `judex/reports/state.py:49`, and
   `judex/reports/watchlist.py:59`. Bonus: store.py temp-file naming
   changed from a fixed `.tmp` to `.tmp.<pid>`, eliminating a
   theoretical collision when two sweep processes touch the same path.
   +5 unit tests in `tests/unit/test_atomic_write.py`; full suite went
   from 598 → 603 green.
3. **`test_build_warehouse.py:44-100`** — seven `_v{1,3,6,8}_case`
   builders are vestigial post-renormalizer. Replace with a single
   `make_case(version="v8", **overrides)` factory; legacy versions
   are tested implicitly through fixture overrides.

**Structural**

4. **`process_store.py` ↔ `peca_store.py` duplication.** Both grow the
   same regime quartet in the in-flight diff (`process_store.py:43-51`,
   `peca_store.py:43-52`). Move the regime-stamping helper into
   `store.py`'s base; subclasses supply only the dataclass + key
   function. **Land *after* the in-flight diff is committed** so the
   refactor reads against the final shape.
5. **`download_driver.py` (427) ↔ `extract_driver.py` (334) parallelism.**
   Init / signal handlers / target loop / skip-or-resume / progress
   reporting are essentially the same; only `process_item` differs.
   Extract `BaseSweepDriver` in `judex/sweeps/driver_base.py`. Saves
   ~150 lines + ensures regime stamping doesn't fork between the two
   when extract_driver later needs it.
6. **`judex/warehouse/builder.py` (1030 lines)** — the `_flush()`
   nested inside `build()` (`builder.py:895-954`) is screaming for a
   `BufferSet` dataclass with a `flush(con)` method. Lifts the
   `flatten_*` functions into testable units and brings the file
   under the 600-line ceiling.
7. **`scripts/run_sweep.py` (1049 lines)** — `_run_passes` (line 842)
   is the loop; everything else is argparse + reporting. Extract a
   `judex/sweeps/process_sweep_runner.py` module that owns the loop
   and state; `run_sweep.py` becomes ~200 lines of argparse +
   orchestration.
8. **`judex/scraping/scraper.py` (711 lines)** violates the CLAUDE.md
   600-line rule that's literally written down. Either split (HTTP
   session + tab orchestration vs. caching vs. extraction-glue) or
   strike the rule from CLAUDE.md and pin a real ceiling with a
   pre-commit check.

**Architectural — decide, don't schedule**

9. **`judex/cli.py` (965 lines) — Typer wrapping argparse is double
   parsing.** Every command in `cli.py:163-666` rebuilds `argv` via
   `_push()` (`cli.py:65-79`) and shells into the script's `main()`.
   Two CLI frameworks, one user-facing surface. Decision needed:
   (a) Typer wins → make script `main()` bodies pure functions, drop
   argparse, kill `_push`; (b) argparse wins → drop Typer, write
   argparse `--help` strings. Status quo is paying ~900 lines for
   nice help text. **Pick one before the next CLI command lands.**
10. **In-flight `RegimeReading` shape — four columns or one nested
    dict?** Diff adds `regime` + `regime_fail_rate` + `regime_p95_wall_s`
    + `regime_promoted_by` to *both* `AttemptRecord` and
    `PecaAttemptRecord` (8 dataclass fields, 2× docstrings). A single
    `regime: dict | None` carries the same data; jq becomes
    `.regime.label` instead of `.regime`. **Decide before merging the
    in-flight branch** — flattening four columns back into a dict
    later is a corpus-wide migration; the reverse is one diff.
11. **Three monitoring tools without a shared seam** — `AdaptiveThrottle`,
    `CircuitBreaker`, `CliffDetector` (`shared.py:65-216`) each maintain
    independent rolling windows over the same attempt stream. The
    architecture is sound — they answer different questions — but
    they don't share a window or a record-stamping path. Not urgent;
    flag this as "the place over-engineering will compound first" so
    the next monitor added doesn't blindly add a fourth window.
12. **Portuguese subcommands → English scripts.** `varrer-processos`
    → `scripts/run_sweep.py`, `baixar-pecas` → `scripts/baixar_pecas.py`,
    `extrair-pecas` → `scripts/extrair_pecas.py`. Pick a language;
    the translation friction shows up every time someone goes from
    `--help` to source.

**Symptoms-of, not work items**

- `_push()` in `cli.py:65-79` exists *only* because of #9. It dies
  when #9 is decided either way.
- `_reset_shutdown_for_tests()` at `shared.py:59` is a test seam in
  production code; a `monkeypatch` in conftest does the job.
- `_REGIME_BANDS` table refactor in the in-flight `shared.py:96-101`
  diff replaces a 6-line `if/elif` ladder with a 3-row table iterated
  by a loop. Earns its keep only if more bands appear; if not, it's
  more code, not less. Re-evaluate when the band count next changes.

## Known limitations

- **Stale-cache content residue.** 2024 + 2023 + ~half of 2025
  structurally v8 but content-stale (partes truncated, pautas empty,
  no `publicacoes_dje`). 2026 is content-fresh; 53.5% of 2025
  (arm-A coverage) now content-fresh.
- **Main `judex.duckdb` pre-session data.** Rebuild deferred to
  end-of-cycle (after arms B, C, and all PDF + extraction land).
- **Scrapegw L3-per-IP reputation decay.** Arm A gave direct
  evidence: pools that cliffed yesterday cliff earlier today after
  21h idle. Overnight gap is "mostly but not fully" cleared. A
  second proxy provider is the only true redundancy.

## Known gaps

- **`publicacoes_dje` → warehouse** (see Backlog § Warehouse #1).
- **PDF enrichment status tracking** — no persisted field answers
  "has this case been through PDF enrichment?" Derivable from
  `extractor` slots; rollup script proposed but not landed.

---

# Reference — how to run things

```bash
# Unit tests (~15 s, 538 tests)
uv run pytest tests/unit/

# Live probe of a sharded sweep (rich table, throughput, ETA, regimes)
uv run judex probe --out-root runs/active/<dir>
uv run judex probe --out-root runs/active/<dir> --watch 30   # auto-refresh

# Ground-truth validation
uv run python scripts/validate_ground_truth.py

# Full-range year re-scrape (what arms A/B/C use)
uv run python scripts/generate_hc_year_gap_csv.py \
    --year <YYYY> --out tests/sweep/hc_<YYYY>_full.csv \
    --dead-ids data/derived/dead-ids/HC.txt --full-range

#   Then launch sharded:
uv run judex varrer-processos --csv tests/sweep/hc_<YYYY>_full.csv \
    --rotulo hc_<YYYY> --saida runs/active/<date>-hc-<YYYY> \
    --diretorio-itens data/source/processos/HC \
    --shards <N> --proxy-pool config/proxies --retomar

#   Aggregate dead-IDs periodically
uv run python scripts/aggregate_dead_ids.py --classe HC

#   PDF bytes (separate WAF counter, 16 shards safe)
uv run judex baixar-pecas --csv <case-list> \
    --saida runs/active/<date>-hc-<YYYY>-pdfs \
    --shards 16 --proxy-pool config/proxies --retomar --nao-perguntar

#   PDF text extraction (zero HTTP; local)
uv run judex extrair-pecas -c HC -i <lo> -f <hi> --nao-perguntar

#   Warehouse rebuild
uv run judex atualizar-warehouse --ano <year> --classe HC \
    --saida data/derived/warehouse/judex-<year>.duckdb
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

Unchanged. See prior archive for the three-hop layout
(case JSON → URL → sha1 → cache quartet).
