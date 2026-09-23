#!/usr/bin/env python3
"""Unbound -- a full-screen LAZSTATION game."""
import curses
import sys

import termstation_sdk as ts


def run(stdscr) -> None:
    curses.curs_set(0)
    # tv_curses draws the cabinet on stdscr and hands back a window for the
    # picture. Draw into `win`; call it again after KEY_RESIZE.
    win, screen = ts.tv_curses(stdscr, "Unbound")
    save = ts.load({"plays": 0})
    save["plays"] += 1
    x = screen.width // 2

    while True:
        win.erase()
        win.addstr(1, 2, "Unbound", curses.A_BOLD)
        win.addstr(3, 2, f"visit #{save['plays']}  --  arrows to move, q to quit")
        win.addstr(screen.height // 2, x, "@")
        stdscr.noutrefresh()
        win.noutrefresh()
        curses.doupdate()

        key = win.getch()
        if key in (ord("q"), 27):
            break
        if key == curses.KEY_RESIZE:
            win, screen = ts.tv_curses(stdscr, "Unbound")
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
