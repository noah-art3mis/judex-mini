"""HTTP backend must be reachable without any Selenium import.

Blocks regressions where a pure-soup extractor accidentally pulls in
the selenium-bound siblings via a package __init__, making the HTTP
path unusable on hosts without Chrome/chromedriver.
"""

from __future__ import annotations

import subprocess
import sys


def _count_selenium_modules_after_import(target: str) -> int:
    code = (
        f"import sys; import {target};"  # noqa
        "print(len([m for m in sys.modules if m.startswith('selenium')]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        cwd=".",
    )
    return int(result.stdout.strip())


def test_importing_src_scraper_http_loads_zero_selenium_modules() -> None:
    count = _count_selenium_modules_after_import("src.scraper_http")
    assert count == 0, (
        f"Importing src.scraper_http pulled in {count} selenium modules."
    )


def test_importing_main_loads_zero_selenium_modules() -> None:
    count = _count_selenium_modules_after_import("main")
    assert count == 0, (
        f"Importing main pulled in {count} selenium modules — the "
        f"Selenium dispatch should be entirely gone post-2026-04-17."
    )
