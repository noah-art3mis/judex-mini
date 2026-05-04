# Setup — RunPod Serverless (`chandra_runpod` provider)

Self-hosted Chandra v2 on RunPod GPUs. ~$0.31 / 1k pages, ~10×
cheaper than Datalab's hosted Chandra.

**SOT for the provider:
[`judex/scraping/ocr/chandra_runpod.py`](../judex/scraping/ocr/chandra_runpod.py)** —
endpoint config (image, env vars, GPU tier, max workers), license
notes, and the `/run`+`/status` rationale live in that docstring.
This doc is the console walkthrough.

## One-time setup

1. **Account + credit.** Sign up at https://runpod.io, load credit.
2. **HF token.** Get a read-only token at huggingface.co; accept the
   Chandra license at
   `https://huggingface.co/datalab-to/chandra-ocr-2`.
3. **Create endpoint** (RunPod console → Serverless → New Endpoint):

| Field | Value |
|---|---|
| Container image | `runpod/worker-vllm` |
| GPU | 24 GB (RTX 4090 / 3090 Flex) |
| Max Workers | 5 (prod) / 2 (debug); never 1 |
| Idle Timeout | 60s |
| `MODEL_NAME` | `datalab-to/chandra-ocr-2` |
| `HF_TOKEN` | your HF token |
| `MAX_MODEL_LEN` | `16384` |
| `ENABLE_CHUNKED_PREFILL` | `true` |

(Why these specific values lives in the provider docstring.)

4. **Copy endpoint ID + API key** from the console and export:

```bash
export RUNPOD_API_KEY="rpa_..."
export RUNPOD_CHANDRA_ENDPOINT_ID="<endpoint id>"
```

## Smoke test + sweep

```bash
uv run judex executar --csv runs/active/<sweep>/cases.csv \
    --provedor chandra_runpod --paralelo 5 \
    --saida runs/active/<sweep>/ --retomar
```

`--paralelo` should match Max Workers. First request after idle is
~30s (vLLM cold start); warm = ~1 page/sec.

## Common failures

| Symptom | Fix |
|---|---|
| 401 | Regenerate `RUNPOD_API_KEY` |
| 404 on `/run` | Verify `RUNPOD_CHANDRA_ENDPOINT_ID` |
| Timeouts on every request | Confirm `MAX_MODEL_LEN=16384` |
| Quality much worse than hosted | Confirm `MODEL_NAME=datalab-to/chandra-ocr-2` |

Recovery flows: [`docs/recovery-patterns.md`](recovery-patterns.md).
