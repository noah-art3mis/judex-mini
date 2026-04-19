"""Derived analytical warehouse over judex-mini case + PDF data.

Full rebuild pipeline in `builder.py`. Read-only connection helper in
`query.py` for marimo notebooks. Both treat `data/cases/` as the
single source of truth — the warehouse is never written to by the
scraper and can be regenerated from scratch at any time.
"""
