"""HTTP backend must be reachable without any Selenium import.

Blocks regressions where a pure-soup extractor accidentally pulls in
the selenium-bound siblings via a package __init__, making the HTTP
path unusable on hosts without Chrome/chromedriver.
"""

from __future__ import annotations

import subprocess
import sys


def test_importing_src_scraper_http_loads_zero_selenium_modules() -> None:
    code = (
        "import sys; "
        "import src.scraper_http;"  # noqa
        "print(len([m for m in sys.modules if m.startswith('selenium')]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        cwd=".",
    )
    count = int(result.stdout.strip())
    assert count == 0, (
        f"Importing src.scraper_http pulled in {count} selenium modules. "
        f"First 5: {result.stderr}"
    )
