# G — HC density probe (stratified sampling, 1..270072)

**Date**: 2026-04-16
**Script**: `scripts/class_density_probe.py --classe HC`
**Approach**: Stratified random sampling across 8 bands of the HC
process_id space; each probe is a single GET to
`portal.stf.jus.br/processos/listarProcessos.asp`.
A 302 with `Location: detalhe.asp?incidente=\d+` means the case exists;
a 200 with empty Location means STF returned the search homepage (no
match). No full scrape, no PDFs — the cheapest possible existence check.

**Parameters**: 15 samples per band · 1.5 s pacing · seed 20260416
(reproducible) · retry-403 on.

## Results

**120 probes · 191.4 s wall · 0 errors** (no WAF pressure; one-endpoint
probing stays well under the threshold).

| range | samples | exist | density | est. count in band |
|---:|---:|---:|---:|---:|
| 1 – 999             | 15 |  7 | 46.7% |    466 |
| 1,000 – 9,999       | 15 |  3 | 20.0% |  1,800 |
| 10,000 – 49,999     | 15 |  6 | 40.0% | 16,000 |
| 50,000 – 99,999     | 15 | 13 | 86.7% | 43,333 |
| 100,000 – 149,999   | 15 | 13 | 86.7% | 43,333 |
| 150,000 – 199,999   | 15 | 14 | 93.3% | 46,666 |
| 200,000 – 249,999   | 15 | 14 | 93.3% | 46,666 |
| 250,000 – 270,071   | 15 | 13 | 86.7% | 17,395 |
| **total**           | **120** | **83** | **69.2%** | **~215,659** |

## Key findings

- **~216,000 HCs exist** across the full space. The earlier handoff
  estimate of ~160k (assuming 60% density) was low; real density is
  69%. Cost projections downstream should use ~216k, not ~160k.

- **Bimodal distribution**. Sparse below ~50k (≤47% density, older
  paper-era and early-electronic cases), then **densely populated at
  87–93%** from 50k upward. Low-id ranges are where you burn budget
  on non-existent numbers; budget-optimal sweeps start at 50k.

- **Non-monotonic blip in [1k, 10k) at 20%** is small-sample noise
  (n=15). Rerunning with `--samples 30` would tighten the band
  estimates but doesn't change the overall shape.

## Current ceiling

Handoff recorded HC **270,071** as the highest extant id on
2026-04-16 morning. A top-end probe this session narrowed it down:

| HC    | exists | notes |
|------:|:------:|:------|
| 270,500 | ✓ | sparse probe |
| 270,900 | ✓ | sparse probe |
| 270,994 | ✓ | **current max** (incidente=7563864) |
| 270,995 | ✗ | linear scan down from 270,999 |
| 270,996 | ✗ | |
| 270,997 | ✗ | |
| 270,998 | ✗ | |
| 270,999 | ✗ | |
| 271,000 | ✗ | |
| 271,500 | ✗ | sparse probe |
| 272,000 | ✗ | sparse probe |

→ **current ceiling HC 270,994**, up from 270,071 recorded earlier
the same day. **~923 new HCs filed in <12 h** — consistent with STF's
typical ~1–2 k/day new HC rate. Confirm with a linear scan-down from
271k+delta any time; takes ~10 probes at 1.2 s pacing.

## Cost implications

Using sweep E's measured throughput of **3.6 s/process** (retry-403 +
2 s pacing, accounting for WAF stall cycles):

| target                                  | processes | wall time |
|-----------------------------------------|----------:|----------:|
| Full backfill (1 .. 271k)               | ~216,000  | ~215 h (~9 days) |
| Dense zone only (50k .. 271k)           | ~195,000  | ~195 h (~8 days) |
| 10k sample (any 5-year slice, dense)    | 10,000    | ~10 h     |
| 1k sample (probe/validation)            | 1,000     | ~60 min   |

Full backfill from one IP is **not practical**. Scoping options for the
HC deep dive:

1. **Sample-first** (recommended): 10k-20k HCs in the dense zone, one
   continuous run (~10-20 h). Enough data volume for most statistical
   questions; ships the tool so users can re-run for more scale.
2. **Time-sliced**: first map HC-id → filing-year boundaries with a
   small probe (~50 HCs), then backfill one year at a time.
3. **Full backfill**: only viable with a posture change (multiple IPs,
   STF whitelist, or cache-first distribution — see handoff for the
   three unresolved postures).

## Reproducing

```bash
PYTHONPATH=. uv run python scripts/class_density_probe.py --classe HC
PYTHONPATH=. uv run python scripts/class_density_probe.py --classe HC --samples 30 --pacing 1.0
PYTHONPATH=. uv run python scripts/class_density_probe.py --classe ADI
PYTHONPATH=. uv run python scripts/class_density_probe.py --classe RE
```

The script is under `analysis/` (git-ignored scratch) because it's a
one-endpoint probe, not a scraper. Ported to `scripts/` if/when the
team wants density maps in version control.
