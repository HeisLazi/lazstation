"""Power-on sequences, drawn on a bare terminal.

These run outside curses on purpose: the launcher must hand a clean TTY to
the child process, so boot composes on an fx Canvas and emits escape codes
rather than opening a curses session of its own.

Two sequences:
  console_boot()   once, when the console starts -- tube strike, logo, self test
  power_on(game)   before each game -- that game's own cover, name and colour
"""
from __future__ import annotations

import sys
import time

from . import brand, library, paths

sys.path.insert(0, str(paths.SDK_DIR))
import termstation_fx as fx                                      # noqa: E402
from termstation_bezel import frame_lines, geometry, side_runs   # noqa: E402

RESET = "\x1b[0m"
AMBER = fx.rgb(255, 176, 64)
DIMMED = fx.rgb(90, 84, 78)
PAPER = fx.rgb(236, 226, 205)


def _w(chunks) -> None:
    sys.stdout.write("".join(chunks))
    sys.stdout.flush()


def _at(y: int, x: int, text: str) -> str:
    return f"\x1b[{y + 1};{x + 1}H{text}"


def _ansi(color: int) -> str:
    return f"\x1b[38;5;{color}m"


def draw_cabinet(title: str = "", power: bool = True, color: int = AMBER,
                 right: str = brand.SHORT):
    screen = geometry()
    out = ["\x1b[2J\x1b[H", _ansi(color)]
    for y, x, text in frame_lines(screen, title, right=right, power=power):
        out.append(_at(y, x, text))
    for y, x, text in side_runs(screen):
        out.append(_at(y, x, text))
    out.append(RESET)
    _w(out)
    return screen


def _tube_strike(screen, step: float, color: int = AMBER) -> None:
    """A hairline of light that widens into a picture."""
    mid = screen.height // 2
    for i in range(mid + 1):
        band = fx.Canvas(screen.width, screen.height, ambient=0.0)
        for y in range(max(0, mid - i), min(screen.height, mid + i + 1)):
            closeness = 1.0 - abs(y - mid) / max(1, i)
            for x in range(screen.width):
                band.put(x, y, "─" if i < 2 else " ", color)
                band.lit[y * screen.width + x] = closeness
        _w([band.to_ansi(screen.x + 1, screen.y + 1)])
        time.sleep(0.011 * step)


def _fade_in(canvas: fx.Canvas, screen, step: float, frames: int = 12) -> None:
    for f in range(frames):
        lit = fx.fade_to(canvas, 1.0 - (f + 1) / frames)
        _w([lit.to_ansi(screen.x + 1, screen.y + 1)])
        time.sleep(0.02 * step)


def console_boot(fast: bool = False) -> None:
    """The console starting up: tube, logo, and a short self test."""
    step = 0.0 if fast else 1.0
    screen = geometry()
    sys.stdout.write("\x1b[?25l")
    try:
        draw_cabinet("", power=False, color=DIMMED)
        _tube_strike(screen, step)
        draw_cabinet("", power=True, color=AMBER)

        art = brand.logo(screen.width)
        canvas = fx.Canvas(screen.width, screen.height, ambient=0.0)
        art_w = max(len(line) for line in art)
        lx = max(0, (screen.width - art_w) // 2)
        ly = max(0, screen.height // 2 - len(art) // 2 - 3)
        for i, line in enumerate(art):
            canvas.text(lx, ly + i, line, AMBER)
        tag = brand.TAGLINE
        canvas.text(max(0, (screen.width - len(tag)) // 2), ly + len(art) + 1,
                    tag, DIMMED)
        _fade_in(canvas, screen, step)

        # a short self test, typed out like a machine checking itself
        games, problems = library.discover()
        try:
            import json
            awards = sum(len(v) for v in json.loads(
                paths.ACHIEVEMENTS.read_text(encoding="utf-8")).values())
        except Exception:
            awards = 0
        checks = [
            ("SYSTEM", "OK"),
            ("LIBRARY", f"{len(games)} GAME" + ("" if len(games) == 1 else "S")),
            ("SAVES", "READY"),
            ("AWARDS", str(awards)),
        ]
        if problems:
            checks.append(("MANIFESTS", f"{len(problems)} BAD"))

        base = ly + len(art) + 3
        for n, (label, value) in enumerate(checks):
            dots = "." * max(3, 22 - len(label) - len(value))
            line = f"{label} {dots} {value}"
            x = max(0, (screen.width - len(line)) // 2)
            _w([_ansi(DIMMED), _at(screen.y + base + n, screen.x + x, label + " " + dots),
                _ansi(PAPER), " " + value, RESET])
            time.sleep(0.13 * step)
        time.sleep(0.25 * step)
    finally:
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()


def power_on(game, fast: bool = False) -> None:
    """A game's own loading screen: its cover, its name, its colour."""
    step = 0.0 if fast else 1.0
    screen = geometry()
    name = getattr(game, "name", str(game))
    tone = fx.rgb(*library.accent_for(game)) if hasattr(game, "slug") else AMBER
    sys.stdout.write("\x1b[?25l")
    try:
        draw_cabinet("", power=False, color=DIMMED)
        _tube_strike(screen, step * 0.6, tone)
        draw_cabinet(name, power=True, color=tone)

        art = library.load_cover(game) if hasattr(game, "root") else []
        canvas = fx.Canvas(screen.width, screen.height, ambient=0.0)
        art_w = max((len(a) for a in art), default=0)
        ax = max(0, (screen.width - art_w) // 2)
        ay = max(1, screen.height // 2 - len(art) // 2 - 2)
        for i, line in enumerate(art):
            canvas.text(ax, ay + i, line, tone)

        title = name.upper()
        canvas.text(max(0, (screen.width - len(title)) // 2),
                    ay + len(art) + 1, title, PAPER)
        tag = getattr(game, "tagline", "")[: screen.width - 4]
        if tag:
            canvas.text(max(0, (screen.width - len(tag)) // 2),
                        ay + len(art) + 2, tag, DIMMED)
        canvas.add_light(screen.width // 2, ay + len(art) // 2,
                         max(10, art_w), 0.5)
        _fade_in(canvas, screen, step, frames=10)

        width = min(34, screen.width - 6)
        bx = screen.x + max(0, (screen.width - width) // 2)
        by = screen.y + min(screen.height - 2, ay + len(art) + 4)
        _w([_ansi(DIMMED), _at(by, bx, "░" * width), RESET])
        for i in range(width + 1):
            _w([_ansi(tone), _at(by, bx, "█" * i), RESET])
            time.sleep(0.009 * step)
        time.sleep(0.1 * step)
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
                _w([_ansi(PAPER), _at(mid, screen.x, "─" * screen.width), RESET])
            time.sleep(0.011)
        _w([_ansi(PAPER), _at(mid, screen.x + screen.width // 2, "·"), RESET])
        time.sleep(0.12)
        _w(["\x1b[2J\x1b[H"])
    finally:
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()
