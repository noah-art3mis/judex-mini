# Setup — Fly.io (`tesseract_fly` provider)

Self-hosted Tesseract on Fly.io Machines. Used by `--provedor
tesseract_fly`. Default cloud OCR (~$0.005 / 1k pages).

**Full deploy runbook + bill math: [`fly/README.md`](../fly/README.md).**
This doc is the integration recap.

## One-time setup

```bash
curl -L https://fly.io/install.sh | sh
export PATH="$HOME/.fly/bin:$PATH"
flyctl auth login
cd fly && flyctl launch --no-deploy --copy-config --name judex-ocr-tesseract-arcos
flyctl deploy
```

## Wire it into a sweep

```bash
export FLY_TESSERACT_URL=https://judex-ocr-tesseract-arcos.fly.dev/extract

uv run judex extrair-pecas --csv runs/active/<sweep>/cases.csv \
    --provedor tesseract_fly --paralelo 30 \
    --saida runs/active/<sweep>/ --retomar
```

`--paralelo` is meaningful only for HTTP-bound providers — leave at 1
for `pypdf` / local `tesseract`.

## Cluster ops

| Action | Command |
|---|---|
| Provision N Machines | `flyctl scale count <N> -a judex-ocr-tesseract-arcos` |
| Inspect | `flyctl scale show -a …` / `flyctl status -a …` |
| Tail logs | `flyctl logs -a …` |
| Park (zero spend) | `flyctl scale count 0 -a …` |

`auto_stop_machines = "stop"` (current `fly.toml`): idle Machines
bill $0/hr. Provisioned count is the parallelism ceiling, not the
idle floor.

## Backpressure sizing

Tenacity budget is 300s (`judex/scraping/ocr/tesseract_fly.py:114`).
Math for "how many Machines do I need":

```
expected_drain ≈ (N_shards − M_machines) / M_machines × 30s × 2
```

Aim for `expected_drain < 100s`. At 32 shards: M=14 is comfortable,
M=9 is tight.

If `pdfs.log.jsonl` shows `provider_error · ~300s · tesseract_fly`,
the budget exhausted — recovery via `judex extrair-pecas
--retentar-de <run>/errors.jsonl`. See
[`docs/recovery-patterns.md`](recovery-patterns.md).
