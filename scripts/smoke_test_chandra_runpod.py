"""Smoke-test the chandra_runpod provider's wiring before any bulk run.

Run with:

    uv run python scripts/smoke_test_chandra_runpod.py

What it checks, in order:

1. ``RUNPOD_API_KEY`` and ``RUNPOD_CHANDRA_ENDPOINT_ID`` are set in env
   (loaded via python-dotenv from the repo-root ``.env``).
2a. ``GET /v2/{ep}/health`` — fast endpoint-exists / auth-correct check.
2b. ``POST /v2/{ep}/openai/v1/chat/completions`` — text-only ping
    that exercises the OpenAI proxy (the route ``chandra_runpod.py``
    uses). 600s timeout — first ever call on a fresh endpoint can
    take 5-10 min while RunPod pulls the image, downloads weights,
    and boots vLLM.
3. (Optional) End-to-end through the provider against a real cached
   PDF, if one is supplied via ``--pdf <sha1_or_path>``.

Stdout is force-flushed on every line (via ``sys.stdout.reconfigure``)
so progress is visible in real time when output is captured to a
file — Python's default block-buffering on non-TTY stdout would
otherwise hide the early prints behind the long HTTP call.

The script never prints the API key value — only its length and the
first 4 characters, to make "wrong .env loaded" diagnosable without
exposing the secret.

Exit codes:
- 0: all checks pass
- 1: env vars missing
- 2: endpoint probe failed (4xx/5xx, timeout, network error)
- 3: end-to-end provider call failed
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# Force line-buffered stdout so "what's happening" is visible in real
# time even when output is captured to a file (block-buffered by default).
sys.stdout.reconfigure(line_buffering=True)


def check_env() -> tuple[str, str]:
    load_dotenv()
    key = os.environ.get("RUNPOD_API_KEY", "")
    ep = os.environ.get("RUNPOD_CHANDRA_ENDPOINT_ID", "")
    print("=== 1. env vars ===")
    print(f"  RUNPOD_API_KEY              set={bool(key)}  len={len(key)}  prefix={key[:4]!r}")
    print(f"  RUNPOD_CHANDRA_ENDPOINT_ID  set={bool(ep)}   value={ep!r}")
    if not key or not ep:
        print("  ✗ missing one or both — populate .env and retry")
        sys.exit(1)
    print("  ✓ both set")
    return key, ep


def probe_health(key: str, ep: str) -> None:
    print("\n=== 2a. /health pre-check (fast) ===")
    url = f"https://api.runpod.ai/v2/{ep}/health"
    print(f"  GET {url}")
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"  ✗ network error: {exc}")
        sys.exit(2)
    print(f"  status: {r.status_code}")
    print(f"  body:   {r.text[:400]}")
    if r.status_code == 404:
        print("  ✗ endpoint not found — verify RUNPOD_CHANDRA_ENDPOINT_ID")
        sys.exit(2)
    if r.status_code in (401, 403):
        print("  ✗ auth failed — verify RUNPOD_API_KEY")
        sys.exit(2)
    if r.status_code != 200:
        print("  ✗ unexpected status — see body above")
        sys.exit(2)
    print("  ✓ endpoint exists and authed")


def probe_run_endpoint(key: str, ep: str) -> None:
    """Submit a tiny text-only job via /run + /status, the canonical
    RunPod worker-vllm async path. Confirms an end-to-end loop:
    submit accepted, worker picks up, response returned, output
    envelope parses. This is the path ``chandra_runpod.py`` uses;
    the OpenAI proxy at ``/openai/v1/...`` returned 500 on our
    deployed worker-vllm image so we never use it."""
    print("\n=== 2b. /run + /status text-only ping ===")
    base = f"https://api.runpod.ai/v2/{ep}"
    print(f"  POST {base}/run")
    try:
        sub = requests.post(
            f"{base}/run",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"input": {
                "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
                "max_tokens": 8,
                "temperature": 0.0,
            }},
            timeout=30,
        )
    except requests.RequestException as exc:
        print(f"  ✗ submit network error: {exc}")
        sys.exit(2)
    print(f"  submit status: {sub.status_code}  body: {sub.text[:200]}")
    if sub.status_code != 200:
        sys.exit(2)
    job_id = sub.json().get("id")
    if not job_id:
        print("  ✗ submit returned no job id")
        sys.exit(2)
    print(f"  job_id: {job_id}")

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        s = requests.get(
            f"{base}/status/{job_id}",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        )
        if not s.ok:
            print(f"  ✗ poll status {s.status_code}: {s.text[:200]}")
            sys.exit(2)
        payload = s.json() or {}
        status = (payload.get("status") or "").upper()
        print(f"  poll: status={status}")
        if status == "COMPLETED":
            from judex.scraping.ocr import chandra_runpod as cr
            text = cr._extract_text(payload.get("output"))
            print(f"  ✓ completed — extracted text: {text!r}")
            return
        if status in ("FAILED", "CANCELLED", "TIMED_OUT"):
            print(f"  ✗ job ended {status}: {payload}")
            sys.exit(2)
        time.sleep(5)
    print("  ✗ poll deadline exceeded (180s) without terminal status")
    sys.exit(2)


def probe_provider_end_to_end(pdf_arg: str) -> None:
    print("\n=== 3. End-to-end provider call ===")
    pdf_bytes = _resolve_pdf(pdf_arg)
    print(f"  PDF size: {len(pdf_bytes):,} bytes")

    from judex.scraping.ocr import OCRConfig
    from judex.scraping.ocr import chandra_runpod as cr

    cfg = OCRConfig(
        provider="chandra_runpod",
        api_key=os.environ["RUNPOD_API_KEY"],
        timeout=600,
    )
    try:
        result = cr.extract(pdf_bytes, config=cfg)
    except Exception as exc:
        print(f"  ✗ provider raised: {type(exc).__name__}: {exc}")
        sys.exit(3)

    print(f"  pages_processed: {result.pages_processed}")
    print(f"  text length:     {len(result.text):,} chars")
    print(f"  first 300 chars: {result.text[:300]!r}")
    print("  ✓ end-to-end OK")


def _resolve_pdf(arg: str) -> bytes:
    """Accept either a SHA1 (looked up under data/raw/pecas/) or a path."""
    p = Path(arg)
    if p.exists():
        return p.read_bytes()

    sha1 = arg.strip()
    if len(sha1) == 40 and all(c in "0123456789abcdef" for c in sha1.lower()):
        candidate = Path("data/raw/pecas") / f"{sha1}.pdf.gz"
        if candidate.exists():
            import gzip
            return gzip.decompress(candidate.read_bytes())

    raise SystemExit(f"--pdf {arg!r}: not a path and not a known cached sha1")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--pdf",
        help="(optional) path to a PDF or a sha1 from data/raw/pecas/ "
             "to also exercise end-to-end through the provider",
    )
    args = parser.parse_args()

    key, ep = check_env()
    probe_health(key, ep)
    probe_run_endpoint(key, ep)
    if args.pdf:
        probe_provider_end_to_end(args.pdf)

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
