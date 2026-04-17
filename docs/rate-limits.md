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

## Validated defaults (commit `2a2833d`)

From the D-runs above, combined with the E validation (429/429 ok, 0
errors at these defaults — `docs/sweep-results/2026-04-16-E-full-1k-defaults/`):

- `ScraperConfig.retry_403: True`
- `ScraperConfig.driver_max_retries: 20` (was 10)
- `ScraperConfig.driver_backoff_max: 60` (was 30)
- `run_sweep.py --throttle-sleep`: `2.0` seconds per process (was 0)
- `run_sweep.py --no-retry-403`: flag renamed to opt-out

Measured pace at these defaults: **3.60 s/process** end-to-end.
Projection for 1000 processes: ~60 minutes (vs Selenium's 77.6 min on
the same range — HTTP ~22% faster end-to-end once WAF stalls are
included).

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
