# Current progress — judex-mini

Branch: `dev`. Prior cycle archived at
[`docs/progress_archive/2026-05-01_1750_cloud-ocr-fly-landing.md`](progress_archive/2026-05-01_1750_cloud-ocr-fly-landing.md)
— ACÓRDÃO re-extract diagnostics + Fly.io cloud-OCR pivot
(2026-05-01). Empirical close-out: local Tesseract structurally
unstable on the 4 GB WSL2 box (Pool deadlocks under OOM); landed
`tesseract_fly` provider + `--paralelo` thread-pool wrapper +
`fly/` deploy stack. Chosen path: Fly shared-cpu-2x × 60 Machines,
~$0.10 / 1k pages, ~1.8 hr per HC year-ladder. App deployed at
`judex-ocr-tesseract-arcos.fly.dev` (gru, 60 shared-cpu-2x
Machines, auto-stop-when-idle).

**Status as of 2026-05-01 evening.** Corpus: **90,763** cases.
PDF cache 99,057 `.pdf.gz` + 3,621 `.rtf.gz`, 105,821 `.txt.gz`.
Warehouse last rebuilt 2026-04-30 17:45 BRT — needs a refresh
once the HC 2026 chain closes.

## Active task — HC year-ladder backfill via 3-stage chain

**Why.** Iterate `varrer-processos → baixar-pecas → extrair-pecas`
per HC year, working backward from 2026, to close out the four-year
HC ladder (2022-2026) with current Fly-cloud OCR for ACÓRDÃOs and
correct EMENTAs corpus-wide.

**Chain shape (per year).** Sequential, idempotent (`set -e` +
`--retomar` everywhere). Run dir: `runs/active/backfill-hc<YYYY>-<date>/`.

```bash
export PATH="$HOME/.fly/bin:$PATH"
export FLY_TESSERACT_URL=https://judex-ocr-tesseract-arcos.fly.dev/extract
export JUDEX_AUTO_TESSERACT_PROVIDER=tesseract_fly

nohup bash -c '
set -e
uv run judex varrer-processos -c HC -i <PID_LO> -f <PID_HI> \
    --saida runs/active/backfill-hc<YYYY>-<date>/varrer \
    --diretorio-itens data/source/processos \
    --rotulo hc<YYYY>_backfill_<date> --retomar
uv run judex baixar-pecas -c HC -i <PID_LO> -f <PID_HI> \
    --saida runs/active/backfill-hc<YYYY>-<date>/baixar \
    --retomar --nao-perguntar
uv run judex extrair-pecas -c HC -i <PID_LO> -f <PID_HI> \
    --provedor auto \
    --saida runs/active/backfill-hc<YYYY>-<date>/extrair \
    --paralelo 60 --retomar --nao-perguntar
' > runs/active/backfill-hc<YYYY>-<date>/launcher-stdout.log 2>&1 &
```

**Per-year PID ranges** (from warehouse, refresh if corpus grows):

| Year | PID range          | Cases captured / total |
| ---- | ------------------ | ---------------------- |
| 2026 | 267,138 → 271,139  | 3,099 / 4,001          |
| 2025 | 250,920 → 267,137  | 13,365 / 16,200        |
| 2024 | 236,530 → 250,918  | 12,014 / 14,387        |
| 2023 | 223,886 → 236,833  | 11,129 / 12,644        |
| 2022 | 210,964 → 223,885  | 10,824 / 13,057        |

**HC 2026 chain in flight** (PID 1280502, launched 2026-05-01 17:40
BRT). Stage A (varrer) ~done (4001/4002 walked, 3097 ok + 903 dead
PIDs); stage B + C will auto-trigger via `&&`. Expected total
wall ~2.5 hr.

**Monitor.** Same pattern across all 3 stages:

```bash
tail -f runs/active/backfill-hc2026-2026-05-01/launcher-stdout.log
```

(Per CLAUDE.md § Conventions, this is the canonical live sweep
monitor — don't reach for anything fancier first.)

**Done when.** Stage C's `report.md` shows ≥99% ok across the
year's targets; spot-check 5–10 ACÓRDÃO `.txt.gz` files (`EXTRATO
DE ATA` and `RELATÓRIO`/`VOTO` markers should appear exactly once
per doc). Then move on to HC 2025, repeating the chain with the
next PID range. After all five years close out, rebuild the
warehouse: `uv run judex atualizar-warehouse --classe HC`.

## Backlog (carried over from prior cycle)

1. **Urgent — DJe scraper regression** (post-2022 blackout).
   Path 1 (andamentos-side regex parse) is the cheap mitigation;
   Path 2 (Playwright against `digital.stf.jus.br`) is the proper
   fix. See archived cycle § "Urgent — DJe scraper regression"
   for the full diagnosis + 200-case empirical table.
2. **HC 2017–2021 case sweeps** — ~37k missing case widths combined,
   ordered by year-density. Once cases land, re-use the 3-stage
   chain above per year.
3. **Schema cleanup** — drop `andamentos.link_text` /
   `documentos.text` / `decisoes_dje.rtf_text` from the warehouse
   build path (queries already use `pdfs_substantive`'s join).
4. **`publicacoes_dje` → warehouse** — open warehouse gap noted in
   prior archive § Backlog.
5. **`pick_provider` env-var override** is in place
   (`JUDEX_AUTO_TESSERACT_PROVIDER`) but the auto-router default
   remains `"tesseract"` for unit-test stability. Consider flipping
   the default to `"tesseract_fly"` once the Fly path proves stable
   over a full year-ladder.

## Where things live (durable pointers)

- [`docs/data-layout.md`](data-layout.md) — file/store map.
- [`docs/stf-portal.md`](stf-portal.md) — URL flow, auth triad, field map.
- [`docs/system-changes.md`](system-changes.md) — STF-side timeline + schema history.
- [`docs/rate-limits.md`](rate-limits.md) — WAF behavior, validated defaults.
- [`docs/process-space.md`](process-space.md) — class sizes + density.
- [`docs/cost-estimates.md`](cost-estimates.md) — per-unit anchors.
- [`docs/warehouse-design.md`](warehouse-design.md) — DuckDB schema + build.
- [`docs/data-dictionary.md`](data-dictionary.md) — schema history v1→v8.
- [`docs/completion-tracker.md`](completion-tracker.md) — per-year coverage.
- [`docs/reports/`](reports/) — promoted narratives (validation sweeps, OCR bakeoff).
- [`docs/superpowers/specs/`](superpowers/specs/) — major-feature design specs.
- [`fly/`](../fly/) — Fly.io OCR app (Dockerfile + server.py + fly.toml + README).

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration.
- **`config/`** — git-ignored (credentials). Canonical proxy input is
  `config/proxies` (flat file).
- **All non-trivial arithmetic via `uv run python -c`** — never mental
  math. See `CLAUDE.md § Arithmetic`.
- **Sweeps write a directory**, not a file. Layout in
  [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).
- **Live sweep monitor**: `tail -f <run_dir>/launcher-stdout.log` is
  the canonical view across all 3 pipeline stages — see
  `CLAUDE.md § Conventions`. Don't roll bespoke monitor scripts.
- **Archive convention**: when the active task closes out or this file
  grows past ~500 lines, move it (or the cycle-specific portion) to
  `docs/progress_archive/YYYY-MM-DD_HHMM_<slug>.md`.
