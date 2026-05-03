# HTTP vs Selenium benchmark (pre-Selenium-retirement, 2026-04-17)

Empirical wall-clock comparison of the HTTP and Selenium backends on
the same fixture (AI 772309), measured by
`scripts/bench_http_vs_selenium.py`. Captured *before* the Selenium
backend was frozen on 2026-04-17 and `--backend selenium` made to
error out (see CLAUDE.md). Promoted from the original
`docs/performance.md` so the survivor doc could be reframed around the
WAF ceiling rather than a backend that no longer exists.

The numbers below are why HTTP became the only first-class backend.
Don't re-run on the current codebase — the Selenium path is
retired; numbers can't be reproduced. Read this as historical record.

## Measured: HTTP vs Selenium (AI 772309, cold)

From `scripts/bench_http_vs_selenium.py`:

| Path                          | Wall clock | Notes                                      |
|-------------------------------|-----------:|--------------------------------------------|
| Selenium (from `main.py`)     | 18.00 s    | includes ~13 s one-time driver startup     |
| Selenium steady-state         |  4.98 s    | `ProcessTimer` — excludes driver startup   |
| HTTP fresh (no cache)         |  0.87 s    | resolve incidente + detalhe + 9 tabs (‖8)  |
| HTTP cache hit                |  0.27 s    | still does the 302 incidente lookup        |
| Andamentos parse only         |  3.5 ms    | from cached fragment                       |

**~5.7× faster than Selenium steady-state** on a cold, unratelimited
request. Per-tab breakdown lives in `docs/stf-portal.md § url-flow`.

This number does **not** extrapolate to a full sweep. The WAF
ceiling is what dominates over 100+ consecutive requests; see
`docs/rate-limits.md`.

## Why HTTP won — historical reasoning

The bench was decisive on three axes:

- **Per-request floor.** Browser startup + JS + click-wait dominates
  when not throttled. HTTP avoids both.
- **Iteration speed.** The HTML fragment cache (~60×) plus the
  URL-keyed PDF text cache (~70×) means re-runs of the same code
  against the same corpus run at local-CPU speed; no need for either
  client.
- **Test surface.** HTTP is `requests` + parse — pure functions taking
  bytes, returning dicts. Selenium tests required driver startup and
  JS-state mocking. The HTTP tests are now `tests/unit/`.

Every field the Selenium scraper emitted is reachable from the same
HTML fragments the browser eventually rendered — the choice was
"fetch them directly" vs. "let jQuery do it." See `docs/stf-portal.md
§ Field → source map` for the field-to-source mapping.

## Speedup table (Selenium row preserved)

The original `docs/performance.md § Expected speedup table` carried a
Selenium baseline row alongside the HTTP variants. Preserved here for
context; the live doc only carries HTTP variants now.

| Approach                                  | Per process (small) | Per process (heavy) | 100 processes | 1000 processes |
|-------------------------------------------|-------------:|-------------:|--------------:|---------------:|
| Selenium (measured baseline)              | 5 s          | ~20 s        | ~33 min       | ~5.5 h         |
| HTTP serial                               | ~2.5 s       | ~5 s         | ~8 min        | ~1.4 h         |
| HTTP, tabs parallel                       | ~1.5 s       | ~2 s         | ~3 min        | ~33 min        |
| HTTP, 1 worker + retry-403 (sweep E)      | ~3.6 s       | ~3.6 s       | ~6 min        | ~60 min        |
| **HTTP, 4-shard + proxy rotation** (measured, 2026-04-18) | ~0.98 s aggregate | ~0.98 s aggregate | ~1.5 min | ~16 min |

The **per-process speedup is larger on heavier cases**. Click-gated
tabs (`andamentos`, `peticoes`, `recursos`) are where Selenium pays
the `button_wait` penalty and where HTTP pays nothing. Small
processes show 2–3×; processes with full docket depth show 5–10×.
