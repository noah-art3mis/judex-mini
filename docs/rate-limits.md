# Rate limits — how STF's WAF gates the scraper, and how we cope

STF's portal is gated by a WAF (AWS WAF, fronted by ALB) that
enforces a rate-and-behavior rule on `/processos/*`. This doc
describes the rule as we've measured it, the sweep posture that
works around it, and the unresolved policy question about
`robots.txt`.

See also:
- [`docs/stf-portal.md`](stf-portal.md) — portal contract (URLs, auth triad).
- [`docs/process-space.md`](process-space.md) — class sizes; wall-time math uses the defaults here.
- [`docs/data-layout.md`](data-layout.md) — sweep artifact layout.

## What the WAF does

- **Returns HTTP 403, not 429.** Standard rate-limit codes don't apply; `abaX.asp` 403s also look identical whether they're auth-triad failures (permanent) or WAF blocks (transient). The retry logic must distinguish by context (see `src/scraping/scraper._http_get_with_retry`).
- **Blocks are session-agnostic.** New session cookies don't clear a block. The limit is per-IP behavior, not per-session.
- **Blocks lift within minutes.** Empirically 1–5 minutes; the reactive-retry loop (`cfg.retry_403=True`) rides this out transparently with tenacity backoff.
- **Non-browser User-Agents are permanently blocked.** `curl/*`, anything with "bot" or "python". Our default Chrome UA is fine.
- **The two hostnames have independent counters.** `portal.stf.jus.br` (case pages) and `sistemas.stf.jus.br` (PDFs, repgeral JSON) throttle separately. Interleaving PDF fetches between tab fetches spreads load across both.

## Empirical threshold

Three 200-process ADI sweeps (commit `c101310`, full analysis at
`docs/sweep-results/2026-04-16-D-rate-budget.md`):

| Run | Pacing  | Retry-403 | ok/200 | First block   | Stall duration      | Wall   |
|-----|--------:|:---------:|-------:|---------------|--------------------:|-------:|
| R1  | 0       | ✓         | 199    | process 121   | 4.5 min             | 7.3 min |
| R2  | 0.5 s   | ✗         | 30     | process 31 (hot start) | n/a        | 2.1 min |
| R3  | 2.0 s   | ✗         | 175    | process 106   | 1.0 min (resumed)   | 9.8 min |

Headline findings:

- **Block threshold ≈ 100–120 processes at any pacing tested.** Pacing doesn't *prevent* blocks; it just shortens them (4.5 min at zero sleep → ~1 min at 2 s).
- **Reactive retry beats proactive pacing alone.** R1's 199/200 vs R3's 175/200.
- **Warm-start measurements are meaningless.** R2 ran immediately after R1 and inherited a hot WAF counter; its 30/200 result doesn't tell us about 0.5 s pacing on a fresh IP.

Earlier evidence (sweep C, `docs/sweep-results/2026-04-16-C-full-1000.md`)
tripped the block at process 108. R1 tripped at 121. The threshold is
**not constant** — it drifts with whatever internal signals the WAF
tracks.

## Two-layer model (sweep V, 2026-04-17)

The "threshold drifts" note above is a description; the mechanism is
(we now think) **two independent WAF layers stacked**:

1. **Per-request throttle** — fast-decaying window counter. Fills with
   each GET to `/processos/*`, decays on a scale of tens of seconds to
   a few minutes. Triggers individual 403 blocks. This is what
   `--throttle-sleep` and `--retry-403` tensions.
2. **Per-IP reputation counter** — slow-decaying. Accumulates across
   requests (and across sweeps on the same IP). Does **not** trigger
   blocks directly; instead it **lowers the threshold** of layer 1.
   Drains on a scale of tens of minutes. This is what pacing within a
   single sweep cannot fix.

### Evidence — sweep V gap sequence

Sweep V (HC 118201..119200, paper era) hit 15 WAF cycles in 638 processes
before SIGTERM. Gap (Δ HCs between consecutive 403 cycles):

```
cycle  1  2  3  4   5  6   7  8  9 10 11 12 13 14 15
gap   62 68 62 52  16 72  60 83 31 30 29 18 40 15
```

Three regimes visible:

- **Cycles 1–5: stable ~60 gap.** Layer 1 is the only active
  constraint; layer 2 hasn't accumulated past its threshold.
- **Cycle 6: transient dip (gap=16).** Backoff from cycle 5 (64 s)
  barely drained the layer-1 window, so cycle 6 fires near-immediately.
  This is the signature — **backoff pauses the client but doesn't
  forgive the accumulated count.**
- **Cycles 8–15: monotonic decay (83 → 15).** Layer 2 has crossed its
  threshold, so layer 1's effective size shrinks every cycle. The WAF
  is no longer telling you to slow down — it's telling you to leave.

### The 32-retry outlier as adaptive-block signature

HC 118593 (cycle 8) absorbed **403×32 retries** over 185 s. Tenacity's
exponential backoff capped at its max wait and kept re-hitting the same
wall. This is the WAF **extending the block duration in response to
retrying**. Polite clients recover in 60–120 s; noisy clients get
stretched to 180 s+. Net effect: retry budget has an adaptive floor,
not just a max count.

### Comparative cycle rates across the same session

| sweep | year | rpm cycles per 100 procs | notes |
|-------|-----:|-------------------------:|-------|
| T | 2015 | 0.2 | fresh-ish WAF state |
| U | 2014 | 0.3 | second paper-era sweep, same session |
| V | 2013 | **2.4** | third paper-era sweep, same session |

V's cycle rate is ~**10× T's** at identical pacing defaults. Layer 1
didn't change between sweeps; layer 2 did.

### Operational implications

- **Cooldown between sweeps, not tighter throttle.** Non-WAF per-process
  time in V was still 1.0 s (unchanged from T's healthy baseline). The
  pacing was never the problem; the reputation counter was. Waiting
  30+ min with no STF requests drains layer 2; tightening
  `--throttle-sleep` from 2 s to 5 s does not.
- **Resume behavior.** Resuming V right after SIGTERM puts you at the
  last gap (15 HCs); waiting 30+ min should reopen gaps to ~60
  initially before shrinking again.
- **Stacking sweeps in one session is non-linear.** T → U → V's
  0.2 → 0.3 → 2.4 cycles/100 escalation argues against a 4th paper-era
  sweep on the same IP in the same session. Schedule paper-era sweeps
  with multi-hour gaps between them.
- **Circuit breaker blind spot.** `src/sweeps/shared.py` trips on
  `status=error`, but tenacity-absorbed 403s keep `status=ok` regardless
  of how long they took. V's degradation would have been caught by a
  secondary breaker on "median `wall_s` of recent N processes > X" —
  a concrete follow-up beyond the existing structural-canary task.
- **Docs/posture framing still holds.** The "behavioral threshold" in
  § *What the WAF does* is what layer 2 is. This section just
  describes the mechanism with empirical data, not a new posture.

### Estimated timing parameters

Rough numbers inferred from sweep V's gap sequence (15 cycles over
40.6 min wall) plus cross-references to sweeps C/D/E/T/U:

**Layer 1 — per-request throttle**

| parameter | estimate | derivation |
|---|---|---|
| Bucket / window size | ~80–100 requests per rolling 5-min window | Sweep E (429/429 ok at 3.6 s/proc = ~83 req/5min); sweep C/R1 tripped at proc 108/121 in a warm bucket |
| Refill timescale | ~1 min to drain from full → usable | Tenacity-absorbed block durations were 60–120 s for most cycles |
| Block duration on trigger | 60–185 s (polite) → 180 s+ (noisy, adaptive) | V cycle 8 hit 403×32 = 185 s because tenacity kept re-firing |
| What drains it | Pure wall-clock time with no requests | Throttle-sleep between requests does **not** help once in a block |

**Layer 2 — per-IP reputation**

| parameter | estimate | derivation |
|---|---|---|
| Fill time from cold | ~20–25 min of sustained *blocked* scraping | V cycles 1–5 spanned HC 118201..118461 = ~23 min before gaps started shrinking |
| Steady-state engagement | after ~5 layer-1 cycles in one session | T: 0.2 cycles/100, U: 0.3, V: 2.4 — jump between U and V is the layer-2 crossover |
| Drain time, partial (gap→60) | ~30 min of no STF requests | not directly measured yet; is a floor; next resume of V is the test case |
| Drain time, full (back to T's rate) | ~2–4 h conservatively; overnight certainly | inferred from the T/U/V escalation curve + the fact that sweeps Z and T (hours apart) both started at ~0.2 cycles/100 |

### Cooldown recommendations (what to pass for `--throttle-sleep` is *not* the answer)

Pacing tightening won't help once layer 2 engages — the gating factor
is wall-clock time since last request, not request spacing. Concrete
wait budgets to pass through as session-level planning:

| situation | wait before next sweep | rationale |
|---|---|---|
| After a clean sweep (0–3 WAF cycles, like T/U) | **15–20 min** | Let layer 2 drain below threshold before the next 1000-HC run. |
| After a WAF-heavy sweep (V-style, ≥5 cycles in <1 h) | **60–90 min** | Layer 2 was sustained at engagement; needs real drain. |
| After SIGTERM'd sweep (want to `--resume`) | **≥30 min** | Floor; resume sooner and expect the last observed gap (~15 HCs) to repeat within the first cycle. |
| Back-to-back paper-era sweeps same session | **avoid** (prefer multi-hour gap, ideally overnight) | T→U→V showed 10× escalation; a 4th in the same session is over the patience threshold. |
| Paper-era after modern-era same session | **30–45 min** | Paper-era HCs are heavier per process (PDFs + retries on rotated-watermark docs), so the layer-1 cost per request is higher. |
| Full cold reset | **overnight / ~8 h** | Sweeps Z and T, hours apart, both behaved like fresh IPs. This is the only interval we've *measured* as fully cold. |

These numbers are estimates from a single observational session; they
should get tightened the next time anyone has an opportunity to
measure drain explicitly (e.g. resume V after exactly 30 min and
compare first-cycle gap to the prior 15).

### Mitigation proposals

The two-layer model changes what "fixing" the WAF problem means.
Layer 1 is already tolerable (retry-403 absorbs it transparently).
Layer 2 is the structural limit — it's what makes a 9-day full HC
backfill a 9-day wall-clock commitment from a single IP.

**In rough order of operational cost:**

1. **Respect the drain, schedule around it** (no code changes).
   Use the cooldown table above and treat each paper-era sweep as a
   ~60–90 min cooldown afterward. Adds ~1 h per sweep but keeps all
   WAF interactions polite on a single IP. **Net effect on a 9-day
   backfill: negligible** — the wall-clock is already dominated by
   layer 1 recovery, not sweep execution.

2. **IP rotation via residential / datacenter proxy pool** (tens of
   lines of glue + paid proxy service).
   - A different IP presents as a cold WAF state — both layers are
     per-IP. 2–4 IPs round-robining sweeps reduces effective layer-2
     pressure linearly.
   - Integration point: `src/scraping/http_session.new_session()`.
     Add a `--proxy` flag to `run_sweep.py` that passes
     `proxies={"https": "http://user:pass@host:port"}` into the
     session, and an env-var-based pool if we want rotation.
   - Residential proxies (~$10–30 per GB, per-request pricing at some
     providers) is the closest to "behave like a normal user". Datacenter
     proxies are cheaper but STF's WAF may classify them differently.
   - **Ethics note**: moving around STF's `/processos/*` `robots.txt`
     disallow via IP rotation is a posture change, not just a
     mechanics one. See § *The unresolved policy question* — IP
     rotation answers *how*, not *whether*.

3. **Tor / free proxy lists** (cheap but brittle).
   - Tor exits are frequently WAF-blocked at the datacenter classifier
     level, and public proxy lists rot within hours. Not recommended
     except as a one-off probe.

4. **Distributed scraping across multiple machines** (days of setup).
   - Ship the CSV + per-process-key sharding to N workers on N
     different IPs. Each worker inherits its own layer-1/layer-2
     state. Coordination via shared `sweep.state.json` (file-locking
     or a small SQLite). Cuts backfill wall-time by ~N (minus
     coordination overhead).
   - This is what a production-grade version would do, but is overkill
     for the current research scope — `judex-mini` is one-person
     research, not a service.

5. **Ship as parser library, end users run their own scraping** (architecture change).
   - Removes our IP from the equation entirely. Mentioned in
     § *The unresolved policy question* posture 3. Cleanest answer to
     the layer-2 problem because it makes layer-2 not our problem.

6. **STF partnership / Ouvidoria** (months of process).
   - Posture 2 in the policy question. If granted, whitelisted access
     bypasses the WAF entirely. Biggest upside, longest lead time.

### Recommended short-term path

Given the research scope — **a few more 1000-HC sweeps, not a full
216k backfill** — options 1 + 2 are the practical sweet spot:

- **Option 1 (cooldowns) alone** suffices for the immediate queue (W,
  resume V, maybe X/Y/densification sweeps) if we spread them across
  a few days.
- **Option 2 (proxy rotation)** is worth the setup cost if the
  research question grows to need the full backfill, or if we want to
  shorten the remaining Track 1 queue from ~2 weeks (with cooldowns)
  to a few days.
- **Option 5 (library-only distribution)** is the honest answer for
  *anyone downstream* of this project — it's a posture decision the
  current research author hasn't made yet but should before any
  public release.

Not recommended: tightening `--throttle-sleep` further. The V data
shows throttle doesn't drain layer 2, so the only pacing knob we have
controls layer 1, which retry-403 already handles.

## Wall taxonomy and severity timeline

Synthesising the evidence above: the WAF is not one wall but a stack
of them on different time scales. Knowing which one is firing is more
useful than any single knob — each wall wants a different response.

### The walls

| wall                              | layer  | what triggers it                           | scale                                             | recoverable by                                               |
|-----------------------------------|--------|--------------------------------------------|---------------------------------------------------|--------------------------------------------------------------|
| **L1: per-request throttle**      | WAF    | sliding ~80–100 req / 5-min window per IP  | ~6 min from cold → first 403 at 3.6 s/proc        | `retry-403` (tenacity 60–120 s, absorbed transparently)      |
| **L2: per-IP reputation**         | WAF    | cumulative L1 cycles across a session      | ~25 min of scraping, or ~5 L1 cycles              | wall-clock idle only (≥30 min partial, overnight full)       |
| **L2+: adaptive block extension** | WAF    | retrying while in a block                  | ~45 min of a hot session (V's cycle 8 = 403×32)   | stop retrying; still need L2 idle                            |
| **Cross-sweep reputation**        | WAF    | stacking sweeps same IP same day           | T→U→V showed 0.2→0.3→2.4 cycles/100 (10×)         | multi-hour or overnight gap between sweeps                   |
| **Retry budget exhaustion**       | client | one request gets max_retries+1 retries     | irreducible — single-process failure              | raise `driver_max_retries`, but D-era R1 hit it at 10        |
| **PDF extraction cost**           | client | Unstructured `hi_res` OCR                  | ~18 s/doc steady-state; 300 s API timeouts rare   | throw money at it, or skip OCR                               |
| **Per-host counter split**        | WAF    | `portal` + `sistemas` counters independent | *not* additive — separate buckets                 | architectural gift, already used                             |
| **Wall-clock at scale**           | math   | 273 k HCs × 3.6 s/proc                     | ~9 days best case single IP                       | proxy rotation or distributed workers                        |
| **`robots.txt` policy wall**      | human  | STF disallows `/processos/*`               | unbounded — posture question                      | `NOTICE.md` + identify UA, or library-only distribution      |

### Timeline to the severe wall on a single IP

From sweep V's gap sequence (the only sweep characterised past the
L2 crossover — see § *Two-layer model*):

```
0 min    Cold start — healthy ~1 s/proc, no WAF signal
6 min    First L1 block fires (process ~100–120)
         → retry-403 absorbs it, ~1 min stall
12 min   Cycle 2 — gap ~60 processes, same shape
18 min   Cycle 3 — still ~60 gap, stable
25 min   ~~~ L2 CROSSOVER ~~~
         Cycles 1–5 complete; layer 2 crosses threshold.
         Gaps start shrinking: 52 → 16 → 72
30 min   Cycle 6 — transient dip (gap=16) — backoff paused you
         but didn't forgive the accumulated count. First visible sign.
40 min   Cycle 8 — 403×32 in a single process (185 s stall).
         ADAPTIVE BLOCK: the WAF is extending duration because
         you kept retrying. Polite retries now hit the wall.
55 min   Monotonic decay: gaps now 31 → 30 → 29 → 18 → 40 → 15.
         WAF has stopped saying "slow down" — it's saying "leave".
60 min   Severe wall reached; every ~15 HCs trips a new cycle.
```

### Operating regimes (first-pass failure rate)

| fail %   | regime                     | implication                                                   |
|---------:|----------------------------|---------------------------------------------------------------|
| 0–5 %    | **under-utilising**        | wastefully polite; WAF budget has slack                       |
| 5–10 %   | **healthy (T/U-style)**    | steady scraping, L1 absorbed, L2 not engaged                  |
| 10–20 %  | **L2-engaged equilibrium** | Pareto frontier — as fast as WAF tolerates pre-adaptive       |
| 20–30 %  | **approaching collapse**   | adaptive block firing; retry budget at risk                   |
| > 30 %   | **V-style collapse**       | gaps < 15 HCs between cycles; stop and cool down              |

### The two CliffDetector axes

CliffDetector decides the regime above from two independent
measurements on a rolling window of recent records — not just the
fail-rate column shown in the table.

- **Axis A — fail rate, WAF-shape-filtered.** A `status:fail`
  record counts toward this axis only if one of:
  `wall_s > 15 s`, `http_status ∈ {403, 429, 5xx}`, or `retries`
  non-empty. Fast `NoIncidente` fails from sparse corpora
  (unallocated HC numbers that STF has no record of) do *not*
  count — they're a data-shape signal, not a WAF signal. This
  filter is what lets a sweep traverse a 100 %-fail dead zone and
  still correctly report `under_utilising`.
- **Axis B — p95 `wall_s`, unfiltered.** Every record in the
  window contributes, success or fail. Catches the adaptive-block
  signature (§ *The 32-retry outlier as adaptive-block signature*):
  tenacity absorbs the 403, stamps `status=ok`, but the 100 s+
  `wall_s` still shows up here.

**Regime is the worse of the two axes.** `l2_engaged` can trip
from axis A crossing its threshold *or* from axis B's p95 crossing
its threshold — whichever hits first. A dead-zone sweep sits at
axis A = 0 % (all fails filtered out), axis B ≈ 1 s (fast NoIncidente
returns), both happy. A V-style collapse trips axis A first; an
adaptive-block-heavy session trips axis B first.

When diagnosing a regime transition: read `sweep.log.jsonl` for both
the filtered fail-rate and the raw p95 `wall_s` — don't assume the
fail column alone explains the state.

The `--resume`-per-record architecture turns L2-engaged operation
from a crisis into deferred work — 15 % first-pass fails means ~85 %
lands on the first attempt and the remainder clears on a
post-cooldown `--retry-from`. This is the core design decision that
makes single-IP multi-day sweeps feasible at all.

### Which wall do I hit first?

- **Sweeps ≤ 100 processes: none.** L1 doesn't fire until process
  ~100–120. Nothing to tune.
- **Sweeps 100 < N ≤ 1 000 at validated defaults: L1 only.**
  Retry-403 absorbs it; expect 1–3 WAF cycles, ~10 % tail of fails,
  fully recovered on first `--resume`.
- **Sweeps > 1 000 or stacked same-session: L2 crossover at ~25 min
  wall-clock**, severe wall at ~45–60 min. Throttle tuning is
  useless here; only IP change or wall-clock cooldown helps.
- **Full-backfill scale (273 k HCs single IP): wall-clock at scale +
  `robots.txt` posture** become the binding walls, not L1/L2. No
  code knob addresses either — see § *Mitigation proposals*.

## Validated defaults (commit `2a2833d`)

From the D-runs above, combined with the E validation (429/429 ok, 0
errors at these defaults — `docs/sweep-results/2026-04-16-E-full-1k-defaults/`):

- `ScraperConfig.retry_403: True`
- `ScraperConfig.driver_max_retries: 20` (was 10)
- `ScraperConfig.driver_backoff_max: 60` (was 30)
- `run_sweep.py --no-retry-403`: flag renamed to opt-out

**`--throttle-sleep` was removed** from `run_sweep.py` on 2026-04-17.
The two-layer model (above) showed proactive process-level pacing
doesn't drain the per-IP reputation counter, and the D-run data
showed retry-403 alone (R1: 199/200 at zero sleep) dominates pacing
alone (R3: 175/200 at 2 s). `--proxy-pool` rotation addresses the
binding layer-2 constraint directly; adding a throttle on top of
rotation only sacrifices throughput without reducing WAF pressure.
The parameter is retained in `iterate_with_guards()` for the PDF
sweep (`scripts/fetch_pdfs.py`), where the empty-body retry rate on
`sistemas.stf.jus.br` does respond to pacing — different signal,
different host, different defaults.

Measured pace at the (pre-removal) defaults: **3.60 s/process** end-to-end.
Without `--throttle-sleep`, expected pace is ~1.6 s/process when WAF
is cold, with per-cycle stalls absorbed by retry-403. 1000-process
wall time projection now depends primarily on WAF cycle count; see
§ *Wall taxonomy and severity timeline* for the regime-indexed view.

## PDF-sweep datapoints (distinct from process sweeps)

Process sweeps (above) hit `portal.stf.jus.br`'s case-page counter.
PDF sweeps (`scripts/fetch_pdfs.py` + `scripts/reextract_unstructured.py`)
hit `portal.stf.jus.br/processos/downloadPeca.asp` + the
`sistemas.stf.jus.br` PDF origin — related but separate counters.

Narrow PDF-sweep run from
[`docs/pdf-sweeps/2026-04-17-top-volume-ocr/SUMMARY.md`][tv] (25 URLs
+ 19 OCR re-extracts + 6 retries over ~16 min):

- **Transient empty-body rate ~28 %** on first pass at
  `--throttle-sleep 3.0` — returns HTTP 200 with an empty / non-%PDF
  body, logged as `unknown_type`. All recovered on retry; at
  `--throttle-sleep 5.0` the rate drops to ~15 %.
- **Session reuse sensitivity.** 3 URLs failed repeatedly under a
  driver-owned single session even at 6 s throttle; all recovered
  immediately on **fresh-per-URL** sessions. Hypothesis: the WAF
  tags the session after cumulative requests. Mitigation: rotate
  `new_session()` every ~20–30 requests, or discard the session on
  `unknown_type` and retry.
- **Hard 403 burst-block** at ~50 cumulative requests over
  ~15 minutes — the standard WAF behavior above, same cooldown (minutes).
- **OCR wall cost.** Unstructured `hi_res` at ~18 s/doc steady-state
  (see [`performance.md § OCR pass`][perf]); one outlier API read
  timeout (300 s) in 19 docs.

[tv]: pdf-sweeps/2026-04-17-top-volume-ocr/SUMMARY.md
[perf]: performance.md#ocr-pass-unstructured-hi_res

## Retry semantics

`src/scraping/scraper._http_get_with_retry` wraps every GET in tenacity:

- 429 / 5xx / connection errors → always retriable.
- 4xx non-429 → fail fast (unless 403 + `cfg.retry_403=True`).
- 403 + `cfg.retry_403=True` → retriable; tenacity backoff rides out the WAF block cycle.
- Budget: `driver_max_retries` attempts, exponential backoff capped at `driver_backoff_max` seconds.

The circuit breaker (`src/sweeps/shared.CircuitBreaker`) is an orthogonal
outer layer — it aborts the *sweep* if error rate crosses a threshold
in a rolling window. Retry-403 handles individual-request resilience;
the breaker handles pathological runaway.

## What pacing does NOT fix

- **PDF extraction cost.** `pypdf.PdfReader.extract_text` and the Unstructured OCR path run at local-CPU / external-API speed; pacing the portal doesn't change them.
- **Individual request latency.** The portal is what it is (~300–650 ms per tab). Pacing sits above that.
- **Courtesy vs. just-faster-failure.** Faster scraping without proper caching is the same load concentrated in time. The HTML fragment cache (`data/html/<CLASSE>_<N>/*.html.gz`) is the primary lever for being a good citizen.

## The unresolved policy question — `robots.txt`

STF's `/processos/*` is **disallowed in `robots.txt` for all user
agents.** The WAF enforcement is the technical version of the same
rule. This is a posture question, not a mechanics question — the
retry / pacing / resume machinery is sufficient to complete sweeps
of any size. The open question is whether we *should*, and under
what terms.

Three postures on the table:

1. **Minimum professional floor.** Custom `User-Agent` identifying the project with a contact email, `NOTICE.md` explaining LAI (Lei de Acesso à Informação) basis + LGPD obligations, keep scraping with adaptive pacing. Low friction, visible to STF if they want to contact us.
2. **Talk to STF first.** Ouvidoria route — Brazilian courts sometimes grant whitelisted access for research. Slow but safest.
3. **Cache-first distribution.** Ship judex-mini as a parser library rather than a running scraper. End users populate `data/` themselves from their own IPs; no single IP ever sweeps at scale.

Unresolved. **Doesn't block sweep mechanics** (`--retry-403` +
`--throttle-sleep` + `--retry-from` absorb the WAF transparently), only
the posture decision. Whichever path is chosen, it should be documented
in a `NOTICE.md` at the repo root before a large backfill runs.

## Wall-time math at scale

Back-of-envelope budget at the validated defaults (3.6 s/process
measured on ADIs; HCs slightly heavier, assume ~3.6 s too):

| Run size       | Wall time        |
|---------------:|-----------------:|
| 100            | ~6 min           |
| 1 000          | ~60 min          |
| 10 000         | ~10 h            |
| 100 000        | ~100 h (~4 days) |
| 216 000 (full HC backfill — see `process-space.md`) | ~215 h (~9 days) |

These assume the WAF stays tolerant at 2 s pacing + retry-403. We've
validated 1000 (sweep E) and partial 429 of that. **We have not
validated 10k or above.** The block threshold drifted between sweep C
and D1; a multi-day run may hit escalating thresholds we haven't
measured.

Practical implication: runs above ~10k should be chunked with a
cool-down window between chunks, or split across IPs by shipping the
cache-first distribution path (posture 3 above).
