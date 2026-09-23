"""The power-on sequence played inside the bezel before a game starts.

Runs on the bare terminal between the launcher's curses teardown and the
child process, using the same geometry the game will draw with -- so the
cabinet stays put and only the picture changes.
"""
from __future__ import annotations

import sys
import time

from . import brand, paths

sys.path.insert(0, str(paths.SDK_DIR))
from termstation_bezel import frame_lines, geometry, side_runs  # noqa: E402

DIM, CYAN, WHITE, GOLD, RESET = "\x1b[90m", "\x1b[96m", "\x1b[97m", "\x1b[93m", "\x1b[0m"




def _at(y: int, x: int, text: str) -> str:
    return f"\x1b[{y + 1};{x + 1}H{text}"


def _w(chunks) -> None:
    sys.stdout.write("".join(chunks))
    sys.stdout.flush()


def draw_cabinet(title: str = "", power: bool = True, color: str = CYAN,
                 right: str = brand.SHORT) -> object:
    screen = geometry()
    out = ["\x1b[2J\x1b[H", color]
    for y, x, text in frame_lines(screen, title, right=right, power=power):
        out.append(_at(y, x, text))
    for y, x, text in side_runs(screen):
        out.append(_at(y, x, text))
    out.append(RESET)
    _w(out)
    return screen


def power_on(game_name: str, fast: bool = False) -> None:
    """Scanline sweep, logo, then the loading line. ~1.4s, skippable."""
    step = 0.0 if fast else 1.0
    sys.stdout.write("\x1b[?25l")  # hide cursor for the animation
    try:
        screen = draw_cabinet("", power=False, color=DIM)
        time.sleep(0.10 * step)

        # scanline sweep down the picture
        blank = " " * screen.width
        for i in range(screen.height):
            _w([DIM, _at(screen.y + i, screen.x, "▔" * screen.width), RESET])
            if i:
                _w([_at(screen.y + i - 1, screen.x, blank)])
            time.sleep(0.012 * step)
        _w([_at(screen.y + screen.height - 1, screen.x, blank)])

        # cabinet comes alive
        draw_cabinet(game_name, power=True, color=CYAN)

        # logo, centred as a block -- centring each line would shear it
        art = brand.logo(screen.width)
        top = screen.y + max(1, (screen.height - len(art)) // 2 - 2)
        art_w = max(len(line) for line in art)
        lx = screen.x + max(0, (screen.width - art_w) // 2)
        for i, line in enumerate(art):
            _w([CYAN, _at(top + i, lx, line), RESET])
            time.sleep(0.05 * step)

        tag = brand.TAGLINE
        _w([DIM, _at(top + len(art) + 1,
                     screen.x + max(0, (screen.width - len(tag)) // 2), tag), RESET])
        time.sleep(0.25 * step)

        # loading line
        label = f"LOADING  {game_name.upper()}"[: screen.width - 2]
        ly = top + len(art) + 3
        lx = screen.x + max(0, (screen.width - len(label)) // 2)
        _w([GOLD, _at(ly, lx, label), RESET])

        width = min(30, screen.width - 4)
        bx = screen.x + max(0, (screen.width - width) // 2)
        _w([DIM, _at(ly + 2, bx, "░" * width), RESET])
        for i in range(width + 1):
            _w([CYAN, _at(ly + 2, bx, "█" * i), RESET])
            time.sleep(0.010 * step)
        time.sleep(0.15 * step)
    finally:
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()


def power_off() -> None:
    """CRT collapse: the picture folds to a line, then a dot."""
    screen = geometry()
    sys.stdout.write("\x1b[?25l")
    try:
        mid = screen.y + screen.height // 2
        blank = " " * screen.width
        for step in range(screen.height // 2):
            top, bot = screen.y + step, screen.y + screen.height - 1 - step
            _w([_at(top, screen.x, blank), _at(bot, screen.x, blank)])
            if top < mid:
                _w([WHITE, _at(mid, screen.x, "─" * screen.width), RESET])
            time.sleep(0.012)
        _w([WHITE, _at(mid, screen.x + screen.width // 2, "·"), RESET])
        time.sleep(0.12)
        _w(["\x1b[2J\x1b[H"])
    finally:
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()
