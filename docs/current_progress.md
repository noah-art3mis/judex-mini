# Current progress — judex-mini

Branch: `dev`. Prior cycle archived at
[`docs/progress_archive/2026-05-01_0016_ocr-bakeoff-tesseract-winner.md`](progress_archive/2026-05-01_0016_ocr-bakeoff-tesseract-winner.md)
— OCR provider bakeoff close-out (2026-04-30 → 2026-05-01). Tesseract
on Modal CPU replaces Mistral as production OCR (14× cheaper, beats
Mistral on every quality axis). Bakeoff narrative + per-provider
empirical findings promoted to
[`docs/reports/2026-04-30-ocr-bakeoff.md`](reports/2026-04-30-ocr-bakeoff.md).

**Status as of 2026-05-01.** Corpus: **90,763** cases. PDF cache
94,091 `.pdf.gz`, 105,821 `.txt.gz`. Warehouse rebuilt 2026-04-30
17:45 BRT (530s, 3.02 GB). HC 2022 peça sweep closed 2026-04-30
(15,007 ok / 0 fails); HC 2024 + HC 2023 closed earlier. Four-year
HC peça ladder (2022–2025) at ≥97% text coverage on direct IP.

**No active cycle.** Strategic state, in-flight notes, backlog,
known gaps, and reference commands carried forward from the prior
cycle are preserved in the archive linked above. Pull forward
relevant sections into this file when the next cycle opens.

## Next-cycle candidates (carried over from prior backlog)

1. **Cut over `extrair-pecas` default to Tesseract** — wire the new
   Modal-hosted provider into the `--provedor` flag and update
   `judex/cli.py` defaults. Optional ~30-line regex post-process to
   close the residual 1.04% gap (`§ → 8`, ellipsis-period drops,
   auth-code character-class swaps). Detail in the bakeoff report.
2. **HC 2024 extract second pass** — text coverage at 80% vs 97-99%
   on 2023/2022. Investigate ~3k-row gap (provider failures, RTF
   mistypes, scanned originals?) and run a focused
   `extrair-pecas --csv` retry, possibly with chandra/tesseract.
3. **HC 2017–2021 case sweeps** — ~37k missing case widths combined,
   ordered by year-density. Once cases land, peça sweeps follow in
   the proven 15k-URL/year shape.
4. **Schema cleanup** — drop `andamentos.link_text` /
   `documentos.text` / `decisoes_dje.rtf_text` from the warehouse
   build path (queries already use `pdfs_substantive`'s join). Lets
   `_CHUNK_SIZE` climb back toward 5000 + halves warehouse build
   peak RAM.
5. **`publicacoes_dje` → warehouse** — open warehouse gap noted in
   prior archive § Backlog.

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

## Working conventions

- **`analysis/`** — git-ignored scratch for this-session exploration.
- **`config/`** — git-ignored (credentials). Canonical proxy input is
  `config/proxies` (flat file).
- **All non-trivial arithmetic via `uv run python -c`** — never mental
  math. See `CLAUDE.md § Arithmetic`.
- **Sweeps write a directory**, not a file. Layout in
  [`docs/data-layout.md § Sweep run artifacts`](data-layout.md#sweep-run-artifacts).
- **Archive convention**: when the active task closes out or this file
  grows past ~500 lines, move it (or the cycle-specific portion) to
  `docs/progress_archive/YYYY-MM-DD_HHMM_<slug>.md`.
