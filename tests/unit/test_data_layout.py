"""Layout invariant: no code references the pre-2026-04-26 data/ paths.

The reorganization moved everything to source/ + raw/ + derived/ + state/.
This test fails fast if any source file reintroduces an old path string —
so a careless copy-paste from a stale doc or a checked-in notebook can't
silently bring back the dishonest `data/cache/` axis.

Allowed exceptions: gitignored notebooks under analysis/ (where embedded
JSON fixtures contain historical text_path strings that document what
was on disk *before* the migration), and the migration plan itself.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

OLD_PATTERNS = [
    r'\bdata/cases\b',
    r'\bdata/cache/pdf\b',
    r'\bdata/cache/html\b',
    r'\bdata/cache/scraper-session-logs\b',
    r'\bdata/cache/_canary-outputs\b',
    r'\bdata/cache/requests\b',
    r'\bdata/warehouse/judex\b',
    r'\bdata/dead_ids\b',
    r'\bdata/exports\b',
    r'\bdata/reports\b',
    r'\bdata/work\b',
    r'\bdata/logs\b',
]

# Subtrees that may legitimately contain old-path strings:
#   - analysis/ holds gitignored notebooks with embedded historical JSON fixtures
#   - tests/unit/test_data_layout.py is this file (it has to mention the patterns)
ALLOWED_PATH_PREFIXES = ("analysis/", "tests/unit/test_data_layout.py")


def _scan_targets() -> list[Path]:
    """Return all tracked .py + .sh files, minus the allow-list.

    Shell scripts are included because the launcher scripts under
    scripts/ (e.g. launch_hc_year_sharded.sh) construct --items-dir
    paths directly and would silently break if the layout drifts.
    """
    result = subprocess.run(
        ["git", "ls-files", "*.py", "*.sh"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    files = []
    for line in result.stdout.splitlines():
        rel = line.strip()
        if not rel:
            continue
        if rel.startswith(ALLOWED_PATH_PREFIXES):
            continue
        files.append(REPO_ROOT / rel)
    return files


def test_no_old_data_paths_in_tracked_source() -> None:
    targets = _scan_targets()
    assert targets, "git ls-files returned no .py/.sh files — sanity-check the test"

    pattern = re.compile("|".join(OLD_PATTERNS))
    offenders: list[tuple[Path, int, str]] = []
    for path in targets:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offenders.append((path.relative_to(REPO_ROOT), lineno, line.strip()))

    if offenders:
        msg = "\n".join(
            f"  {p}:{n}  {line[:100]}" for p, n, line in offenders[:20]
        )
        raise AssertionError(
            f"{len(offenders)} reference(s) to pre-reorg data/ paths in tracked .py files:\n{msg}"
            + ("\n  ..." if len(offenders) > 20 else "")
        )
