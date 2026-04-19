#!/usr/bin/env bash
# Overnight chain monitor. Writes ONE timestamped line to ALERTS_FILE
# per detected problem, nothing on green. Tail ALERTS_FILE to watch.
#
# Self-expires after EXPIRY_DATE (silent no-op past then). Designed to
# be installed via crontab "13,43 * * * *".
#
# Checks:
#   1. Chain wrapper pid alive (cat chain.pid + kill -0)
#   2. Per-shard sweep.state.json status != "aborted"
#   3. Per-shard sweep.log.jsonl mtime within 30 min (only if chain alive)
#   4. New error_type values in sweep.errors.jsonl (vs alerts.seen-errors)

set -uo pipefail
cd "$(dirname "$0")/.."

EXPIRY_DATE="2026-04-26"
ROOT="runs/active/2026-04-19-overnight-t0123"
ALERTS_FILE="$ROOT/alerts.log"
SEEN_ERRORS_FILE="$ROOT/alerts.seen-errors"
TIERS=(2026 2025 2024 2023)
STALE_MIN=30

[[ "$(date +%F)" > "$EXPIRY_DATE" ]] && exit 0
[[ ! -d "$ROOT" ]] && exit 0

mkdir -p "$ROOT"
touch "$ALERTS_FILE" "$SEEN_ERRORS_FILE"

alert() {
    echo "[$(date -Iseconds)] $*" >> "$ALERTS_FILE"
}

CHAIN_PID_FILE="$ROOT/chain.pid"
CHAIN_ALIVE=0
if [[ -f "$CHAIN_PID_FILE" ]]; then
    CHAIN_PID=$(cat "$CHAIN_PID_FILE")
    if kill -0 "$CHAIN_PID" 2>/dev/null; then
        CHAIN_ALIVE=1
    fi
fi

if grep -q "OVERNIGHT DONE" "$ROOT/chain.log" 2>/dev/null; then
    grep -q "DONE_LOGGED" "$ALERTS_FILE" 2>/dev/null || alert "OVERNIGHT DONE — chain finished cleanly. (DONE_LOGGED)"
    exit 0
fi

if [[ -f "$CHAIN_PID_FILE" && "$CHAIN_ALIVE" -eq 0 ]]; then
    alert "chain wrapper pid $(cat "$CHAIN_PID_FILE") not alive but chain.log shows no OVERNIGHT DONE"
fi

NOW=$(date +%s)
for YEAR in "${TIERS[@]}"; do
    TIER_DIR="runs/active/2026-04-19-hc-${YEAR}"
    [[ ! -d "$TIER_DIR" ]] && continue

    for SHARD_DIR in "$TIER_DIR"/shard-*; do
        [[ ! -d "$SHARD_DIR" ]] && continue
        STATE="$SHARD_DIR/sweep.state.json"
        LOG="$SHARD_DIR/sweep.log.jsonl"
        ERRORS="$SHARD_DIR/sweep.errors.jsonl"

        if [[ -f "$STATE" ]]; then
            STATUS=$(grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' "$STATE" 2>/dev/null | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
            if [[ "$STATUS" == "aborted" ]]; then
                alert "tier=${YEAR} ${SHARD_DIR##*/}: status=aborted in sweep.state.json"
            fi
        fi

        if [[ "$CHAIN_ALIVE" -eq 1 && -f "$LOG" ]]; then
            MTIME=$(stat -c %Y "$LOG")
            AGE=$(( NOW - MTIME ))
            if [[ "$AGE" -gt $(( STALE_MIN * 60 )) ]]; then
                alert "tier=${YEAR} ${SHARD_DIR##*/}: sweep.log.jsonl stale (${AGE}s, >${STALE_MIN}m); chain alive — likely dead worker"
            fi
        fi

        if [[ -f "$ERRORS" ]]; then
            while IFS= read -r ETYPE; do
                [[ -z "$ETYPE" ]] && continue
                if ! grep -qxF "$ETYPE" "$SEEN_ERRORS_FILE"; then
                    echo "$ETYPE" >> "$SEEN_ERRORS_FILE"
                    alert "tier=${YEAR} ${SHARD_DIR##*/}: new error_type=${ETYPE}"
                fi
            done < <(grep -o '"error_type"[[:space:]]*:[[:space:]]*"[^"]*"' "$ERRORS" 2>/dev/null | sed 's/.*"\([^"]*\)"$/\1/' | sort -u)
        fi
    done
done

exit 0
