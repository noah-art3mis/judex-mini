"""Poll a RunPod Serverless endpoint's worker / queue status.

Cheap status check that does NOT trigger a cold start — hits the
``/v2/{ep}/health`` endpoint, which RunPod returns near-instantly
with the current worker pool state and recent-jobs counters.

Run once::

    uv run python scripts/runpod_status.py

Run continuously (every 5s, until Ctrl-C)::

    uv run python scripts/runpod_status.py --watch

Useful for "is anything happening?" diagnostics when a smoke-test or
sweep is sitting blocked on a cold-start. The Logs tab on the
RunPod console is still the ground-truth view (this only sees what
RunPod's control plane reports), but ``--watch`` here gives you a
live counter without leaving the terminal.

Reads ``RUNPOD_API_KEY`` and ``RUNPOD_CHANDRA_ENDPOINT_ID`` from the
repo-root ``.env`` via python-dotenv. Never echoes the API key.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

import requests
from dotenv import load_dotenv

sys.stdout.reconfigure(line_buffering=True)


def _fetch_health(key: str, ep: str) -> tuple[int, dict]:
    url = f"https://api.runpod.ai/v2/{ep}/health"
    r = requests.get(
        url, headers={"Authorization": f"Bearer {key}"}, timeout=10,
    )
    try:
        return r.status_code, r.json() if r.ok else {"_raw": r.text[:300]}
    except ValueError:
        return r.status_code, {"_raw": r.text[:300]}


def _format_one(payload: dict) -> str:
    """Compact one-line summary for ``--watch`` mode.

    RunPod's /health typically returns:
      {"workers": {"idle": N, "running": N, "ready": N, "throttled": N},
       "jobs":    {"completed": N, "failed": N, "inProgress": N,
                   "inQueue": N, "retried": N}}
    Field names occasionally drift; we surface what's there and fall
    back to a raw dump if the shape is unrecognised.
    """
    w = payload.get("workers") or {}
    j = payload.get("jobs") or {}
    if not w and not j:
        return f"raw: {payload}"
    return (
        f"workers: idle={w.get('idle', '?')} running={w.get('running', '?')} "
        f"ready={w.get('ready', '?')} throttled={w.get('throttled', '?')}  |  "
        f"jobs: queue={j.get('inQueue', '?')} inProgress={j.get('inProgress', '?')} "
        f"completed={j.get('completed', '?')} failed={j.get('failed', '?')}"
    )


def _format_full(payload: dict) -> str:
    """Pretty multi-line dump for one-shot mode."""
    import json
    return json.dumps(payload, indent=2, sort_keys=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--watch", action="store_true",
                        help="poll every --interval seconds until Ctrl-C")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="seconds between polls in --watch mode (default: 5)")
    args = parser.parse_args()

    load_dotenv()
    key = os.environ.get("RUNPOD_API_KEY", "")
    ep = os.environ.get("RUNPOD_CHANDRA_ENDPOINT_ID", "")
    if not key or not ep:
        print("error: RUNPOD_API_KEY or RUNPOD_CHANDRA_ENDPOINT_ID not set in .env")
        sys.exit(1)

    print(f"endpoint: {ep}")

    if not args.watch:
        status, payload = _fetch_health(key, ep)
        print(f"http {status}")
        print(_format_full(payload))
        sys.exit(0 if status == 200 else 2)

    print(f"watching every {args.interval}s — Ctrl-C to stop\n")
    last_line = ""
    while True:
        try:
            status, payload = _fetch_health(key, ep)
        except requests.RequestException as exc:
            line = f"network error: {exc}"
        else:
            line = f"http {status}  {_format_one(payload)}" if status == 200 \
                else f"http {status}  {payload}"
        ts = datetime.now().strftime("%H:%M:%S")
        # Only redraw when content changes — keeps the scroll readable
        # during long cold-starts where state is mostly static.
        if line != last_line:
            print(f"[{ts}] {line}")
            last_line = line
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nstopped.")
            return


if __name__ == "__main__":
    main()
