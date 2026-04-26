"""URL-keyed request log. One row per outbound GET.

SQLite with WAL journal mode so `_TAB_WORKERS=4` concurrent inserts
don't block each other. Schema is append-only — we never update or
delete, so historical latencies / statuses per URL are preserved for
post-hoc diagnosis.

The `context` column is opaque JSON; callers stuff whatever
provenance they want (`processo_id`, `classe`, `tab`, `doc_type`,
`lawyer_hits`, …) without schema churn.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  url          TEXT NOT NULL,
  host         TEXT NOT NULL,
  method       TEXT NOT NULL DEFAULT 'GET',
  status       INTEGER,
  elapsed_ms   INTEGER,
  bytes        INTEGER,
  fetched_at   TEXT NOT NULL,
  from_cache   INTEGER NOT NULL DEFAULT 0,
  context_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_requests_url ON requests(url);
CREATE INDEX IF NOT EXISTS idx_requests_host ON requests(host);
CREATE INDEX IF NOT EXISTS idx_requests_fetched_at ON requests(fetched_at);
"""


class RequestLog:
    def __init__(self, db_path: Path | str = "state/requests-archive.duckdb") -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.execute("PRAGMA journal_mode=WAL")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def log(
        self,
        *,
        url: str,
        status: Optional[int] = None,
        elapsed_ms: Optional[int] = None,
        bytes: Optional[int] = None,
        from_cache: bool = False,
        context: Optional[dict[str, Any]] = None,
        method: str = "GET",
    ) -> None:
        host = urlparse(url).hostname or ""
        ctx = json.dumps(context, ensure_ascii=False) if context else None
        now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO requests "
                "(url, host, method, status, elapsed_ms, bytes, fetched_at, "
                " from_cache, context_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (url, host, method, status, elapsed_ms, bytes, now,
                 1 if from_cache else 0, ctx),
            )

    def count(self) -> int:
        with self._connect() as conn:
            (n,) = conn.execute("SELECT COUNT(*) FROM requests").fetchone()
            return int(n)

    def count_by_host(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT host, COUNT(*) FROM requests GROUP BY host"
            ).fetchall()
            return {r[0]: int(r[1]) for r in rows}

    def find_by_url(self, url: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT url, host, method, status, elapsed_ms, bytes, "
                "fetched_at, from_cache, context_json "
                "FROM requests WHERE url = ? ORDER BY id DESC",
                (url,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def per_host_stats(self) -> list[dict[str, Any]]:
        """Per-host aggregate for report rendering.

        Counts are over all rows; latency percentiles are computed over
        non-cache-hit rows with `elapsed_ms IS NOT NULL` (cache hits aren't
        network time).
        """
        with self._connect() as conn:
            host_rows = conn.execute(
                """
                SELECT host,
                       COUNT(*) AS n,
                       SUM(CASE WHEN from_cache = 1 THEN 1 ELSE 0 END) AS cache_hits,
                       SUM(CASE WHEN status = 200 THEN 1 ELSE 0 END) AS n_200,
                       SUM(CASE WHEN status = 403 THEN 1 ELSE 0 END) AS n_403,
                       SUM(CASE WHEN status >= 500 AND status < 600 THEN 1 ELSE 0 END) AS n_5xx
                FROM requests GROUP BY host ORDER BY n DESC
                """
            ).fetchall()
            elapsed_by_host: dict[str, list[int]] = {}
            for host, ms in conn.execute(
                "SELECT host, elapsed_ms FROM requests "
                "WHERE elapsed_ms IS NOT NULL AND from_cache = 0"
            ):
                elapsed_by_host.setdefault(host, []).append(int(ms))

        out: list[dict[str, Any]] = []
        for r in host_rows:
            host = r["host"]
            samples = sorted(elapsed_by_host.get(host, []))
            p50, p90, pmax = _percentiles_ms(samples)
            out.append({
                "host": host,
                "n": int(r["n"]),
                "cache_hits": int(r["cache_hits"] or 0),
                "n_200": int(r["n_200"] or 0),
                "n_403": int(r["n_403"] or 0),
                "n_5xx": int(r["n_5xx"] or 0),
                "p50_ms": p50,
                "p90_ms": p90,
                "max_ms": pmax,
            })
        return out


def _percentiles_ms(sorted_samples: list[int]) -> tuple[int, int, int]:
    """Return (p50, p90, max) via nearest-rank; zeros when empty."""
    n = len(sorted_samples)
    if n == 0:
        return (0, 0, 0)
    p50 = sorted_samples[int(round(0.5 * (n - 1)))]
    p90 = sorted_samples[int(round(0.9 * (n - 1)))]
    return (int(p50), int(p90), int(sorted_samples[-1]))


def _row_to_dict(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    d["from_cache"] = bool(d.pop("from_cache"))
    ctx = d.pop("context_json")
    d["context"] = json.loads(ctx) if ctx else None
    return d
