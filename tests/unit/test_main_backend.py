"""CLI dispatch: --backend selects which scraper implementation runs."""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def common_args(tmp_path) -> list[str]:
    return [
        "-c", "AI",
        "-i", "1",
        "-f", "1",
        "-o", "csv",
        "-d", str(tmp_path),
    ]


def test_backend_defaults_to_selenium(
    runner: CliRunner, common_args: list[str]
) -> None:
    with patch("main.run_scraper_http") as http, patch("main.run_scraper") as sel:
        result = runner.invoke(main.app, common_args)

    assert result.exit_code == 0, result.output
    sel.assert_called_once()
    http.assert_not_called()


def test_backend_http_dispatches_to_http_scraper(
    runner: CliRunner, common_args: list[str]
) -> None:
    with patch("main.run_scraper_http") as http, patch("main.run_scraper") as sel:
        result = runner.invoke(main.app, ["--backend", "http", *common_args])

    assert result.exit_code == 0, result.output
    http.assert_called_once()
    sel.assert_not_called()


def test_backend_selenium_dispatches_to_selenium_scraper(
    runner: CliRunner, common_args: list[str]
) -> None:
    with patch("main.run_scraper_http") as http, patch("main.run_scraper") as sel:
        result = runner.invoke(main.app, ["--backend", "selenium", *common_args])

    assert result.exit_code == 0, result.output
    sel.assert_called_once()
    http.assert_not_called()


def test_invalid_backend_fails_fast(
    runner: CliRunner, common_args: list[str]
) -> None:
    with patch("main.run_scraper_http") as http, patch("main.run_scraper") as sel:
        result = runner.invoke(main.app, ["--backend", "bogus", *common_args])

    assert result.exit_code != 0
    sel.assert_not_called()
    http.assert_not_called()
