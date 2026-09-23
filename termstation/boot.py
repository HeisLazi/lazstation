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
import termstation_fx as fx                                      # noqa: E402
from termstation_bezel import frame_lines, geometry, side_runs   # noqa: E402

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
    """A cathode tube warming up: a hairline of light widens into a picture,
    the logo burns in, then the game loads. About 1.5s, skippable."""
    step = 0.0 if fast else 1.0
    screen = geometry()
    sys.stdout.write("\x1b[?25l")
    try:
        art = brand.logo(screen.width)
        canvas = fx.Canvas(screen.width, screen.height, ambient=0.0)
        art_w = max(len(line) for line in art)
        lx = max(0, (screen.width - art_w) // 2)
        ly = max(0, screen.height // 2 - len(art) // 2 - 2)
        for i, line in enumerate(art):
            canvas.text(lx, ly + i, line, fx.rgb(120, 220, 235))
        tag = brand.TAGLINE
        canvas.text(max(0, (screen.width - len(tag)) // 2), ly + len(art) + 1,
                    tag, fx.rgb(150, 150, 160))

        # 1. the tube strikes: a bright line across the middle, widening
        mid = screen.height // 2
        draw_cabinet("", power=False, color=DIM)
        for i in range(mid + 1):
            band = fx.Canvas(screen.width, screen.height, ambient=0.0)
            for y in range(max(0, mid - i), min(screen.height, mid + i + 1)):
                closeness = 1.0 - abs(y - mid) / max(1, i)
                for x in range(screen.width):
                    band.put(x, y, "─" if i < 2 else " ", fx.rgb(200, 240, 255))
                    band.lit[y * screen.width + x] = closeness
            _w([band.to_ansi(screen.x + 1, screen.y + 1)])
            time.sleep(0.012 * step)

        # 2. the logo burns in
        draw_cabinet(game_name, power=True, color=CYAN)
        for f in range(14):
            lit = fx.fade_to(canvas, 1.0 - (f + 1) / 14)
            _w([lit.to_ansi(screen.x + 1, screen.y + 1)])
            time.sleep(0.02 * step)

        # 3. loading
        label = f"LOADING  {game_name.upper()}"[: screen.width - 2]
        ly2 = ly + len(art) + 3
        _w([GOLD, _at(screen.y + ly2, screen.x + max(0, (screen.width - len(label)) // 2),
                      label), RESET])
        width = min(30, screen.width - 4)
        bx = screen.x + max(0, (screen.width - width) // 2)
        for i in range(width + 1):
            _w([CYAN, _at(screen.y + ly2 + 2, bx, "█" * i), RESET])
            time.sleep(0.010 * step)
        time.sleep(0.12 * step)
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
