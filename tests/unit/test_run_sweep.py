"""Tests for scripts.run_sweep helpers that need care: CSV parsing for
the sweep input and Selenium-baseline row parsing for parity comparisons.
"""

from __future__ import annotations

import io

import pytest

from unittest.mock import Mock

import requests

from scripts.run_sweep import (
    parse_selenium_row,
    parse_sweep_csv,
)
from src._shared import CircuitBreaker, classify_exception
from src.http_session import RetryableHTTPError


def test_parse_sweep_csv_minimal_columns():
    f = io.StringIO("classe,processo\nADI,100\nAI,772309\n")
    rows = parse_sweep_csv(f)
    assert rows == [("ADI", 100, None), ("AI", 772309, None)]


def test_parse_sweep_csv_with_source_column():
    f = io.StringIO(
        "classe,processo,source\nADI,2820,ground_truth\nHC,82959,curated\n"
    )
    rows = parse_sweep_csv(f)
    assert rows == [
        ("ADI", 2820, "ground_truth"),
        ("HC", 82959, "curated"),
    ]


def test_parse_selenium_row_scalar_and_list_fields():
    row = {
        "incidente": "123456",
        "classe": "ADI",
        "processo_id": "42",
        "numero_unico": "0000042-00.0000.0.00.0000",
        "meio": "FISICO",
        "publicidade": "PUBLICO",
        "badges": "[]",
        "assuntos": '["ASSUNTO A", "ASSUNTO B"]',
        "data_protocolo": "01/01/2000",
        "orgao_origem": "SP",
        "origem": "SP - SAO PAULO",
        "numero_origem": "",
        "volumes": "2",
        "folhas": "400",
        "apensos": "1",
        "relator": "MIN. X",
        "primeiro_autor": "AUTOR",
        "partes": '[{"tipo": "REQTE.(S)"}]',
        "andamentos": "[]",
        "sessao_virtual": "[]",
        "deslocamentos": "[]",
        "peticoes": "[]",
        "recursos": "[]",
        "pautas": "[]",
        "status": "200",
        "extraido": "2025-10-26T21:23:02.541442",
    }
    parsed = parse_selenium_row(row)

    assert parsed["incidente"] == 123456
    assert parsed["classe"] == "ADI"
    assert parsed["processo_id"] == 42
    assert parsed["volumes"] == 2
    assert parsed["folhas"] == 400
    assert parsed["apensos"] == 1
    assert parsed["assuntos"] == ["ASSUNTO A", "ASSUNTO B"]
    assert parsed["partes"] == [{"tipo": "REQTE.(S)"}]
    assert parsed["andamentos"] == []
    assert parsed["numero_origem"] is None


def test_parse_selenium_row_handles_empty_scalars():
    row = {
        "incidente": "",
        "classe": "ADI",
        "processo_id": "1",
        "numero_unico": "",
        "meio": "",
        "publicidade": "",
        "badges": "[]",
        "assuntos": "[]",
        "data_protocolo": "",
        "orgao_origem": "",
        "origem": "",
        "numero_origem": "",
        "volumes": "",
        "folhas": "",
        "apensos": "",
        "relator": "",
        "primeiro_autor": "",
        "partes": "[]",
        "andamentos": "[]",
        "sessao_virtual": "[]",
        "deslocamentos": "[]",
        "peticoes": "[]",
        "recursos": "[]",
        "pautas": "[]",
        "status": "200",
        "extraido": "",
    }
    parsed = parse_selenium_row(row)

    assert parsed["incidente"] is None
    assert parsed["numero_unico"] is None
    assert parsed["meio"] is None
    assert parsed["publicidade"] is None
    assert parsed["volumes"] is None
    assert parsed["folhas"] is None
    assert parsed["apensos"] is None
    assert parsed["relator"] is None


def test_classify_exception_http_error_extracts_status_and_url():
    # requests.HTTPError carries a .response with the status + url
    resp = Mock()
    resp.status_code = 403
    resp.url = "https://portal.stf.jus.br/processos/listarProcessos.asp?classe=ADI"
    err = requests.HTTPError("403 Client Error: Forbidden")
    err.response = resp

    etype, status, url = classify_exception(err)
    assert etype == "HTTPError"
    assert status == 403
    assert url == "https://portal.stf.jus.br/processos/listarProcessos.asp?classe=ADI"


def test_classify_exception_retryable_http_error():
    err = RetryableHTTPError(429, "http://x.test/page")
    etype, status, url = classify_exception(err)
    assert etype == "RetryableHTTPError"
    assert status == 429
    assert url == "http://x.test/page"


def test_classify_exception_connection_error():
    err = requests.ConnectionError("boom")
    etype, status, url = classify_exception(err)
    assert etype == "ConnectionError"
    assert status is None
    assert url is None


def test_classify_exception_unknown_error():
    err = ValueError("weird")
    etype, status, url = classify_exception(err)
    assert etype == "ValueError"
    assert status is None
    assert url is None


def test_circuit_breaker_does_not_trip_before_window_is_full():
    cb = CircuitBreaker(window=5, threshold=0.5)
    for _ in range(4):
        cb.record("error")
    assert not cb.tripped()


def test_circuit_breaker_does_not_trip_below_threshold():
    cb = CircuitBreaker(window=4, threshold=0.5)
    cb.record("ok")
    cb.record("ok")
    cb.record("error")
    cb.record("error")
    # 2/4 = 50%, not > 50%
    assert not cb.tripped()


def test_circuit_breaker_trips_above_threshold():
    cb = CircuitBreaker(window=4, threshold=0.5)
    cb.record("ok")
    cb.record("error")
    cb.record("error")
    cb.record("error")
    # 3/4 = 75% > 50%
    assert cb.tripped()


def test_circuit_breaker_rolling_window_recovers_after_ok_streak():
    cb = CircuitBreaker(window=4, threshold=0.5)
    for _ in range(4):
        cb.record("error")
    assert cb.tripped()
    # Now four successes roll the errors out of the window.
    for _ in range(4):
        cb.record("ok")
    assert not cb.tripped()


def test_circuit_breaker_does_not_trip_on_fails():
    # "fail" = STF returned 200 for a non-existent process (expected on
    # sparse numbering ranges). Only thrown exceptions ("error") count.
    cb = CircuitBreaker(window=4, threshold=0.5)
    cb.record("fail")
    cb.record("fail")
    cb.record("fail")
    cb.record("fail")
    assert not cb.tripped()


def test_circuit_breaker_trips_on_errors_ignoring_fails():
    cb = CircuitBreaker(window=4, threshold=0.5)
    cb.record("fail")
    cb.record("error")
    cb.record("error")
    cb.record("error")
    # 3 errors / 4 = 75% > 50% → trips. `fail` is benign.
    assert cb.tripped()


def test_parse_selenium_row_numero_origem_list():
    row = {
        "incidente": "1",
        "classe": "ADI",
        "processo_id": "1",
        "numero_unico": "",
        "meio": "",
        "publicidade": "",
        "badges": "[]",
        "assuntos": "[]",
        "data_protocolo": "",
        "orgao_origem": "",
        "origem": "",
        "numero_origem": "[123, 456]",
        "volumes": "",
        "folhas": "",
        "apensos": "",
        "relator": "",
        "primeiro_autor": "",
        "partes": "[]",
        "andamentos": "[]",
        "sessao_virtual": "[]",
        "deslocamentos": "[]",
        "peticoes": "[]",
        "recursos": "[]",
        "pautas": "[]",
        "status": "200",
        "extraido": "",
    }
    parsed = parse_selenium_row(row)
    assert parsed["numero_origem"] == [123, 456]
