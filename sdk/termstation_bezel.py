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

#: The cabinet never grows past this. A screen stretched across an ultrawide
#: terminal leaves the picture stranded in one corner; a fixed set centred in
#: the room reads like a television.
MAX_COLS = 100
MAX_ROWS = 34

TL, TR, BL, BR = "╔", "╗", "╚", "╝"
H, V = "═", "║"
ML, MR = "╟", "╢"
HL = "─"

#: Cabinet glyphs per style: corners, edges, the title-bar separator ends and
#: its rule. "classic" is the double-line CRT set; "neo" is the thin rounded
#: set of the modern theme. Same geometry either way -- only the ink changes.
GLYPHS = {
    "classic": {"tl": TL, "tr": TR, "bl": BL, "br": BR, "h": H, "v": V, "ml": ML, "mr": MR, "hl": HL},
    "neo": {"tl": "╭", "tr": "╮", "bl": "╰", "br": "╯", "h": "─", "v": "│", "ml": "├", "mr": "┤", "hl": "─"},
}


@dataclass(frozen=True)
class Screen:
    """Where the picture lives inside the cabinet, in absolute screen cells."""
    cols: int          # full terminal
    rows: int
    x: int             # inner content origin (0-indexed, absolute)
    y: int
    width: int         # inner content size
    height: int
    framed: bool
    ox: int = 0        # cabinet origin (0-indexed, absolute)
    oy: int = 0
    cab_w: int = 0     # cabinet size
    cab_h: int = 0

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
        return Screen(cols, rows, 0, 0, cols, rows, framed=False,
                      cab_w=cols, cab_h=rows)
    cab_w = min(cols, MAX_COLS)
    cab_h = min(rows, MAX_ROWS)
    ox = (cols - cab_w) // 2
    oy = (rows - cab_h) // 2
    return Screen(cols, rows, ox + 2, oy + 3,
                  cab_w - CHROME_COLS, cab_h - CHROME_ROWS,
                  framed=True, ox=ox, oy=oy, cab_w=cab_w, cab_h=cab_h)


def inner_size(cols: int | None = None, rows: int | None = None) -> tuple[int, int]:
    g = geometry(cols, rows)
    return g.width, g.height


def title_bar(screen: Screen, title: str = "", right: str = "LAZSTATION 2",
              power: bool = True) -> str:
    """The text between the title row's two edges: LED + title, brand on the right."""
    span = screen.cab_w - 2
    led = "●" if power else "○"
    label = f" {led} {title.upper()}"[: span - len(right) - 2]
    return (label.ljust(span - len(right) - 1) + right + " ")[:span]


def frame_lines(screen: Screen, title: str = "", right: str = "LAZSTATION 2",
                power: bool = True, style: str = "classic") -> list[tuple[int, int, str]]:
    """The bezel as (y, x, text) runs -- rendered by ANSI or curses alike."""
    if not screen.framed:
        return []
    g = GLYPHS.get(style, GLYPHS["classic"])
    span = screen.cab_w - 2
    bar = title_bar(screen, title, right, power)
    ox, oy = screen.ox, screen.oy
    return [
        (oy, ox, g["tl"] + g["h"] * span + g["tr"]),
        (oy + 1, ox, g["v"] + bar + g["v"]),
        (oy + 2, ox, g["ml"] + g["hl"] * span + g["mr"]),
        (oy + screen.cab_h - 1, ox, g["bl"] + g["h"] * span + g["br"]),
    ]


def side_runs(screen: Screen, style: str = "classic") -> list[tuple[int, int, str]]:
    """The left and right cabinet edges for every content row."""
    if not screen.framed:
        return []
    v = GLYPHS.get(style, GLYPHS["classic"])["v"]
    runs = []
    for y in range(screen.oy + 3, screen.oy + screen.cab_h - 1):
        runs.append((y, screen.ox, v))
        runs.append((y, screen.ox + screen.cab_w - 1, v))
    return runs
