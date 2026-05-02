"""Rich-based CLI rendering helpers — warning panels, kv blocks, info lines.

Single home for the visual idioms shared by ``baixar-pecas`` and
``extrair-pecas`` previews and the various pre-flight warnings printed
by sweep entry points. Kept small on purpose: three primitives is
enough for the current CLI surface, and any new bespoke layout should
land here rather than re-importing rich at the call site.

Output rules:

- Each helper binds a fresh ``Console`` to the destination stream.
  ``Console`` auto-detects ``stream.isatty()`` and disables ANSI
  escapes for non-TTY destinations (``io.StringIO`` in unit tests,
  ``launcher-stdout.log`` in detached sweeps). Box-drawing characters
  survive in both modes — the layout reads fine in plain logs.
- Helpers flush after writing. The legacy ``print(..., flush=True)``
  call sites care about ordering vs. subsequent sweep stdout, so the
  switch must preserve that.
"""

from __future__ import annotations

import sys
from typing import Iterable, Sequence, TextIO

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


_DEFAULT_WIDTH = 92


def _make_console(stream: TextIO | None) -> Console:
    target = stream if stream is not None else sys.stdout
    is_tty = bool(getattr(target, "isatty", lambda: False)())
    return Console(
        file=target,
        force_terminal=is_tty,
        color_system="auto" if is_tty else None,
        width=_DEFAULT_WIDTH,
        highlight=False,
        emoji=False,
    )


def _flush(stream: TextIO | None) -> None:
    target = stream if stream is not None else sys.stdout
    flush = getattr(target, "flush", None)
    if callable(flush):
        try:
            flush()
        except Exception:
            pass


def render_warning(
    title: str,
    body_lines: Sequence[str],
    *,
    stream: TextIO | None = None,
) -> None:
    """Yellow-bordered panel for non-fatal, operator-actionable warnings.

    ``body_lines`` are joined with newlines inside the panel. The title
    is prefixed with a warning glyph; pass the warning subject only
    (e.g. ``"unseen tipo(s)"``).
    """
    console = _make_console(stream)
    panel = Panel(
        "\n".join(body_lines),
        title=f"⚠  {title}",
        title_align="left",
        border_style="yellow",
        box=box.ROUNDED,
        padding=(0, 1),
    )
    console.print(panel)
    _flush(stream)


def render_info(message: str, *, stream: TextIO | None = None) -> None:
    """One-line dim notice — pre-flight summaries, filter side-effects."""
    console = _make_console(stream)
    console.print(f"[dim]·[/dim] {message}")
    _flush(stream)


def render_kv_block(
    title: str,
    rows: Iterable[tuple[str, str]],
    *,
    subtitle: str | None = None,
    stream: TextIO | None = None,
    border_style: str = "cyan",
) -> None:
    """Soft-bordered panel containing a right-aligned key/value grid.

    Used by the download / extract previews. ``subtitle`` lands on the
    bottom-right of the panel — good for the ``modo: …`` annotation.
    """
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="left", no_wrap=True)
    grid.add_column(justify="right", no_wrap=True)
    for key, value in rows:
        grid.add_row(key, value)

    panel = Panel(
        grid,
        title=title,
        title_align="left",
        subtitle=subtitle,
        subtitle_align="right",
        border_style=border_style,
        box=box.ROUNDED,
        padding=(0, 1),
    )
    _make_console(stream).print(panel)
    _flush(stream)
