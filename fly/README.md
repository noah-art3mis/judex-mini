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

## Cost (2026 rates, verify before bulk runs)

```
shared-cpu-2x + 4 GB ≈ $0.0118/hr per Machine
```

For the 12,930 ACÓRDÃO ladder at ~5 s OCR per PDF:

```
total compute    = 12930 × 5 s = 64,650 cpu-sec ≈ 18 cpu-hr
total bill       = 18 × $0.0118 = $0.21
wall (30-way)    = 12930 × 5 / 30 ÷ 60 ≈ 36 min
```

vs. Modal's $2.27 estimate for the same work — **~10× cheaper**.

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

## Teardown

```bash
flyctl apps destroy judex-ocr-tesseract
```

Stops billing immediately. No persistent volumes attached, so this is
clean — nothing to GC manually.
