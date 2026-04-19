# Post-migration verification + overnight HC backfill — PLAN

**Status: drafted 2026-04-19. Awaiting `scripts/renormalize_cases.py` full-corpus completion.**

Gates a verification pass between the v3→v6 schema migration and the next year-priority backfill tier. Reuses the existing launcher (`scripts/launch_hc_year_sharded.sh`) and the year-priority plan in [`docs/hc-backfill-extension-plan.md`](../hc-backfill-extension-plan.md); adds the migration-gate checks and the overnight sequencing.

---

## Phase 1 — Post-migration verification (~30–45 min)

Runs once the renormalizer exits. All gates must pass before any scraping starts. If anything fails, diagnose and re-run Phase 1 — the renormalizer is `--resume`-safe via the `already_current` short-circuit, so correcting a bug mid-corpus is cheap.

| # | Check | Command | Pass condition |
|---|---|---|---|
| 1A | Renormalizer summary          | `tail -50 <renormalize log>`                                                                             | No `error` rows beyond known `needs_rescrape` category |
| 1B | Unit tests                    | `uv run pytest tests/unit/`                                                                              | All green |
| 1C | Random-sample schema audit    | one-liner below                                                                                          | 100/100 files report `schema_version=6`, ISO dates, dict-shaped `outcome`/`link`, snake_case sessão keys |
| 1D | Ground-truth parity           | `PYTHONPATH=. uv run python scripts/validate_ground_truth.py`                                            | All 5 fixtures match |
| 1E | Warehouse rebuild             | `PYTHONPATH=. uv run python scripts/build_warehouse.py`                                                  | `done in <Ns>`; no `_flatten_case` exceptions |
| 1F | Warehouse sanity SQL          | DuckDB queries below                                                                                     | `schema_version=6` on 100% of `cases`; `outcome_verdict` distribution sane; near-zero NULLs in `data_protocolo_iso` / andamento links |
| 1G | Canary notebook               | `uv run marimo export html analysis/hc_famous_lawyers.py -o /tmp/verify.html`                            | Exits clean (the dict-unhashable-type tripwire) |

### 1C random-sample one-liner

```bash
uv run python -c "
import json, random
from pathlib import Path
files = list(Path('data/cases').rglob('judex-mini_*.json'))
bad = []
for f in random.sample(files, 100):
    d = json.loads(f.read_text())
    rec = d[0] if isinstance(d, list) else d
    meta = rec.get('_meta') or {}
    if meta.get('schema_version') != 6: bad.append((f.name, 'not v6'))
    if rec.get('outcome') is not None and not isinstance(rec.get('outcome'), dict):
        bad.append((f.name, 'outcome not dict'))
print('bad:', bad or 'none')
"
```

### 1F warehouse sanity SQL

```sql
SELECT schema_version, COUNT(*) FROM cases GROUP BY 1;                             -- expect only {6: N}
SELECT outcome_verdict, COUNT(*) FROM cases GROUP BY 1 ORDER BY 2 DESC;
SELECT COUNT(*) FROM cases WHERE data_protocolo_iso IS NULL AND classe = 'HC';     -- expect small
SELECT COUNT(*) FROM andamentos WHERE link_url IS NOT NULL AND link_tipo IS NULL;  -- expect 0
SELECT * FROM manifest ORDER BY built_at DESC LIMIT 1;
```

**Fail mode:** any check fails → don't launch overnight. Diagnose, patch, re-run Phase 1.

---

## Phase 2 — Overnight year-backfill (tier 0 → tier 2/3)

Gate: Phase 1 green. Target: ≥ 8 h window at 8-shard throughput.

### Refresh stale inputs first

`tests/sweep/hc_2026_gap.csv` (918 rows) and `hc_2025_gap.csv` (6797 rows) were generated 2026-04-18. HCs captured since then would double-fetch. Regenerate all three years first:

```bash
PYTHONPATH=. uv run python scripts/generate_hc_year_gap_csv.py --year 2026 --out tests/sweep/hc_2026_gap.csv
PYTHONPATH=. uv run python scripts/generate_hc_year_gap_csv.py --year 2025 --out tests/sweep/hc_2025_gap.csv
PYTHONPATH=. uv run python scripts/generate_hc_year_gap_csv.py --year 2024 --out tests/sweep/hc_2024_gap.csv
```

### Tier 0 — 2026 catch-up (smoke test, ~18–30 min)

This is the **empirical anchor** for the 8-shard scaling claim (projected ~92 ok/min, untested). A ~20-min smoke test under the new conditions de-risks the 4+ hours of subsequent tiers.

```bash
nohup ./scripts/launch_hc_year_sharded.sh 2026 \
    > runs/active/$(date +%F)-hc-2026/launcher.log 2>&1 & disown
```

Wait for all 8 shards to finish — they exit when their CSV is exhausted.

**Tier-0 pass gates** (from the year-priority plan's § Stop criteria):

- `ok/total ≥ 0.80` across shards.
- ≥ 80% of captured cases have `data_protocolo` in 2025–2026.
- No `aborted` state; no new error classes in `sweep.errors.jsonl`.
- Wall ≤ 2× estimate (i.e. ≤ 1 h).

### Tier 1 — 2025 (~1.5–2.5 h at 8-shard)

```bash
nohup ./scripts/launch_hc_year_sharded.sh 2025 \
    > runs/active/$(date +%F)-hc-2025/launcher.log 2>&1 & disown
```

### Tier 2 — 2024 (~2.5–4.9 h at 8-shard)

The **biggest modern gap** (13,609 IDs) — most valuable slot if the budget allows it.

```bash
nohup ./scripts/launch_hc_year_sharded.sh 2024 \
    > runs/active/$(date +%F)-hc-2024/launcher.log 2>&1 & disown
```

Launch sequentially. The launcher doesn't queue tiers — each one only starts after the previous tier's shards all exit. If you prefer fire-and-forget, add a wrapper that `wait`s on the prior tier's `shards.pids`.

### Session-independent monitoring

Before bed, schedule a cron heartbeat via `/schedule` (per [`docs/agent-sweeps.md § session-independent alerting`](../agent-sweeps.md)). Cadence `13,43 * * * *` polls each active shard's `sweep.state.json` and alerts on: dead worker, status=`aborted`, no progress for ≥ 30 min, or new error class. Set `expires_after: 7 days` so alerts outlive the window that scheduled them.

### If things go sideways overnight

From any window:

```bash
pgrep -af "run_sweep.*hc_"                                   # identify running shards
xargs -a runs/active/<dir>/shards.pids kill -TERM            # clean stop
```

Everything on disk is atomic per-record; `--resume` picks up from exactly where it left off.

---

## Phase 3 — Morning audit (~20 min)

1. `PYTHONPATH=. uv run python scripts/probe_sharded.py --out-root runs/active/<dir>` per tier.
2. Promote `runs/active/<date>-hc-YYYY/` → `docs/reports/<date>-hc-YYYY.md` (consolidate shard REPORTs), then `mv` to `runs/archive/`.
3. Refresh `src/utils/hc_id_to_date.json` with new `(processo_id, data_protocolo)` anchors — tightens subsequent years' range derivation.
4. Update `docs/current_progress.md § What just landed` and `§ In flight`.
5. Rebuild warehouse: `PYTHONPATH=. uv run python scripts/build_warehouse.py`. Sanity-SQL it again — new rows should have `schema_version=6`.

---

## Out of scope for this overnight

- **PDF download + extraction** (`baixar-pdfs` then `extrair-pdfs --provedor {pypdf|mistral|chandra|unstructured}`) — separate sweep, run once the HC corpus is filled in. The download pass is WAF-bound and needs its own quota accounting; the extraction pass is local-only and can re-run OCR per provider without re-downloading.
- **Tiers 3+ (2023 → 2013)** — next night(s). Plan exists as-is in [`docs/hc-backfill-extension-plan.md`](../hc-backfill-extension-plan.md).
- **Non-HC classes** (RHC, AP, MS, RE, ADI) — one class at a time; reprioritize after HC is done.

---

## Decision points before launching

1. **Which tier-set fits the window?** ≥ 8 h → tiers 0 + 1 + 2. ≤ 4 h → tiers 0 + 1 only.
2. **Cron monitor cadence.** Twice-per-hour (`13,43 * * * *`) is the default; bump to hourly if noisy.
3. **Bandwidth budget.** `docs/hc-backfill-extension-plan.md § Year priority queue` projects ~7 GB total for tiers 0–13; three nights' worth of tiers = ~1–2 GB. Confirm ScrapeGW quota before launch.

---

## Why this shape

Verification before execution is cheap when the cost of continuing on broken data is high. Every minute scraping a corrupt-schema corpus is a minute producing records the warehouse and notebooks can't read — cheaper to spend 30 min confirming the migration than to re-scrape after discovering a bug at 03:00. Tier 0 as empirical anchor is the same logic at smaller scale: the 8-shard scaling projection (~92 ok/min) was written but never measured; a ~20-min smoke test de-risks the tiers that follow.
