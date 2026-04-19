"""Render the daily report as a single Markdown string.

Pure: `list[StfItem-shaped dict]` + date/classe/stats → `str`. No I/O.
The orchestrator (`scripts/daily_report.py`) picks the output path.

Two optional sections in one artifact:
    1. New filings — cases discovered since the last high-water mark.
    2. Watched cases — diff against each case's last-seen snapshot.
       Provided by passing ``watched_changes=…``; omit or pass None to
       keep the legacy "new filings only" layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from judex.reports.watch_diff import WatchChange

_MISSING = "—"


@dataclass(frozen=True)
class WatchedCaseChange:
    """One watched case's identity + freshly-scraped item + diff."""
    classe: str
    numero: int
    item: dict
    change: WatchChange


def _fmt(value: Any) -> str:
    if value is None or value == "" or value == []:
        return _MISSING
    return str(value)


def _render_partes(partes: list[dict]) -> list[str]:
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


def _render_andamento(a: dict) -> str:
    data = a.get("data") or _MISSING
    nome = a.get("nome") or _MISSING
    comp = a.get("complemento")
    suffix = f" — {comp}" if comp else ""
    return f"  - {data}: {nome}{suffix}"


def _render_publicacao_dje(p: dict) -> str:
    numero = p.get("numero") or _MISSING
    data = p.get("data") or _MISSING
    titulo = p.get("titulo") or _MISSING
    return f"  - DJ {numero} ({data}) — {titulo}"


def _render_generic_list_item(x: Any) -> str:
    return f"  - {x}"


def _render_added_items(field_name: str, items: list) -> list[str]:
    if field_name == "andamentos":
        return [_render_andamento(a) for a in items]
    if field_name == "publicacoes_dje":
        return [_render_publicacao_dje(p) for p in items]
    return [_render_generic_list_item(x) for x in items]


def _summarize_change(change: WatchChange) -> str:
    """Short suffix for the section header: '2 new andamentos, relator changed'."""
    parts: list[str] = []
    for field_name, items in change.items_added.items():
        parts.append(f"{len(items)} new {field_name}")
    for field_name in change.fields_changed:
        parts.append(f"{field_name} changed")
    return ", ".join(parts) if parts else ""


def _render_watched_case(wc: WatchedCaseChange) -> list[str]:
    header = f"### {wc.classe} {wc.numero}"
    if wc.change.is_new:
        header += " (first time scraped)"
    else:
        suffix = _summarize_change(wc.change)
        if suffix:
            header += f" — {suffix}"

    lines = [header, ""]

    if wc.change.is_new:
        lines.extend([
            "- **Relator:** " + _fmt(wc.item.get("relator")),
            "- **Primeiro autor:** " + _fmt(wc.item.get("primeiro_autor")),
            "",
        ])
        return lines

    for field_name, (old, new) in wc.change.fields_changed.items():
        lines.append(f"- **{field_name}:** {_fmt(old)} → {_fmt(new)}")

    for field_name, items in wc.change.items_added.items():
        lines.append(f"- **New {field_name}:**")
        lines.extend(_render_added_items(field_name, items))

    lines.append("")
    return lines


def _render_watched_section(changes: list[WatchedCaseChange]) -> list[str]:
    lines = ["---", "", f"## Changes on watched cases ({len(changes)})", ""]
    if not changes:
        lines.extend(["No watched cases changed since last run.", ""])
        return lines

    for wc in sorted(changes, key=lambda c: (c.classe, c.numero)):
        lines.extend(_render_watched_case(wc))
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
    if "watched_total" in stats:
        lines.append(f"- Watched cases checked: {stats['watched_total']}")
    lines.append("")
    return lines


def render_daily_markdown(
    cases: list[dict],
    *,
    date: str,
    classe: str,
    stats: dict,
    watched_changes: list[WatchedCaseChange] | None = None,
) -> str:
    """Render the daily report as a Markdown string.

    `watched_changes=None` keeps the legacy layout (new-filings-only).
    Pass `[]` to render the "No watched cases changed" placeholder block.
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

    if watched_changes is not None:
        # Render only cases that actually changed; filter noise.
        actionable = [wc for wc in watched_changes if wc.change.has_changes]
        lines.extend(_render_watched_section(actionable))

    lines.extend(_render_stats(stats))

    return "\n".join(lines)
