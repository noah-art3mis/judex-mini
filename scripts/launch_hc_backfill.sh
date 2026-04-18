#!/usr/bin/env bash
# Autonomous launcher for the HC full backfill.
#
# 1. Waits for the in-flight Z sweep (label hc_258105_259104) to finish.
# 2. Sleeps 120 s so the WAF counter can decay.
# 3. Re-merges all prior HC sweep states into the backfill dir so --resume
#    skips the ~10.8k already-ok HCs.
# 4. Launches the full backfill (descending IDs, newest first) as a
#    replacement process via exec, so pgrep -f hc_full_backfill finds it.
#
# Intended to be run itself via nohup ... & disown so it survives the
# parent shell closing.

set -uo pipefail
cd "$(dirname "$0")/.."

OUT=docs/sweep-results/2026-04-17-hc-full-backfill
LOG="$OUT/launcher.log"
DRIVER_LOG="$OUT/driver.log"
mkdir -p "$OUT" data/output/hc_backfill

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }

log "launcher starting; pid $$"

log "waiting for Z sweep to finish (label: hc_258105_259104)"
while pgrep -f "hc_258105_259104" >/dev/null 2>&1; do
    sleep 30
done
log "Z ended; WAF cool-down 120s"
sleep 120

log "checking whether state merge is needed (idempotency guard)"
PYTHONPATH=. uv run python - <<'PY' >> "$LOG" 2>&1
import json
from pathlib import Path

out = Path("docs/sweep-results/2026-04-17-hc-full-backfill/sweep.state.json")
if out.exists():
    existing = json.loads(out.read_text())
    if len(existing) > 0:
        print(f"state already has {len(existing)} records — skipping merge (idempotent relaunch)")
        raise SystemExit(0)

# First-run bootstrap: merge ok HC entries from every prior sweep
merged = {}
for sf in sorted(Path("docs/sweep-results").glob("*/sweep.state.json")):
    if "hc-full-backfill" in str(sf):
        continue
    try:
        data = json.loads(sf.read_text())
    except Exception as e:
        print(f"skip {sf}: {e}")
        continue
    for k, v in data.items():
        if v.get("classe") == "HC" and v.get("status") == "ok":
            merged[k] = v

out.write_text(json.dumps(merged, indent=2))
print(f"merged {len(merged)} ok HC entries into {out}")
PY

log "launching backfill (exec — driver replaces this shell)"
exec env PYTHONPATH=. uv run python scripts/run_sweep.py \
    --csv tests/sweep/hc_all_desc.csv \
    --label hc_full_backfill \
    --out "$OUT" \
    --items-dir data/output/hc_backfill \
    --proxy-pool "$PWD/proxies.txt" \
    --resume \
    >> "$DRIVER_LOG" 2>&1
