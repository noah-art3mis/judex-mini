# Setup — Modal (`tesseract_modal`, `surya`, `paddle` providers)

Self-hosted OCR endpoints on Modal: one app, three GPU classes.

**SOT for the app definition:
[`judex/scraping/ocr/modal_app.py`](../judex/scraping/ocr/modal_app.py)** —
images, GPU, timeouts, costs, bakeoff notes all live in that
docstring. This doc is the operational wrapper.

## One-time setup

```bash
uv run modal token new      # browser flow; persists ~/.modal.toml
uv run modal token info     # verify
```

## Deploy

```bash
uv run modal deploy judex/scraping/ocr/modal_app.py
```

First deploy ~10 min (image build); subsequent deploys are seconds
unless `pip_install` / `apt_install` lists change.

## Smoke test

```bash
uv run modal run judex/scraping/ocr/modal_app.py::test_endpoints
```

Exercises all three providers on a 1-page blank PDF. `text_len=0` is
correct — the PDF has no rendered text.

## Wire it into a sweep

```bash
uv run judex extrair-pecas --csv runs/active/<sweep>/cases.csv \
    --provedor tesseract_modal --paralelo 8 \
    --saida runs/active/<sweep>/ --retomar
```

`--paralelo 8` matches Modal's typical CPU-container concurrency
ceiling. Cluster mgmt is declarative — edit `@app.function(...)` in
`modal_app.py` and re-deploy. Default `scaledown_window=30` keeps
warm containers across rapid successive calls.

## When to pick Modal over Fly

`tesseract_fly` is the default (cheaper). Use `tesseract_modal` when
Fly's `gru` region is at capacity. Use `surya` / `paddle` for
layout-heavy peças where Tesseract's quality floor isn't enough —
see [`docs/reports/2026-04-30-ocr-bakeoff.md`](reports/2026-04-30-ocr-bakeoff.md).
