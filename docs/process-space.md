# Process space — how big each STF class is

Sweep planning needs to know, for each class (HC, ADI, RE, …), (a)
the highest extant `processo_id` and (b) roughly how many of the IDs
in `[1, ceiling]` are real processes vs. gaps. This doc records the
current numbers, the methodology that produces them, and how to
refresh them.

See also:
- [`docs/rate-limits.md`](rate-limits.md) — wall-time math uses these counts.
- [`docs/stf-portal.md`](stf-portal.md) — the incidente-resolution endpoint used by the probes.

## Current numbers

Binary-searched + density-probed 2026-04-16; HC refreshed evening
2026-04-16. See `docs/sweep-results/2026-04-16-G-hc-density-probe.md`
for the HC measurement.

| Class | Highest extant `processo_id` | Measured / estimated count | Density | Source |
|-------|---:|---:|---:|---|
| HC    | **270,994** | **~216,000** | 69% (**bimodal** — ≤47% below 50k, 87–93% above) | measured (sweep G) |
| ADI   | 7,956       | ~4,800       | 60.9%  | estimated from sweep C |
| RE    | 640,321     | ~380,000     | ~60% (assumed) | ceiling binary-searched; density not yet probed |

HC's bimodal density is worth noting: the older paper-era range
(≤50k) has many gaps; the post-digitization range (>50k) is densely
packed. This matters for sampling — a uniform random sample across
the full range over-represents older cases.

HC ceiling moves continuously. The 2026-04-16 morning ceiling of
270,071 moved to 270,994 by that evening — ~923 new HCs filed in
<12h, consistent with STF's ~1–2k/day HC intake. Linear scan-down
from `ceiling + 1000` is a ~10-probe refresh.

## Binary-search technique — ceiling

For any class, find the highest extant `processo_id` in ~20 probes
(one HTTP request each, reusable session):

```python
# The probe: listarProcessos.asp on (classe, N).
#   302 with Location = exists (processo present).
#   200 with empty body = missing (gap).
# Double an upper bound until it 200s, then binary-search
# between the last confirmed-exists and the first confirmed-empty.
```

A one-shot harness lives in `scripts/class_density_probe.py` — that's
the right entrypoint for new probes, not the conversation-log snippet
above.

## Density-probe technique

Ceiling × density = count, and density isn't constant across the
range. The density probe draws ~500 uniform random `processo_id`s
from stratified buckets, probes each, and reports the hit rate per
stratum. For HC, the output immediately showed the ≤50k / >50k split.

Run time: ~3 minutes per class at sweep-validated pacing.

## Commands

```bash
# Ceiling + density probe for any class — 3 min per run
PYTHONPATH=. uv run python scripts/class_density_probe.py --classe HC
PYTHONPATH=. uv run python scripts/class_density_probe.py --classe ADI
PYTHONPATH=. uv run python scripts/class_density_probe.py --classe RE
```

The probes write to `docs/sweep-results/<date>-<label>-<classe>-density-probe.md`
by default; follow the sweep directory layout in [`data-layout.md`](data-layout.md).

## Why this matters for sweeps

Sweep scope is "process IDs `[lo, hi]` for class C". Without density
numbers, a caller can't tell whether `[1, 1000]` means "1000 processes
to fetch" or "600 hits and 400 fast-404s" — a 40% savings in wall time
and WAF pressure. And without the bimodal structure, sampling from HC
uniformly over-represents the paper-era tail.

Default sweeps (`scripts/run_sweep.py`) treat 404 / missing processes
as non-errors and continue; the state machinery logs them as `missing`
in `sweep.state.json`. Reconstruction from `sweep.log.jsonl` of
"what's real in this range" is post-hoc.

## Refresh cadence

- **HC ceiling** — refresh before any large HC sweep; moves ~1–2k/day.
- **ADI ceiling** — stable-ish; refresh monthly or before a full backfill.
- **RE ceiling** — stable-ish; refresh before a full backfill.
- **Densities** — refresh when the ceiling has moved >5–10% since the last probe, or when scope is sensitive to density (e.g. "how many HCs in 2024?" needs a date-joined density, not the lifetime one).
