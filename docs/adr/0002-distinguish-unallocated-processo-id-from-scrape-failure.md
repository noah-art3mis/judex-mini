# ADR-0002: Distinguish unallocated processo_id from scrape failure

**Status**: Proposed (2026-05-01).

## Summary

A `(classe, processo_id)` pair that STF's portal never bound to an `incidente` is currently logged as `status="fail" + error_type="NoIncidente"` and lumped with real failures in `report.md` headlines — a 23%-of-input "failure rate" on a clean direct-IP sweep that is in fact a corpus-sparsity property. This ADR reframes the concept as a peer terminal status, names it **processo_id não alocado** in CONTEXT.md, and assigns `status="unallocated"` on the wire. Renames cascade through the CLI flag, the on-disk registry directory, and code identifiers; the HTTP-layer `NoIncidenteError` exception keeps its name.

## Context

A `varrer-processos` sweep over the live edge of HC 2026 (4,002 input pids) returned `ok=3099 fail=903`. All 903 "failures" share an identical signature — `status="fail"`, `error_type="NoIncidente"`, `http_status=200`, `body_head=""`, `filter_skip=true` — and are scattered (not contiguous) throughout the input range, ruling out "ran past the live edge." The pattern is: STF's `listarProcessos.asp` redirects with HTTP 200 + a Location header that lacks `incidente=<n>`, signalling that the processo_id was never allocated. Empty `body_head` is the high-confidence form of this signal; a non-empty body_head NoIncidente is ambiguous (could be a proxy soft-block returning a synthetic 200 with a different shape).

The concept is already implemented in five places under four overlapping names:

| Layer | Surface | Term |
|---|---|---|
| HTTP | `judex/scraping/scraper.py:104` | `NoIncidenteError` |
| Sweep record | `AttemptRecord.error_type` | `"NoIncidente"` |
| Regime | `judex/sweeps/shared.py:160` | `filter_skip=true` (excludes from WAF-pressure axis A; 2026-04-17 calibration fix) |
| Cross-sweep aggregation | `judex/utils/dead_ids.py`, `data/derived/dead-ids/` | "dead ID" |
| Input filter | `judex/cli.py --excluir-mortos` | "morto" |

CONTEXT.md does not name the concept at all. The report headline (`ok=N fail=M of total`) is the only layer where the lump is still visible to a human reading run output.

## Decision

Adopt **processo_id não alocado** (English alias on first use: *unallocated processo_id*) as the canonical CONTEXT.md term. Frame it as a *property of the input target*, discovered per-attempt during a sweep and confirmed across sweeps. Realise it as a peer terminal status to `ok` / `fail` / `error` on the per-attempt record (named `status="unallocated"` on the wire), preserving the existing single-log + atomic-state architecture rather than introducing a peer log for discoveries.

| Layer | Pre-change | Post-change |
|---|---|---|
| CONTEXT.md | (absent) | new entry **Processo_id não alocado** between **Numero_unico** and **Andamento** |
| Run-loop classification | `NoIncidenteError` → `status="fail"` (always) | empty `body_head` → `status="unallocated"`; non-empty → `status="fail"` + `error_type="NoIncidente"` (proxy-noise bucket) |
| Report headline | `ok=N fail=M of total` | `ok=N fail=M unallocated=K of total` |
| `sweep.errors.jsonl` | all non-ok records | `status ∈ {fail, error}` only |
| Per-sweep artifact | (none) | `<run_dir>/unallocated.candidates.txt` — one pid per line, derived from state |
| Cross-sweep registry | `data/derived/dead-ids/<classe>.txt` + `<classe>.candidates.tsv` | renamed → `data/derived/nao-alocados/<classe>.txt` + `<classe>.candidates.tsv` (same schema) |
| CLI flag | `--excluir-mortos` | `--excluir-nao-alocados` |
| Code module | `judex/utils/dead_ids.py` (`DeadObservation`, `load_dead_ids`, `write_dead_id_files`) | `judex/utils/unallocated_pids.py` (`UnallocatedObservation`, `load_unallocated_pids`, `write_unallocated_pid_files`) |
| Aggregator script | `scripts/aggregate_dead_ids.py` | `scripts/aggregate_unallocated_pids.py` |
| HTTP-layer exception | `NoIncidenteError` | unchanged (protocol-level technical name; layer below the discovery interpretation) |
| Aggregator predicate | `status=="fail" AND error_type=="NoIncidente" AND body_head==""` | `status=="unallocated"` |
| Warehouse | (no presence) | new `unallocated_pids` table — schema `(classe VARCHAR, processo_id INTEGER, n_observations INTEGER, n_empty_body INTEGER, confirmed BOOLEAN)` with `confirmed = (n_empty_body >= 2)`; sourced from `<classe>.candidates.tsv` per classe in scope |

Existing on-disk `sweep.state.json` records get a one-shot migration via `scripts/migrate_unallocated_status.py`: records with `error_type=="NoIncidente" AND body_head==""` flip from `status="fail"` to `status="unallocated"`. The aggregator only learns the new shape; no backwards-compat shim survives in code.

## Why

1. **Four overlapping terms across five layers cause real confusion.** Standardising on one canonical noun and demoting the others is the only way to keep CONTEXT.md, the CLI, code identifiers, and on-disk artifacts coherent. Reusing "morto"/"dead" was rejected because CONTEXT.md already uses "operationally dead" for a different concept (Numero_unico — DataJud integration) — the metaphor is taken.

2. **The "fail" label is wrong on the merits.** A 23% "fail rate" on a clean direct-IP sweep with zero 403s and zero 5xx reads as a reliability problem when it is in fact a corpus-sparsity property — already known to the regime detector (`filter_skip=true`) but not to the report headline. The fix is per-target framing, not per-attempt framing: the scraper *discovered* a property of the target, not a failure of the attempt.

3. **Body_head as the run-loop boundary preserves layer separation.** Empty body_head is STF's high-confidence "this number is unallocated" signal; non-empty body_head is ambiguous (proxy soft-block possible). Putting the boundary at the run-loop classifier — not at the aggregator — means the per-attempt status already encodes the discovery interpretation. `--retentar-de` then naturally retries proxy-noise NoIncidente records (`status="fail"` + `error_type="NoIncidente"`) and skips genuine unallocations (`status="unallocated"`), which is the correct behaviour: the former might succeed on a different IP; the latter never will.

4. **Soft-(b) over hard-(b) preserves replay invariants.** The store layer's atomic-write + replay (`recover_state_from_log`) is single-log-shaped; sharding launches one log per shard; signal handlers reason about one log. A peer log for unallocated discoveries (hard-(b)) would double the replay surface, complicate sharded merges, and require updating `judex probe` and `analisar-regimes` to read two streams — without delivering material benefit, since the discovery framing is fully recoverable from a single new status string plus the existing aggregator.

5. **`NoIncidenteError` keeps its name.** The HTTP-layer exception is the *protocol-level fact* ("STF responded without an incidente"). The per-target interpretation ("this processo_id is unallocated") depends on `body_head` and lives in the run loop's classifier. Renaming the exception would collapse those layers and force the HTTP layer to know about the empty-body invariant, which it cannot decide on its own.

## Consequences

- **`--retentar-de` no longer retries unallocated targets.** Confirmed-no-processo numbers leave `sweep.errors.jsonl`; retry semantics naturally skip them. The historical waste of re-attempting known-dead pids on every retry disappears.
- **Aggregator predicate simplifies to one field.** `judex/utils/unallocated_pids.py` drops the multi-condition filter; `status=="unallocated"` is the single predicate. The `≥ 2 independent observations` confirmation threshold is unchanged — the threshold defends against single-sweep proxy noise polluting the registry.
- **`report.md` headline gains a third bucket.** Existing tooling that greps for `ok=N fail=M of total` will need a one-line patch.
- **One-shot migration rewrites every existing `sweep.state.json` under `runs/`.** Atomic per-file rewrite; no dual-format support survives. Operators with archived sweep directories outside `runs/` are responsible for migrating those manually if they want re-aggregation to include them.
- **Warehouse rebuild reads a new source.** Adds ~8K rows from `<classe>.candidates.tsv`; no measurable rebuild-time impact. Coverage analysis (`docs/completion-tracker.md`) becomes SQL-native — `SELECT COUNT(*) FROM unallocated_pids WHERE classe='HC' AND confirmed` replaces `wc -l data/derived/dead-ids/HC.txt`.
- **Layered semantics are explicit.** Per-attempt observation (`status="unallocated"` or `status="fail" + error_type="NoIncidente"`) → per-sweep summary (`<run_dir>/unallocated.candidates.txt`) → cross-sweep confirmation (`<classe>.txt` + warehouse `unallocated_pids` table). Four tiers, each with its own predicate, each addressable in isolation.
- **Path B accepts rename churn for terminological precision.** The trade-off was deliberate: keeping `morto`/`dead-ids/` (Path A) was zero-cost but left the metaphor colliding with Numero_unico's "operationally dead" usage. Path B pays the rename once and unifies on the literal term.
