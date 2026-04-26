"""Post-hoc CLI analysis of CliffDetector regime trajectory.

Replaces hand-rolled jq queries over ``sweep.log.jsonl`` /
``pdfs.log.jsonl`` with a single ``judex analisar-regimes <run-dir>``
invocation. Auto-detects whether the run is a case sweep
(``sweep.log.jsonl``, keyed by ``<CLASSE>_<pid>``) or a PDF sweep
(``pdfs.log.jsonl``, keyed by URL).

Default output is a rich-rendered transition timeline + cliff-first-seen
table. ``--json`` emits one JSON event per line (jq-friendly), so the
tool composes with shell pipelines when needed.

Distinct from ``probe`` / ``probe_sharded``: those read the compacted
``*.state.json`` snapshot for *live* monitoring (where are we now?);
this reads the append-only ``*.log.jsonl`` for *post-hoc* analysis
(what happened?).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Literal, Optional

LogKind = Literal["case", "pdf"]

# Severity-ordered. Used to (a) decide which regimes count as "cliff"
# in cliff_first_seen, (b) drive coloring in the rich display.
SEVERITY: dict[str, int] = {
    "warming": 0,
    "under_utilising": 1,
    "healthy": 2,
    "l2_engaged": 3,
    "approaching_collapse": 4,
    "collapse": 5,
}
SEVERE_REGIMES: frozenset[str] = frozenset(
    {"l2_engaged", "approaching_collapse", "collapse"}
)
REGIME_STYLE: dict[str, str] = {
    "warming": "dim",
    "under_utilising": "green",
    "healthy": "cyan",
    "l2_engaged": "yellow",
    "approaching_collapse": "red",
    "collapse": "red bold",
}


@dataclass(frozen=True)
class RegimeEvent:
    """One log row with regime stamped — the unit of analysis."""

    ts: str
    key: str  # "<CLASSE>_<pid>" for case sweeps; URL for PDF sweeps
    regime: str
    fail_rate: Optional[float]
    p95_wall_s: Optional[float]
    promoted_by: Optional[str]


def detect_log_kind(run_dir: Path) -> tuple[LogKind, Path]:
    """Return ``(kind, log_path)`` for the run directory.

    Prefers the case-sweep log when both are present — the WAF-hot
    sweep is the one an operator usually wants to inspect.
    """
    case_log = run_dir / "sweep.log.jsonl"
    pdf_log = run_dir / "pdfs.log.jsonl"
    if case_log.exists():
        return "case", case_log
    if pdf_log.exists():
        return "pdf", pdf_log
    raise FileNotFoundError(
        f"no sweep.log.jsonl or pdfs.log.jsonl in {run_dir}"
    )


def iter_regime_events(log_path: Path) -> Iterator[RegimeEvent]:
    """Yield one ``RegimeEvent`` per row that carries a non-null regime.

    Skips:
      - rows with ``regime`` missing or ``None`` (cache hits, pre-change logs)
      - malformed JSON lines (truncated tail from a killed process)

    Auto-detects key shape: case-sweep rows have ``classe`` + ``processo``;
    PDF-sweep rows have ``url``.
    """
    with log_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            regime = rec.get("regime")
            if regime is None:
                continue
            if "url" in rec:
                key = rec["url"]
            elif "classe" in rec and "processo" in rec:
                key = f"{rec['classe']}_{rec['processo']}"
            else:
                continue
            yield RegimeEvent(
                ts=rec.get("ts", ""),
                key=key,
                regime=regime,
                fail_rate=rec.get("regime_fail_rate"),
                p95_wall_s=rec.get("regime_p95_wall_s"),
                promoted_by=rec.get("regime_promoted_by"),
            )


def only_transitions(events: Iterable[RegimeEvent]) -> Iterator[RegimeEvent]:
    """Yield events where ``regime`` differs from the previous event.

    The first event always counts as a transition (the warming → first-band
    boundary is itself the first interesting moment in any sweep).
    """
    prev: Optional[str] = None
    for ev in events:
        if ev.regime != prev:
            yield ev
            prev = ev.regime


def cliff_first_seen(events: Iterable[RegimeEvent]) -> dict[str, RegimeEvent]:
    """Map each *severe* regime band (``l2_engaged`` and worse) to the
    first event that hit it.

    Less-severe bands are excluded — they're either healthy operation
    (under_utilising / healthy) or pre-classification (warming), and
    surfacing them in the cliff summary would be noise.
    """
    seen: dict[str, RegimeEvent] = {}
    for ev in events:
        if ev.regime in SEVERE_REGIMES and ev.regime not in seen:
            seen[ev.regime] = ev
    return seen


def summarize(events: Iterable[RegimeEvent]) -> dict[str, object]:
    """Return total + per-regime + per-promoter counts.

    Materialises the iterable, so don't call this on a generator you
    intend to consume elsewhere.
    """
    by_regime: Counter = Counter()
    by_promoter: Counter = Counter()
    total = 0
    for ev in events:
        total += 1
        by_regime[ev.regime] += 1
        if ev.promoted_by is not None:
            by_promoter[ev.promoted_by] += 1
    return {
        "total": total,
        "by_regime": dict(by_regime),
        "by_promoter": dict(by_promoter),
    }


# ----- rendering ------------------------------------------------------------


def _render_human(
    *,
    run_dir: Path,
    kind: LogKind,
    events: list[RegimeEvent],
    transitions: list[RegimeEvent],
    cliffs: dict[str, RegimeEvent],
    summary: dict[str, object],
    limit: int,
) -> None:
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    console = Console()
    kind_label = "case sweep" if kind == "case" else "PDF sweep"
    console.print(
        f"\n[bold]Regime trajectory · {run_dir} ({kind_label})[/bold]"
    )

    by_regime = summary["by_regime"]
    assert isinstance(by_regime, dict)
    regimes_str = ", ".join(
        f"[{REGIME_STYLE.get(r, '')}]{r}[/]={c}"
        for r, c in sorted(
            by_regime.items(), key=lambda kv: -SEVERITY.get(kv[0], 0)
        )
    )
    console.print(
        f"{summary['total']} records with regime · {regimes_str}"
    )
    console.print(f"Promoters: {summary['by_promoter']}\n")

    if not transitions:
        console.print("[dim]No regime transitions in this log.[/dim]")
        return

    show = transitions[:limit]
    truncated = len(transitions) - len(show)
    table = Table(
        title=f"Transitions ({len(transitions)} total"
        + (f", showing first {limit}" if truncated > 0 else "")
        + ")",
        show_lines=False,
    )
    table.add_column("ts", style="dim", no_wrap=True)
    table.add_column("key", no_wrap=True)
    table.add_column("regime")
    table.add_column("fail_rate", justify="right")
    table.add_column("p95", justify="right")
    table.add_column("by")
    prev_label = "—"
    for ev in show:
        regime_text = Text(
            f"{prev_label} → {ev.regime}",
            style=REGIME_STYLE.get(ev.regime, ""),
        )
        table.add_row(
            ev.ts,
            ev.key,
            regime_text,
            f"{ev.fail_rate:.2f}" if ev.fail_rate is not None else "—",
            f"{ev.p95_wall_s:.1f}s" if ev.p95_wall_s is not None else "—",
            ev.promoted_by or "—",
        )
        prev_label = ev.regime
    console.print(table)

    if cliffs:
        console.print("\n[bold]Cliff first-seen:[/bold]")
        for label in ("l2_engaged", "approaching_collapse", "collapse"):
            ev = cliffs.get(label)
            if ev is None:
                continue
            fr = f"{ev.fail_rate:.2f}" if ev.fail_rate is not None else "—"
            p95 = f"{ev.p95_wall_s:.1f}s" if ev.p95_wall_s is not None else "—"
            console.print(
                f"  [{REGIME_STYLE[label]}]{label:<22}[/]"
                f" {ev.key}  at {ev.ts}"
                f"  (fail_rate={fr} p95={p95} by={ev.promoted_by or '—'})"
            )


def _render_json(events: Iterable[RegimeEvent]) -> None:
    for ev in events:
        sys.stdout.write(json.dumps({
            "ts": ev.ts,
            "key": ev.key,
            "regime": ev.regime,
            "fail_rate": ev.fail_rate,
            "p95_wall_s": ev.p95_wall_s,
            "promoted_by": ev.promoted_by,
        }) + "\n")


# ----- argparse + main ------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="analisar-regimes",
        description="Post-hoc CliffDetector regime analysis over a sweep run dir.",
    )
    p.add_argument(
        "run_dir",
        type=Path,
        help="Diretório de varredura (contém sweep.log.jsonl ou pdfs.log.jsonl).",
    )
    p.add_argument(
        "--apenas-transicoes",
        action="store_true",
        help="Mostra só os eventos onde o regime mudou. Default: ligado para "
             "saída humana, desligado para --json.",
    )
    p.add_argument(
        "--filtrar",
        type=str,
        default=None,
        help="Filtra para um único rótulo de regime (ex.: approaching_collapse).",
    )
    p.add_argument(
        "--limite",
        type=int,
        default=50,
        help="Máximo de transições renderizadas na tabela humana (default: 50).",
    )
    p.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        help="Emite uma linha JSON por evento (jq-compatível). "
             "Se não combinar com --apenas-transicoes, sai o stream completo.",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        kind, log_path = detect_log_kind(args.run_dir)
    except FileNotFoundError as e:
        sys.stderr.write(f"error: {e}\n")
        return 2

    events = list(iter_regime_events(log_path))
    if args.filtrar is not None:
        events = [e for e in events if e.regime == args.filtrar]

    if args.json_out:
        stream = list(only_transitions(events)) if args.apenas_transicoes else events
        _render_json(stream)
        return 0

    transitions = list(only_transitions(events))
    cliffs = cliff_first_seen(events)
    summary = summarize(events)
    _render_human(
        run_dir=args.run_dir,
        kind=kind,
        events=events,
        transitions=transitions,
        cliffs=cliffs,
        summary=summary,
        limit=args.limite,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
