"""`ts new <slug>` -- generate a working game from a template."""
from __future__ import annotations

import re
from pathlib import Path

from . import paths

MANIFEST = '''[game]
name = "{title}"
slug = "{slug}"
version = "0.1.0"
author = "{author}"
description = """
{title} -- a TermStation game.

Edit games/{slug}/main.py and this description, then press r in the
console to see your changes."""
tags = [{tags}]
entry = ["{{python}}", "main.py"]
min_cols = 80
min_rows = 24
'''

MAIN = '''#!/usr/bin/env python3
"""{title} -- a LAZSTATION game."""
import sys

import termstation_sdk as ts


def main() -> int:
    # ts.tv() draws the CRT cabinet and keeps everything you print inside it.
    # Use ts.tv_print() instead of print() and ts.tv_clear() to wipe the
    # picture. Delete these two lines if you would rather run full screen.
    ts.tv("{title}")

    save = ts.load({{"plays": 0, "best": 0}})
    save["plays"] += 1

    ts.tv_print(ts.title("{title}"))
    ts.tv_print()
    ts.tv_print(f"  welcome back, {{ts.profile()}} -- visit #{{save['plays']}}")
    ts.tv_print()

    while True:
        choice = ts.menu("What now?", ["Play a round", "Show stats"], back="Quit")
        if choice == -1:
            break
        if choice == 0:
            score = ts.ask_int("pick a number 1-100", 1, 100)
            save["best"] = max(save["best"], score)
            ts.tv_print(ts.color(f"  scored {{score}}!", "bright_green"))
        elif choice == 1:
            ts.tv_print(ts.box([
                f" plays : {{save['plays']}}",
                f" best  : {{save['best']}}",
            ]))
        ts.tv_pause()
        ts.tv_clear()

    ts.save(save)
    ts.tv_print(ts.color("\\n  saved. see you on the station.", "cyan"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
'''

CURSES_MAIN = '''#!/usr/bin/env python3
"""{title} -- a full-screen LAZSTATION game."""
import curses
import sys

import termstation_sdk as ts


def run(stdscr) -> None:
    curses.curs_set(0)
    # tv_curses draws the cabinet on stdscr and hands back a window for the
    # picture. Draw into `win`; call it again after KEY_RESIZE.
    win, screen = ts.tv_curses(stdscr, "{title}")
    save = ts.load({{"plays": 0}})
    save["plays"] += 1
    x = screen.width // 2

    while True:
        win.erase()
        win.addstr(1, 2, "{title}", curses.A_BOLD)
        win.addstr(3, 2, f"visit #{{save['plays']}}  --  arrows to move, q to quit")
        win.addstr(screen.height // 2, x, "@")
        stdscr.noutrefresh()
        win.noutrefresh()
        curses.doupdate()

        key = win.getch()
        if key in (ord("q"), 27):
            break
        if key == curses.KEY_RESIZE:
            win, screen = ts.tv_curses(stdscr, "{title}")
            x = min(x, screen.width - 2)
        elif key == curses.KEY_LEFT:
            x = max(1, x - 1)
        elif key == curses.KEY_RIGHT:
            x = min(screen.width - 2, x + 1)

    ts.save(save)


def main() -> int:
    curses.wrapper(run)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
'''


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "untitled"


def titleize(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("_", "-").split("-") if w)


def create(name: str, target: Path | None = None, author: str = "",
           tags: list[str] | None = None, curses_game: bool = False) -> Path:
    slug = slugify(name)
    base = target or paths.BUNDLED_GAMES
    directory = base / slug
    if directory.exists():
        raise FileExistsError(f"{directory} already exists")

    title = titleize(slug)
    directory.mkdir(parents=True)
    tag_list = ", ".join(f'"{t}"' for t in (tags or ["wip"]))
    (directory / "game.toml").write_text(
        MANIFEST.format(title=title, slug=slug, author=author, tags=tag_list),
        encoding="utf-8")
    template = CURSES_MAIN if curses_game else MAIN
    main = directory / "main.py"
    main.write_text(template.format(title=title), encoding="utf-8")
    main.chmod(0o755)
    return directory
