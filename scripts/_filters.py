"""Shared CSV-parsing helper used by the PDF CLI scripts."""

from __future__ import annotations


def split_csv(s: str | None) -> list[str]:
    if not s:
        return []
    return [p.strip() for p in s.split(",") if p.strip()]
