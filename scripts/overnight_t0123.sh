#!/usr/bin/env bash
# Sequentially run year-priority backfill tiers 0 → 3 (HCs).
# Each tier launches via launch_hc_year_sharded.sh (8 shards on disjoint
# proxy pools); we block on its shards.pids before starting the next.
#
# Plows through regardless of per-tier ok-rate (option (a) per
# 2026-04-19 overnight plan). Morning audit catches anything bad.
#
# Usage (detached):
#   nohup ./scripts/overnight_t0123.sh > runs/active/$(date +%F)-overnight-t0123/chain-stdout.log 2>&1 & disown
#   echo $! > runs/active/$(date +%F)-overnight-t0123/chain.pid

set -uo pipefail
cd "$(dirname "$0")/.."

DATE=$(date +%Y-%m-%d)
ROOT="runs/active/${DATE}-overnight-t0123"
mkdir -p "$ROOT"
LOG="$ROOT/chain.log"
log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }

run_tier() {
    local YEAR=$1
    local TIER_ROOT="runs/active/${DATE}-hc-${YEAR}"
    local PIDS_FILE="${TIER_ROOT}/shards.pids"

    log "=== tier ${YEAR} starting ==="
    ./scripts/launch_hc_year_sharded.sh "$YEAR" >> "$LOG" 2>&1
    local LAUNCH_RC=$?
    if [[ ! -f "$PIDS_FILE" ]]; then
        log "tier ${YEAR}: no shards.pids found at ${PIDS_FILE} (launcher rc=${LAUNCH_RC}); skipping wait"
        return 0
    fi

    local N=$(wc -l < "$PIDS_FILE")
    log "tier ${YEAR}: waiting on ${N} shard PIDs from ${PIDS_FILE}"
    while read -r PID; do
        [[ -z "$PID" ]] && continue
        tail --pid="$PID" -f /dev/null
        log "tier ${YEAR}: pid ${PID} exited"
    done < "$PIDS_FILE"
    log "=== tier ${YEAR} all shards exited ==="
}

log "overnight chain starting; pid $$; tiers = 2026 2025 2024 2023"
run_tier 2026
run_tier 2025
run_tier 2024
run_tier 2023
log "OVERNIGHT DONE"
