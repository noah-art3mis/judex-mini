# Recovery patterns — what to do with errored / lost / unallocated targets

A sweep ends with a residual: rows that didn't reach `ok`. The
*per-row* recovery decision is encoded in code; this doc covers the
stuff a per-row function can't answer — multi-step scenarios,
verification beyond `ok` count, and the gaps a future cleanup command
would close.

## Source of truth — `error_triage`

[`judex/sweeps/error_triage.py`](../judex/sweeps/error_triage.py) is
the single source of truth, in two layers:

1. `classify_error(stage, row) -> Kind` returns one of `transient` /
   `terminal` / `cross_stage` / `ok`. Read the module docstring for
   what each kind means and the conservative-default policy.
2. `recovery_recipe(stage, row) -> Recipe(action, summary,
   command_hint)` returns the operator action for a row — the
   table-driven mapping that previously lived as Markdown tables in
   this file. `RECOVERY_RECIPES` (in the same module) is the data
   table; `tests/unit/test_error_triage.py` pins coverage of every
   `(stage, kind)` cell and the two extrair status overrides
   (`empty` → `switch_provider`, `unknown_type` → `refetch_bytes`).

Want the recipe for a specific row? Don't read a Markdown table —
import the function:

```python
from judex.sweeps.error_triage import recovery_recipe
recipe = recovery_recipe("extrair", {"status": "empty", "error": "pypdf returned 0 chars"})
print(recipe.action, recipe.summary, recipe.command_hint, sep="\n")
```

Every replay surface in the codebase
(`targets_for_replay`, `judex executar --retomar`, `--retentar-de
…/errors.jsonl`) goes through `classify_error`. **Unknown rows default
to `terminal`** — mis-classifying transient as terminal is louder and
safer than the inverse.

## Multi-step recovery scenarios

The single-row recipes compose into a few standard operator playbooks.
These can't all live as `command_hint` strings because they involve
shell pipelines, multiple commands, or knowledge of the whole run
directory rather than one row.

### A. "I just finished a sweep; clean up the residual"

```bash
# Unified pipeline (recommended for new sweeps)
uv run judex executar --retomar --saida runs/active/<label>/

# Legacy three-command path
uv run judex varrer-processos --retentar-de runs/.../sweep.errors.jsonl --saida …
uv run judex baixar-pecas    --retentar-de runs/.../pdfs.errors.jsonl  --saida …
uv run judex extrair-pecas   --retentar-de runs/.../pdfs.errors.jsonl  --saida …
```

`--retomar` (unified) and `--retentar-de` (legacy) both filter through
`error_triage.classify_error`, so terminal rows are dropped automatically
— the loop converges.

### B. "Empty extractions on a year I already ran"

The `recovery_recipe` for an extrair `empty` row already returns the
right command shape, but you need to build the CSV first:

```bash
# Build a CSV of the empty bucket
jq -r 'select(.status == "empty") | "\(.classe),\(.processo)"' \
   runs/active/<label>/pdfs.log.jsonl \
   | sort -u > /tmp/empty.csv

# Re-extract with a beefier provider (matches recipe.command_hint)
uv run judex extrair-pecas --csv /tmp/empty.csv \
   --provedor chandra --forcar --saida runs/active/<label>-empty-recover/
```

`--forcar` overrides the `<sha1>.extractor` sidecar guard so the new
provider's output replaces the empty pypdf result.

### C. "Cross-stage residual — text failed because bytes are missing"

```bash
# Pull no_bytes targets
jq -r 'select(.status == "no_bytes") | .url' \
   runs/active/<label>/pdfs.log.jsonl > /tmp/no_bytes_urls.txt

# Re-fetch bytes (re-uses the same CSV scoping)
uv run judex baixar-pecas --csv runs/active/<label>/cases.csv --retomar \
   --saida runs/active/<label>/

# Then re-extract
uv run judex extrair-pecas --csv runs/active/<label>/cases.csv --retomar \
   --saida runs/active/<label>/
```

### D. "Confirm an `unallocated` is real, or check stragglers"

`unallocated` is terminal — there's nothing to recover. To audit the
list, look at `data/derived/nao-alocados/<CLASSE>.txt` (one pid per
line). To **un**-mark one (e.g. a previously-unallocated number was
later assigned by STF), drop the line from that file and re-run
`varrer-processos` against the range.

### E. "Sweep was killed mid-run; resume from where it stopped"

```bash
# Unified
uv run judex executar --retomar --saida runs/active/<label>/

# Legacy (per stage that was in flight)
uv run judex <stage> --retomar --saida runs/active/<label>/
```

`--retomar` reads the state file, drops rows already at `ok`, re-queues
everything else (subject to cap=2 in the unified path; legacy is
unbounded — this is a known gap, see § Gaps).

## Verification — don't trust `ok` blindly

A `report.md` `ok` count means the call returned without raising.
For text quality, spot-check:

```bash
# 5 random sha1s from the run
shuf -n 5 <(awk -F'"url":"' '/status":"ok"/ {print $2}' \
            runs/active/<label>/pdfs.log.jsonl | cut -d'"' -f1)

# For each: decompress and inspect
for sha in $(echo "$urls" | python3 -c \
   "import sys,hashlib; [print(hashlib.sha1(u.encode()).hexdigest()) for u in sys.stdin.read().split()]"); do
  echo "=== $sha ==="
  gzip -dc data/derived/pecas-texto/$sha.txt.gz | head -20
done
```

Look for: actual sentences, no `Ã§` / `Ã£` corruption, length plausible
for the document type. If a meaningful fraction look bad, treat that as
an `empty`-class residual and recover via Scenario B with a different
provider.

## `judex limpar <run_dir>` — one-command residual closer

**As of 2026-05-03, Gap #1 is closed.** `judex limpar <run_dir>` walks
a finished `judex executar` run dir (mono *or* sharded — auto-detects),
classifies every `executar.errors.jsonl` row via
`classify_unified_error`, partitions by bucket, and (under `--apply`)
dispatches one detached `judex executar --retentar-de` per shard with
at least one transient row. Spec:
[`docs/superpowers/specs/2026-05-03-judex-limpar.md`](superpowers/specs/2026-05-03-judex-limpar.md);
implementation: [`judex/sweeps/limpar.py`](../judex/sweeps/limpar.py).

```bash
# Default: dry-run. Prints `would-recover: …` + per-shard plan, exits 0.
uv run judex limpar runs/active/hc2020-sharded/

# Actually dispatch the recoveries (16 detached children for sharded).
uv run judex limpar runs/active/hc2020-sharded/ --apply --nao-perguntar
```

Summary line shape:

```
recovered: 532 transient · 0 cross_stage · 0 provider_switched · 1036 confirmed_unallocated · 826 terminal_dropped
```

Auto-dispatched in v1: only the **transient** bucket (REPLAY).
Cross-stage and provider-switch buckets are counted and surfaced but
need manual escalation (`baixar-pecas` for `no_bytes`,
`extrair-pecas --provedor chandra --forcar` for `empty`) — same
operator action as Scenarios B and C above. Promoting these to
auto-dispatch is a follow-up.

PIDs go to `<run_dir>/limpar.pids`; per-shard logs go to
`<shard>/limpar.log`. Monitor with `judex acompanhar <run_dir>` or
`pgrep -af 'judex executar'`.

## Remaining gaps

1. **Cap=2 lives only in the unified pipeline.** Legacy `--retentar-de`
   loops are unbounded; an operator running a legacy chain in a tight
   loop can burn retry budget on a slowly-shrinking residual that's
   actually saturated. `limpar` doesn't fix this — it dispatches
   `judex executar --retentar-de` (which honors cap=2) but doesn't
   touch the legacy `varrer-processos` / `baixar-pecas` /
   `extrair-pecas` paths. Formally retiring the legacy path closes
   this (ADR-0005 slice 6).
2. **Empty-bucket re-extraction is still manual.** `limpar` counts the
   `provider_switch` bucket but doesn't auto-dispatch — the operator
   still has to build a CSV by hand and run `extrair-pecas --forcar`.
   v2 would promote this once `executar` learns a flag analogous to
   `--retentar-de` but inverted (filter-to-empty + force).
3. **Spot-check is not automated.** No tool diffs `ok`-count against
   actual text plausibility. The 2026-04-30 HC 2024 anomaly (text 80%
   vs 97-99% on adjacent years) would have surfaced earlier with a
   cheap "median chars per `DECISÃO` document" sanity check.
4. **Cross-stage residual is reported but not auto-dispatched.**
   `limpar` surfaces the `refetch_upstream` count but doesn't fan a
   `baixar-pecas` retry. v2 would auto-dispatch since the cap=2 chain
   has already exited on a finished run.

## See also

- [`docs/adr/0002-distinguish-unallocated-processo-id-from-scrape-failure.md`](adr/0002-distinguish-unallocated-processo-id-from-scrape-failure.md) — `unallocated` semantics
- [`docs/adr/0004-coleta-orchestrator-with-status-aware-retry.md`](adr/0004-coleta-orchestrator-with-status-aware-retry.md) — `error_triage` classifier (now superseded but classifier inherited verbatim)
- [`docs/adr/0005-unified-pipeline.md`](adr/0005-unified-pipeline.md) — `judex executar`, cap=2 retry, per-pool transient gate
- [`judex/sweeps/error_triage.py`](../judex/sweeps/error_triage.py) — code (one source of truth: `classify_error` + `recovery_recipe` + `RECOVERY_RECIPES` table)
- [`tests/unit/test_error_triage.py`](../tests/unit/test_error_triage.py) — pinned `(status, error_substring)` coverage from real run dirs and the 12-cell `(stage, kind)` recipe table
