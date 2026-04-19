"""Render the daily new-filings report as a single Markdown string.

Pure: `list[StfItem-shaped dict]` + date/classe/stats → `str`. No I/O.
The orchestrator (`scripts/daily_report.py`) picks the output path.

v1 scope: new filings only (no watch-set refresh, no PDF content embed).
Each case is rendered as a compact bullet list of the fields a journalist
or lawyer would scan first — numero, incidente, relator, primeiro_autor,
protocolo, origem, partes, assuntos, source URL.
"""

from __future__ import annotations

from typing import Any

_MISSING = "—"


def _fmt(value: Any) -> str:
    """Render None / empty as em-dash; pass through everything else as str."""
    if value is None or value == "" or value == []:
        return _MISSING
    return str(value)


def _render_partes(partes: list[dict]) -> list[str]:
    """Bullet sub-list of `tipo — nome` lines, or a single em-dash bullet if empty."""
    if not partes:
        return [f"  - {_MISSING}"]
    return [f"  - {p.get('tipo', _MISSING)} — {p.get('nome', _MISSING)}" for p in partes]


def _render_case(case: dict) -> list[str]:
    classe = case.get("classe", "?")
    processo_id = case.get("processo_id", "?")
    lines = [f"## {classe} {processo_id}", ""]

    assuntos = case.get("assuntos") or []
    assuntos_str = ", ".join(assuntos) if assuntos else _MISSING

    lines.extend([
        f"- **Incidente:** {_fmt(case.get('incidente'))}",
        f"- **Protocolado:** {_fmt(case.get('data_protocolo'))}",
        f"- **Relator:** {_fmt(case.get('relator'))}",
        f"- **Primeiro autor:** {_fmt(case.get('primeiro_autor'))}",
        f"- **Origem:** {_fmt(case.get('origem'))}",
        f"- **Assuntos:** {assuntos_str}",
        "- **Partes:**",
    ])
    lines.extend(_render_partes(case.get("partes") or []))

    url = case.get("url")
    if url:
        lines.append(f"- [Link no portal STF]({url})")

    lines.append("")
    return lines


def _render_stats(stats: dict) -> list[str]:
    if not stats:
        return []
    lines = ["---", "", "## Summary", ""]
    if "n_probed" in stats:
        lines.append(f"- Numbers probed: {stats['n_probed']}")
    if "pdfs_downloaded" in stats:
        lines.append(f"- PDFs downloaded: {stats['pdfs_downloaded']}")
    if "duration_s" in stats:
        lines.append(f"- Duration: {stats['duration_s']}s")
    if "waf_403s" in stats:
        lines.append(f"- WAF 403s: {stats['waf_403s']}")
    lines.append("")
    return lines


def render_daily_markdown(
    cases: list[dict],
    *,
    date: str,
    classe: str,
    stats: dict,
) -> str:
    """Render the daily report as a Markdown string.

    `cases` may be empty (empty-day: header + placeholder + stats).
    `stats` is optional and pass-through — only keys the renderer knows
    about are emitted, unknown keys ignored.
    """
    sorted_cases = sorted(cases, key=lambda c: c.get("processo_id", 0))

    lines: list[str] = [
        f"# STF {classe} Daily — {date}",
        "",
        f"**{len(sorted_cases)} new filings** discovered today.",
        "",
    ]

    if not sorted_cases:
        lines.extend(["No new filings.", ""])
    else:
        for case in sorted_cases:
            lines.extend(_render_case(case))

    lines.extend(_render_stats(stats))

    return "\n".join(lines)
