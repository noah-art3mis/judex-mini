# PDF sweeps — directory layout

PDF-sweep results live here in one directory per run, named
`<date>-<label>/`. Both `baixar-pecas` (via
`judex.sweeps.download_driver.run_download_sweep`) and `extrair-pecas`
(via `judex.sweeps.extract_driver.run_extract_sweep`) write this same
institutional layout — state, log, errors, optional request_log,
report — so the operational tooling (monitoring, archiving) is
uniform across both halves of the pipeline.

## Expected files

| File | Written by | Purpose |
|---|---|---|
| `pdfs.state.json`   | `judex.pdf_store.PecaStore._write_state_atomically` | compacted per-URL state, atomic rewrite |
| `pdfs.log.jsonl`    | `PecaStore.record` (per attempt, fsynced)         | append-only attempt log; source of truth if `state.json` tears |
| `pdfs.errors.jsonl` | `PecaStore.write_errors_file`                     | derived; feeds `--retry-from` on the next run |
| `requests.db`       | `judex.utils.request_log.RequestLog` (SQLite WAL)  | per-GET URL / status / latency / bytes |
| `report.md`         | `pdf_driver._render_pdf_report`                  | auto-generated; status counts, extractor breakdown, per-host HTTP stats |
| `SUMMARY.md`        | human                                            | human narrative — headline numbers, outliers, what changed |
| `run.log`           | `tee`                                            | optional; stdout capture for ad-hoc invocations |

## Writing the SUMMARY.md

Follow the shape of
[`docs/sweep-results/2026-04-16-E-full-1k-defaults/SUMMARY.md`][E]
(the canonical template for process sweeps). Typical sections:

1. **Status** — complete / partial / stopped-early and why.
2. **Date + config** — commit sha, `ScraperConfig` values that matter
   (retry_403, throttle floor, strategy), run wall clock.
3. **Headline table** — targets, ok / unchanged / failed, wall pace,
   retries, biggest outliers.
4. **Stalls or outliers** — rows where wall >> p90, what happened,
   whether the breaker or retry logic absorbed it.
5. **Implications for downstream analysis** — what numbers change in
   the profile/notebook because of this run.

[E]: ../sweep-results/2026-04-16-E-full-1k-defaults/SUMMARY.md

## Scripts that populate this directory

The PDF pipeline is split into two commands (see
[`docs/superpowers/specs/2026-04-19-varrer-pdfs-ocr-knob.md`](superpowers/specs/2026-04-19-varrer-pdfs-ocr-knob.md)):

- `scripts/baixar_pecas.py` — routes through
  `judex.sweeps.download_driver.run_download_sweep`. The only path that
  talks to STF; writes raw bytes to `data/cache/pdf/<sha1>.pdf.gz`.
- `scripts/extrair_pecas.py` — routes through
  `judex.sweeps.extract_driver.run_extract_sweep`. Reads cached bytes,
  dispatches via `--provedor {pypdf|mistral|chandra|unstructured}`,
  writes text + sidecar + (optional) elements. Zero HTTP.

Both share four input modes (priority: `--retentar-de` > `--csv` >
`-c` + `-i`/`-f` range > filter fallback) and the same preview +
confirm guardrails (`--dry-run`, `--nao-perguntar`). Filters
(`--classe`, `--impte-contem`, `--tipos-doc`, `--relator-contem`,
`--excluir-tipos-doc`) apply only in the fallback mode.
