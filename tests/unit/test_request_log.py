"""URL-keyed request log — one row per outbound GET.

SQLite-backed provenance table: which URL was fetched, when, from which
host, how long it took, the response status, byte count, cache hit/miss,
and an opaque JSON context column for caller-supplied metadata
(processo_id, classe, tab, doc_type, …).
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from judex.utils.request_log import RequestLog


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "requests.db"


def test_new_log_starts_empty(db_path: Path) -> None:
    log = RequestLog(db_path)
    assert log.count() == 0


def test_log_writes_a_row(db_path: Path) -> None:
    log = RequestLog(db_path)
    log.log(
        url="https://portal.stf.jus.br/processos/abaAndamentos.asp?incidente=1",
        status=200,
        elapsed_ms=412,
        bytes=10240,
        from_cache=False,
    )
    assert log.count() == 1


def test_log_derives_host_from_url(db_path: Path) -> None:
    log = RequestLog(db_path)
    log.log(url="https://portal.stf.jus.br/processos/x", status=200)
    rows = log.find_by_url("https://portal.stf.jus.br/processos/x")
    assert rows[0]["host"] == "portal.stf.jus.br"


def test_log_records_context_json(db_path: Path) -> None:
    log = RequestLog(db_path)
    log.log(
        url="https://portal.stf.jus.br/processos/x",
        status=200,
        context={"processo_id": 123, "classe": "HC", "tab": "abaAndamentos"},
    )
    rows = log.find_by_url("https://portal.stf.jus.br/processos/x")
    assert rows[0]["context"] == {
        "processo_id": 123,
        "classe": "HC",
        "tab": "abaAndamentos",
    }


def test_log_records_cache_hit_without_status(db_path: Path) -> None:
    log = RequestLog(db_path)
    log.log(url="https://portal.stf.jus.br/processos/x", from_cache=True)
    rows = log.find_by_url("https://portal.stf.jus.br/processos/x")
    assert rows[0]["from_cache"] is True
    assert rows[0]["status"] is None


def test_find_by_url_returns_all_matches_newest_first(db_path: Path) -> None:
    log = RequestLog(db_path)
    url = "https://portal.stf.jus.br/processos/x"
    log.log(url=url, status=403)
    log.log(url=url, status=200)
    rows = log.find_by_url(url)
    assert [r["status"] for r in rows] == [200, 403]


def test_concurrent_writes_all_land(db_path: Path) -> None:
    log = RequestLog(db_path)

    def worker(tid: int) -> None:
        for i in range(20):
            log.log(
                url=f"https://portal.stf.jus.br/processos/t{tid}i{i}",
                status=200,
                elapsed_ms=10,
            )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert log.count() == 4 * 20


def test_count_by_host(db_path: Path) -> None:
    log = RequestLog(db_path)
    log.log(url="https://portal.stf.jus.br/a", status=200)
    log.log(url="https://portal.stf.jus.br/b", status=200)
    log.log(url="https://sistemas.stf.jus.br/c", status=200)
    by_host = log.count_by_host()
    assert by_host == {"portal.stf.jus.br": 2, "sistemas.stf.jus.br": 1}


def test_per_host_stats_aggregates_counts_and_latency(db_path: Path) -> None:
    log = RequestLog(db_path)
    for ms in (100, 200, 300, 400, 500):
        log.log(url="https://portal.stf.jus.br/x", status=200, elapsed_ms=ms)
    log.log(url="https://portal.stf.jus.br/y", status=403, elapsed_ms=1000)
    log.log(url="https://portal.stf.jus.br/z", status=503, elapsed_ms=2000)
    log.log(url="https://portal.stf.jus.br/c", from_cache=True)
    log.log(url="https://sistemas.stf.jus.br/a", status=200, elapsed_ms=50)

    stats = {s["host"]: s for s in log.per_host_stats()}

    portal = stats["portal.stf.jus.br"]
    assert portal["n"] == 8
    assert portal["cache_hits"] == 1
    assert portal["n_200"] == 5
    assert portal["n_403"] == 1
    assert portal["n_5xx"] == 1
    # 7 non-cache elapsed samples; p50 ≈ 400 (median of 100,200,300,400,500,1000,2000)
    assert portal["p50_ms"] == 400
    assert portal["max_ms"] == 2000

    sistemas = stats["sistemas.stf.jus.br"]
    assert sistemas["n"] == 1
    assert sistemas["n_200"] == 1
    assert sistemas["p50_ms"] == 50
