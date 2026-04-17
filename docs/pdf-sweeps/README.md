# PDF sweeps — directory layout

PDF-sweep results live here in one directory per run, named
`<date>-<label>/`. Contents match the institutional layout written
by `src/pdf_driver.run_pdf_sweep` (when routed through it) plus a
human summary.

## Expected files

| File | Written by | Purpose |
|---|---|---|
| `pdfs.state.json`   | `src.pdf_store.PdfStore._write_state_atomically` | compacted per-URL state, atomic rewrite |
| `pdfs.log.jsonl`    | `PdfStore.record` (per attempt, fsynced)         | append-only attempt log; source of truth if `state.json` tears |
| `pdfs.errors.jsonl` | `PdfStore.write_errors_file`                     | derived; feeds `--retry-from` on the next run |
| `requests.db`       | `src.utils.request_log.RequestLog` (SQLite WAL)  | per-GET URL / status / latency / bytes |
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

- `scripts/fetch_pdfs.py` — routes through `pdf_driver.run_pdf_sweep`;
  writes the full institutional layout above.
- `scripts/reextract_unstructured.py` — **does not yet route through
  `pdf_driver`** (pre-Phase-A inlined loop). Currently only
  `run.log` (via `tee`) is produced. See the script's "Known gaps"
  section for the migration todo.
