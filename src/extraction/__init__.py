"""Extraction functions. Import specific extractors from their submodules.

The package __init__ is intentionally empty so that importing a
single submodule (e.g. `from src.extraction.extract_classe import
extract_classe`) doesn't drag in the Selenium-bound siblings —
keeps the HTTP backend free of the selenium dependency.
"""
