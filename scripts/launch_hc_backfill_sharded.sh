#!/usr/bin/env bash
# Launch N concurrent HC backfill shards, each with its own disjoint proxy
# pool and a disjoint slice of hc_all_desc.csv.
#
# Pipeline:
#   1. Shard the master CSV into N range-partitions (tests/sweep/shards/).
#   2. Seed each shard's sweep.state.json with the `ok` records from the
#      existing monolithic backfill, partitioned by the same rule — so no
#      already-done HC is re-fetched.
#   3. Launch N run_sweep.py workers via nohup, each with its own --out,
#      --csv, --proxy-pool. All shards share --items-dir (per-process JSON
#      filenames are unique across disjoint CSVs) and the data/raw/pecas/ cache
#      (atomic writes land on 2026-04-17 via peca_cache._atomic_write).
#   4. Record all PIDs to <out-root>/shards.pids for scripted stop/resume.
#
# Idempotent: re-running after a partial launch leaves any shard whose
# sweep.state.json already has entries untouched. Safe to invoke repeatedly.
#
# Usage (from repo root):
#   nohup ./scripts/launch_hc_backfill_sharded.sh > launcher-sharded.log 2>&1 & disown

set -uo pipefail
cd "$(dirname "$0")/.."

DATE="2026-04-17"
ROOT="runs/active/${DATE}-hc-full-backfill-sharded"
SRC_CSV="tests/sweep/hc_all_desc.csv"
# Seed from the archived monolithic sweep's final state (all ok records
# up to the pre-shard SIGTERM, 13 943 entries).
SRC_STATE="runs/archive/${DATE}-hc-full-backfill/sweep.state.json"
SHARD_CSV_DIR="tests/sweep/shards"

# One proxy file per shard — order matters, shard i uses PROXY_FILES[i].
PROXY_FILES=(config/proxies.a.txt config/proxies.b.txt config/proxies.c.txt config/proxies.d.txt)
N=${#PROXY_FILES[@]}

mkdir -p "$ROOT" data/source/processos/HC "$SHARD_CSV_DIR"
LOG="$ROOT/launcher.log"
log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }

log "sharded launcher starting; pid $$; N=$N shards"

log "step 1/4: shard CSV into $N range-partitions"
PYTHONPATH=. uv run python scripts/shard_csv.py \
    --csv "$SRC_CSV" --shards "$N" --out-dir "$SHARD_CSV_DIR" | tee -a "$LOG"

log "step 2/4: seed each shard's sweep.state.json from $SRC_STATE"
PYTHONPATH=. SRC_CSV="$SRC_CSV" SRC_STATE="$SRC_STATE" ROOT="$ROOT" N="$N" \
    uv run python - <<'PY' 2>&1 | tee -a "$LOG"
import csv, json, os
from pathlib import Path

src_csv = Path(os.environ["SRC_CSV"])
src_state = Path(os.environ["SRC_STATE"])
root = Path(os.environ["ROOT"])
N = int(os.environ["N"])

with src_csv.open() as f:
    rd = csv.reader(f)
    header = next(rd)
    rows = list(rd)
n = len(rows)

# Mirror the range-partition rule in scripts/shard_csv.py so every
# (classe, processo) maps to the same shard index here as it does there.
shard_of: dict[tuple[str, int], int] = {}
for i, (classe, proc) in enumerate(rows):
    shard_of[(classe, int(proc))] = (i * N) // n

state = json.loads(src_state.read_text()) if src_state.exists() else {}
per_shard: dict[int, dict] = {i: {} for i in range(N)}
for k, v in state.items():
    if not isinstance(v, dict) or v.get("status") != "ok":
        continue
    key = (v.get("classe"), v.get("processo"))
    idx = shard_of.get(key)
    if idx is None:
        continue
    per_shard[idx][k] = v

for i in range(N):
    out = root / f"shard-{i}"
    out.mkdir(parents=True, exist_ok=True)
    sf = out / "sweep.state.json"
    if sf.exists():
        cur = json.loads(sf.read_text())
        if cur:
            print(f"shard-{i}: state already has {len(cur)} records — leaving untouched")
            continue
    sf.write_text(json.dumps(per_shard[i], indent=2))
    print(f"shard-{i}: seeded {len(per_shard[i])} ok records from monolithic sweep")
PY

log "step 3/4: launch $N shard workers"
: > "$ROOT/shards.pids"
for i in $(seq 0 $((N - 1))); do
    SHARD_DIR="$ROOT/shard-$i"
    CSV="$SHARD_CSV_DIR/hc_all_desc.shard.$i.csv"
    PROXY="$PWD/${PROXY_FILES[$i]}"
    LABEL="hc_full_backfill_shard_$i"
    DRIVER_LOG="$SHARD_DIR/driver.log"
    mkdir -p "$SHARD_DIR"

    if pgrep -f "$LABEL" >/dev/null 2>&1; then
        log "  shard-$i: already running — skipping"
        continue
    fi

    nohup env PYTHONPATH=. uv run python scripts/run_sweep.py \
        --csv "$CSV" \
        --label "$LABEL" \
        --out "$SHARD_DIR" \
        --items-dir data/source/processos/HC \
        --proxy-pool "$PROXY" \
        --resume \
        >> "$DRIVER_LOG" 2>&1 &
    PID=$!
    echo "$PID" >> "$ROOT/shards.pids"
    log "  shard-$i: pid=$PID csv=$CSV proxy=${PROXY_FILES[$i]} log=$DRIVER_LOG"
done

log "step 4/4: done; pids at $ROOT/shards.pids"
log "probe: PYTHONPATH=. uv run python scripts/probe_sharded.py --out-root $ROOT"
log "stop:  xargs -a $ROOT/shards.pids kill -TERM"
