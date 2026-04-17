# `src/_deprecated/` — frozen Selenium scraper

This subtree holds the original Selenium-based STF scraper, retired
2026-04-17. The HTTP backend (`src/scraper.py`) is now the only
first-class scraping path. Nothing in the live code path imports
from here.

## What's here

```
_deprecated/
├── scraper.py                      # was src/scraper.py — orchestrator
├── utils/
│   ├── driver.py                   # was src/utils/driver.py — chromedriver factory
│   └── get_element.py              # was src/utils/get_element.py — XPath helpers
└── extraction/
    └── extract_*.py                # 16 selenium-bound DOM extractors
```

The pure-soup extractors that the HTTP backend reuses
(`extract_classe`, `extract_meio`, `extract_numero_unico`,
`extract_publicidade`, `extract_relator`) **stayed** at
`src/extraction/` — they have no Selenium dependency.

## Why kept (instead of deleted)

The DOM-walking extractors capture exactly what STF emits at the HTML
level for each tab — useful as living documentation of the page
structure if the HTTP backend ever has to re-derive a field. The bug
list under `docs/handoff.md § 5. Pre-existing bugs in the Selenium side`
is also frozen here as-is; we don't maintain this code, we just
preserve it.

## Running it

The `selenium` dependency moved to an opt-in `[selenium-legacy]`
extra. To install:

```bash
uv sync --extra selenium-legacy
```

Even with selenium installed, `main.py --backend selenium` is now an
error — the dispatch was removed. To run the deprecated scraper you
must either pin an older release of judex-mini (pre-2026-04-17) or
import directly:

```python
from src._deprecated.scraper import run_scraper
```

## Hard-removal criterion

If a year passes with no one importing from `src/_deprecated/`, the
whole subtree gets deleted and the `[selenium-legacy]` extra goes
away. See `docs/superpowers/specs/2026-04-17-selenium-retirement.md
§ Phase 2`.
