#!/usr/bin/env bash
# Launch 8 concurrent HC shards for a single target year, each on its
# own disjoint proxy pool and a disjoint slice of the year's gap CSV.
#
# Pipeline:
#   1. Generate the gap CSV for YYYY (IDs in year range NOT already on disk).
#   2. Shard the gap CSV 8-way.
#   3. Launch 8 run_sweep.py workers via nohup, each with its own --out,
#      --csv, --proxy-pool. All shards share --items-dir and the PDF cache.
#   4. Record PIDs to <out-root>/shards.pids for scripted stop/resume.
#
# Unlike launch_hc_backfill_sharded.sh, there is no state-seeding step —
# the gap CSV excludes captured IDs by construction, so every row in
# the CSV is work to do.
#
# Idempotent: re-running leaves any shard whose sweep.state.json already
# has entries untouched (handled by run_sweep.py's --resume).
#
# Usage (from repo root):
#   nohup ./scripts/launch_hc_year_sharded.sh 2026 > launcher-hc-2026.log 2>&1 & disown

set -uo pipefail
cd "$(dirname "$0")/.."

YEAR=${1:?Usage: $0 YYYY}

DATE=$(date +%Y-%m-%d)
ROOT="runs/active/${DATE}-hc-${YEAR}"
CSV="tests/sweep/hc_${YEAR}_gap.csv"
SHARD_CSV_DIR="tests/sweep/shards/hc_${YEAR}"

PROXY_FILES=(
    config/proxies.a.txt config/proxies.b.txt config/proxies.c.txt config/proxies.d.txt
    config/proxies.e.txt config/proxies.f.txt config/proxies.g.txt config/proxies.h.txt
)
N=${#PROXY_FILES[@]}

mkdir -p "$ROOT" data/cases/HC "$SHARD_CSV_DIR"
LOG="$ROOT/launcher.log"
log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }

log "year-sharded launcher starting; pid $$; year=$YEAR N=$N"

log "step 1/3: generate gap CSV for $YEAR → $CSV"
if [[ -f "$CSV" ]]; then
    log "  $CSV already exists — leaving untouched"
else
    PYTHONPATH=. uv run python scripts/generate_hc_year_gap_csv.py \
        --year "$YEAR" --out "$CSV" 2>&1 | tee -a "$LOG"
fi

GAP_ROWS=$(($(wc -l < "$CSV") - 1))
if [[ "$GAP_ROWS" -le 0 ]]; then
    log "gap CSV is empty (year already fully captured) — nothing to do"
    exit 0
fi
log "  $GAP_ROWS rows in gap CSV"

log "step 2/3: shard gap CSV into $N range-partitions"
PYTHONPATH=. uv run python scripts/shard_csv.py \
    --csv "$CSV" --shards "$N" --out-dir "$SHARD_CSV_DIR" 2>&1 | tee -a "$LOG"

log "step 3/3: launch $N shard workers"
: > "$ROOT/shards.pids"
for i in $(seq 0 $((N - 1))); do
    SHARD_DIR="$ROOT/shard-$i"
    SHARD_CSV="$SHARD_CSV_DIR/hc_${YEAR}_gap.shard.$i.csv"
    PROXY="$PWD/${PROXY_FILES[$i]}"
    LABEL="hc_${YEAR}_shard_$i"
    DRIVER_LOG="$SHARD_DIR/driver.log"
    mkdir -p "$SHARD_DIR"

    if pgrep -f "$LABEL" >/dev/null 2>&1; then
        log "  shard-$i: already running ($LABEL) — skipping"
        continue
    fi

    nohup env PYTHONPATH=. uv run python scripts/run_sweep.py \
        --csv "$SHARD_CSV" \
        --label "$LABEL" \
        --out "$SHARD_DIR" \
        --items-dir data/cases/HC \
        --proxy-pool "$PROXY" \
        --resume \
        >> "$DRIVER_LOG" 2>&1 &
    PID=$!
    echo "$PID" >> "$ROOT/shards.pids"
    log "  shard-$i: pid=$PID csv=$SHARD_CSV proxy=${PROXY_FILES[$i]} log=$DRIVER_LOG"
done

log "done; pids at $ROOT/shards.pids"
log "probe: PYTHONPATH=. uv run python scripts/probe_sharded.py --out-root $ROOT"
log "stop:  xargs -a $ROOT/shards.pids kill -TERM"
