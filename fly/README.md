# Tesseract on Fly.io — prototype

HTTP-wrapped Tesseract OCR for fanout-on-demand. Mirrors the Modal
`tesseract_extract` endpoint but runs on Fly.io Machines, which are
~3-4× cheaper per cpu-hour and per-second billed (no hourly
minimum).

## Architecture

```
local box                          Fly.io app (judex-ocr-tesseract)
─────────                          ────────────────────────────────
extrair-pecas      ──HTTPS POST──▶ Machine 1  ┐
  thread pool      ──HTTPS POST──▶ Machine 2  │  auto-spawned, scales
  (N concurrent)   ──HTTPS POST──▶ Machine N  ┘  to 0 when idle
                                  ↑
                                  raw PDF bytes in body
                                  text/n_pages JSON out
```

- **Stateless service.** Each request carries one PDF; response carries
  text. No queue, no shared storage, no extracted-text cache on the Fly
  side — that lives on the local box, same as today.
- **Parallelism = client thread pool.** The local extractor opens N
  HTTPS connections concurrently; Fly's `auto_start_machines = true`
  spins up Machines to match.
- **Cold start.** First request after idle ≈ 5 s (image pull from
  Fly's registry, container start, uvicorn boot). Successive requests
  hit warm Machines at ~30 ms overhead.

## Cost (anchored against a real two-day bill, 2026-05-02)

Fly bills the cluster on **two meters**, not one — this is what the
$0.0118/hr quote used to miss:

```
Shared CPU 2x (gru):       $0.00000242 / Machine-second   ($0.0087/hr)
Additional RAM (gru):      $0.00000312 / GB-second × 3.5 GB additional
                                                          ($0.0394/hr)
                                                          ──────────
combined per Machine-hour:                                $0.0479/hr
```

The "additional 3.5 GB" is `[[vm]] memory = "4gb"` minus the ~0.5 GB
included in shared-cpu-2x. RAM is **82% of the line item** — heavier
than CPU. If you change Memory in `fly.toml`, this rate moves with
it (memory at "2gb" → 1.5 GB additional → ~$0.0259/hr per Machine).

Bill-anchored derivation: $8.70 spent over 138,931 + 514,472 =
653,403 Machine-seconds = 181.5 Machine-hours → $0.0479/hr exactly.

For the 12,930 ACÓRDÃO ladder at ~5 s OCR per PDF:

```
total compute    = 12930 × 5 s = 64,650 Machine-sec ≈ 18 Machine-hr
total bill       = 18 × $0.0479 = $0.86
wall (30-way)    = 12930 × 5 / 30 ÷ 60 ≈ 36 min
```

vs. Modal's $2.27 estimate for the same work — **~2.6× cheaper**
(was claimed as "10× cheaper"; that quote dropped the RAM line).

## One-time setup

```bash
# Install flyctl (no sudo required; lands in ~/.fly/bin)
curl -L https://fly.io/install.sh | sh
export FLYCTL_INSTALL="$HOME/.fly"
export PATH="$FLYCTL_INSTALL/bin:$PATH"

# Sign in (browser-based auth; one-time)
flyctl auth login

# Verify
flyctl auth whoami
```

## Deploy

```bash
cd fly
flyctl launch --no-deploy --copy-config --name judex-ocr-tesseract
# (or `flyctl apps create judex-ocr-tesseract` if launch is too magic)
flyctl deploy
```

The first deploy uses Fly's remote builder — **no local Docker
required**. Subsequent deploys reuse cached image layers (only the
~110 MB Portuguese language pack is the slow layer).

## Smoke test

```bash
# Pick any cached ACÓRDÃO from data/raw/pecas/
SHA=$(ls data/raw/pecas/*.pdf.gz | head -1 | xargs -n1 basename | sed 's/\.pdf\.gz$//')
gunzip -c data/raw/pecas/${SHA}.pdf.gz | \
    curl -X POST -H "Content-Type: application/pdf" --data-binary @- \
    https://judex-ocr-tesseract.fly.dev/extract \
    | jq '.n_pages, .wall_seconds, (.text[:200])'
```

Expected: `n_pages` ≥ 1, `wall_seconds` < 60 for typical ACÓRDÃOs,
text starts with "SUPREMO TRIBUNAL FEDERAL" or similar.

## Integration into `extrair-pecas` (landed 2026-05-01)

The `tesseract_fly` provider is registered in
`judex/scraping/ocr/tesseract_fly.py` and wired through the dispatch
registry. Use it via `--provedor tesseract_fly` after exporting
`FLY_TESSERACT_URL`:

```bash
export FLY_TESSERACT_URL=https://judex-ocr-tesseract.fly.dev/extract

# Sequential (one PDF in flight) — useful for smoke test:
uv run judex extrair-pecas \
    --csv runs/active/extrair-acordaos-2026-05-01/cases.csv \
    --provedor tesseract_fly --saida runs/active/extrair-fly-test \
    --limite 5 --nao-perguntar
```

Throughput fanout is gated by the new `--paralelo N` flag, which
wraps `run_extract_sweep`'s per-target dispatch in a
`ThreadPoolExecutor(max_workers=N)`. The store's `record()` is
serialised behind a `threading.Lock`; per-URL cache writes are
already sha1-keyed so they don't collide. The breaker is disabled
in parallel mode (would race across threads); provider errors retry
via `--retentar-de` instead.

```bash
# Production-shape: 30 concurrent HTTPS requests to Fly,
# Machines auto-spawn to match.
uv run judex extrair-pecas \
    --csv runs/active/extrair-acordaos-2026-05-01/cases.csv \
    --provedor tesseract_fly \
    --saida runs/active/extrair-fly-2026-05-01 \
    --paralelo 30 --retomar --nao-perguntar
```

`--paralelo` is meaningful only for HTTP-bound providers
(tesseract_fly, tesseract_modal, mistral, chandra*); local providers
(pypdf, tesseract) are CPU-bound and gain no throughput from thread
fanout — leave at 1.

To route the `auto` router's ACÓRDÃO branch through Fly instead of
local Tesseract, edit `judex/sweeps/extrair_pecas.py:56` to return
`"tesseract_fly"` instead of `"tesseract"`. Not done by default —
keeps `auto` self-contained (no external endpoint dependency).

## Cluster management

Three independent levers control the cluster. Knowing which to reach
for is the difference between "scale up before a sweep" and
"accidentally re-burn 2x as much money."

### Lever 1 — provisioned count (`flyctl scale count`)

How many Machine slots exist. Provisioned ≠ running: with
`auto_stop_machines = "stop"` (the current config), idle Machines drop
to `stopped` and cost $0/hr. The count is the *ceiling* on how much
parallelism you can absorb at peak, not the floor of what you pay
when idle.

```bash
flyctl scale count 100 -a judex-ocr-tesseract-arcos   # provision 100 slots
flyctl scale count   1 -a judex-ocr-tesseract-arcos   # shrink to 1
flyctl scale count   0 -a judex-ocr-tesseract-arcos   # destroy all (recoverable)
```

A `flyctl deploy` that changes `[[vm]]` shape (size or memory)
implicitly destroys-and-recreates Machines because Fly can't reshape
a running container in place. **Expect count to drop after a memory
change** — re-`scale count` to your target afterward.

### Lever 2 — per-Machine shape (`flyctl scale memory` / `vm`)

How much CPU and RAM each Machine has. These bypass `flyctl deploy`
and reshape Machines directly:

```bash
flyctl scale memory 1024  -a judex-ocr-tesseract-arcos       # cap RAM at 1 GB
flyctl scale memory 1536  -a judex-ocr-tesseract-arcos       # nudge to 1.5 GB
flyctl scale vm shared-cpu-4x -a judex-ocr-tesseract-arcos   # bigger CPU
```

Use this for hot-fix recovery when production OCR shows OOM symptoms
— faster than editing `fly.toml` + redeploying.

### Lever 3 — auto-start / auto-stop (in `fly.toml`)

When a provisioned Machine wakes vs sleeps. Currently:

```toml
[http_service]
  auto_start_machines  = true     # cold-start (~5s) on incoming request
  auto_stop_machines   = "stop"   # idle Machines stop after ~5 min of no traffic
  min_machines_running = 0        # no minimum kept warm
```

Together: **pay only for active OCR seconds; idle = $0.** Production
sweeps wake Machines on demand; the cluster auto-quiesces afterward.

## Turning the cluster off — three levels

Pick by what you want preserved.

### Level 1 — do nothing

`auto_stop_machines = "stop"` already drops Machines to `stopped`
~5 min after the last request. **Stopped Machines cost $0** (no
compute, only ~free root-fs storage).

- Effort: zero
- Idle cost: $0
- Wake-up: ~5 s cold start on next request
- Reversible: automatic

This is the right answer for "I'm not running anything for a few
days but might next week."

### Level 2 — scale to 0 (`flyctl scale count 0`)

Destroys all provisioned Machines but keeps the app, image, and
config on Fly.

```bash
flyctl scale count 0 -a judex-ocr-tesseract-arcos
```

- Idle cost: $0 (no Machine slots to bill)
- Wake-up: `flyctl scale count <N>` re-provisions from current
  `fly.toml` in ~30-60 s
- Reversible: trivially

This is the **paranoid, no-surprise-bill** option. Choose it when
you're parking the cluster for weeks/months and want to be sure
nothing can spin up unexpectedly.

### Level 3 — destroy the app (`flyctl apps destroy`)

```bash
flyctl apps destroy judex-ocr-tesseract-arcos
```

- Permanently removes app, Machines, deployment history, DNS
- Reversible only by `cd fly && flyctl launch` (full re-create)
- Stops billing immediately

The nuclear option. Only choose this if abandoning the OCR project
entirely. We have no volumes, so there's nothing to GC manually —
but you do lose deployment history.

## Decision tree

| Situation | Lever |
|---|---|
| Production sweep starting | `flyctl scale count <N>` to your target parallelism |
| OCR throwing OOMs in production | `flyctl scale memory 1536` to widen headroom instantly |
| Done sweeping for the day | (do nothing — auto-stop quiesces in ~5 min) |
| Parking the cluster for weeks | `flyctl scale count 0` |
| Abandoning the OCR project | `flyctl apps destroy judex-ocr-tesseract-arcos` |

## Inspection commands

```bash
flyctl scale show -a judex-ocr-tesseract-arcos        # provisioned count + shape
flyctl status     -a judex-ocr-tesseract-arcos        # Machine list + states
flyctl logs       -a judex-ocr-tesseract-arcos        # tail logs (Ctrl-C to stop)
flyctl logs --no-tail -a judex-ocr-tesseract-arcos    # last batch only
flyctl machine status <id> -a judex-ocr-tesseract-arcos   # one Machine in detail
```
