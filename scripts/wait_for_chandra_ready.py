"""Block until the RunPod Chandra endpoint has a stable ready worker.

Polls ``/v2/{ep}/health`` every 10 s and watches the worker pool:

- Exit 0 (success) once ``ready >= 1`` and ``unhealthy == 0`` for two
  consecutive polls (avoids declaring victory on a transient flicker).
- Exit 1 (failure) if ``unhealthy >= 1`` for five consecutive polls
  AND zero workers ever reach ready — workers are still crashing on
  startup, the env-var fix didn't land, paste the latest logs.
- Exit 2 (timeout) after ``--max-wait`` seconds (default 900 = 15 min).

Each line of output is a one-shot summary of the current state, so
``cat <output_file>`` shows the full transition history of the pool
during the wait.

Usage::

    uv run python scripts/wait_for_chandra_ready.py
    uv run python scripts/wait_for_chandra_ready.py --max-wait 1200
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


def _poll(key: str, ep: str) -> tuple[int, dict, dict]:
    r = requests.get(
        f"https://api.runpod.ai/v2/{ep}/health",
        headers={"Authorization": f"Bearer {key}"},
        timeout=10,
    )
    payload = r.json() if r.ok else {"_raw": r.text[:200]}
    return r.status_code, payload.get("workers") or {}, payload.get("jobs") or {}


def _format(workers: dict, jobs: dict) -> str:
    return (
        f"workers: ready={workers.get('ready', '?')} "
        f"running={workers.get('running', '?')} "
        f"idle={workers.get('idle', '?')} "
        f"throttled={workers.get('throttled', '?')} "
        f"unhealthy={workers.get('unhealthy', '?')} "
        f"init={workers.get('initializing', '?')}"
        f"  |  jobs: queue={jobs.get('inQueue', '?')} "
        f"inProgress={jobs.get('inProgress', '?')} "
        f"completed={jobs.get('completed', '?')} "
        f"failed={jobs.get('failed', '?')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--max-wait", type=int, default=900,
                        help="seconds before giving up (default 900 = 15 min)")
    parser.add_argument("--interval", type=int, default=10,
                        help="seconds between polls (default 10)")
    args = parser.parse_args()

    load_dotenv()
    key = os.environ.get("RUNPOD_API_KEY", "")
    ep = os.environ.get("RUNPOD_CHANDRA_ENDPOINT_ID", "")
    if not key or not ep:
        print("error: RUNPOD_API_KEY or RUNPOD_CHANDRA_ENDPOINT_ID not set")
        sys.exit(1)

    print(f"endpoint: {ep}")
    print(f"polling every {args.interval}s for up to {args.max_wait}s\n")

    deadline = time.monotonic() + args.max_wait
    consec_ready = 0  # ready≥1 AND unhealthy==0
    consec_unhealthy = 0  # unhealthy≥1 AND ready==0
    last_line = ""
    ever_saw_ready = False

    while time.monotonic() < deadline:
        try:
            status, workers, jobs = _poll(key, ep)
        except requests.RequestException as exc:
            line = f"network error: {exc}"
            workers, jobs = {}, {}
        else:
            if status != 200:
                line = f"http {status}"
            else:
                line = _format(workers, jobs)
        ts = datetime.now().strftime("%H:%M:%S")
        if line != last_line:
            print(f"[{ts}] {line}")
            last_line = line

        ready = int(workers.get("ready", 0) or 0)
        unhealthy = int(workers.get("unhealthy", 0) or 0)
        if ready >= 1:
            ever_saw_ready = True

        if ready >= 1 and unhealthy == 0:
            consec_ready += 1
            consec_unhealthy = 0
        elif unhealthy >= 1 and ready == 0:
            consec_unhealthy += 1
            consec_ready = 0
        else:
            consec_ready = 0
            consec_unhealthy = 0

        if consec_ready >= 2:
            print(f"\n✓ stable ready state — endpoint is serving")
            sys.exit(0)
        if consec_unhealthy >= 5 and not ever_saw_ready:
            print(f"\n✗ workers crashing repeatedly — env-var fix not landing")
            print("  pull fresh container logs and check for the new failure mode")
            sys.exit(1)

        time.sleep(args.interval)

    print(f"\n✗ timed out after {args.max_wait}s without stable ready state")
    sys.exit(2)


if __name__ == "__main__":
    main()
