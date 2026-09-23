"""The TermStation CRT bezel -- one source of truth for the screen geometry.

Both the launcher and games import this module, so the frame drawn by the
console during boot and the frame drawn by a game afterwards land on exactly
the same cells. That is why the bezel never blinks at the handover.

A cooperative frame, not a relay: `\\x1b[2J` (erase display) ignores terminal
scroll margins, so a curses game would wipe any frame the parent drew around
it. Instead games draw the frame themselves via `tv()` / `tv_curses()`, and a
game that ignores the bezel simply runs full screen.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass

# Frame costs: top border + title bar + separator, and a bottom border.
CHROME_ROWS = 4
CHROME_COLS = 4  # border + one space of padding on each side

MIN_COLS = 60
MIN_ROWS = 18

TL, TR, BL, BR = "╔", "╗", "╚", "╝"
H, V = "═", "║"
ML, MR = "╟", "╢"
HL = "─"


@dataclass(frozen=True)
class Screen:
    """Where the picture lives inside the cabinet."""
    cols: int          # full terminal
    rows: int
    x: int             # inner content origin (0-indexed)
    y: int
    width: int         # inner content size
    height: int
    framed: bool

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height


def geometry(cols: int | None = None, rows: int | None = None) -> Screen:
    """Inner drawing area for the current terminal.

    Below MIN_COLS x MIN_ROWS the frame is dropped rather than squeezed -- a
    bezel that eats a third of a small terminal is worse than no bezel.
    """
    if cols is None or rows is None:
        term = shutil.get_terminal_size((80, 24))
        cols = cols or term.columns
        rows = rows or term.lines
    if cols < MIN_COLS or rows < MIN_ROWS:
        return Screen(cols, rows, 0, 0, cols, rows, framed=False)
    return Screen(cols, rows, 2, 3, cols - CHROME_COLS, rows - CHROME_ROWS, framed=True)


def inner_size(cols: int | None = None, rows: int | None = None) -> tuple[int, int]:
    g = geometry(cols, rows)
    return g.width, g.height


def frame_lines(screen: Screen, title: str = "", right: str = "LAZSTATION 2",
                power: bool = True) -> list[tuple[int, int, str]]:
    """The bezel as (y, x, text) runs -- rendered by ANSI or curses alike."""
    if not screen.framed:
        return []
    w = screen.cols
    span = w - 2
    led = "●" if power else "○"
    label = f" {led} {title.upper()}"[: span - len(right) - 2]
    bar = label.ljust(span - len(right) - 1) + right + " "
    return [
        (0, 0, TL + H * span + TR),
        (1, 0, V + bar[:span] + V),
        (2, 0, ML + HL * span + MR),
        (screen.rows - 1, 0, BL + H * span + BR),
    ]


def side_runs(screen: Screen) -> list[tuple[int, int, str]]:
    """The left and right cabinet edges for every content row."""
    if not screen.framed:
        return []
    runs = []
    for y in range(3, screen.rows - 1):
        runs.append((y, 0, V))
        runs.append((y, screen.cols - 1, V))
    return runs
