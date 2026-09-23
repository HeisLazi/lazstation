"""The console front-end: a curses library browser.

The curses session is torn down completely before a game is launched -- the
loop returns an action, the caller runs the game on a bare terminal, then a
fresh curses session starts. That full handoff is why a curses game launched
from this curses launcher still receives its keystrokes.
"""
from __future__ import annotations

import curses
import sys
from dataclasses import dataclass

from . import brand, library, paths
from .library import Game

sys.path.insert(0, str(paths.SDK_DIR))
from termstation_bezel import frame_lines, geometry, side_runs  # noqa: E402



C_TITLE, C_SEL, C_DIM, C_ACCENT, C_BAD, C_GOOD = 1, 2, 3, 4, 5, 6


@dataclass
class Action:
    kind: str  # "launch" | "quit"
    game: Game | None = None
    profile: str = "default"


class Console:
    def __init__(self, profile: str = "default") -> None:
        self.profile = profile
        self.index = 0
        self.filter = ""
        self.message = ""
        self.searching = False
        self.has_color = False
        self.fast_boot = False
        self.screen = geometry()
        self.refresh_library()

    # ---------------------------------------------------------------- data
    def refresh_library(self) -> None:
        self.all_games, self.problems = library.discover()
        self.stats = library.load_stats()
        self.index = min(self.index, max(0, len(self.visible) - 1))

    @property
    def visible(self) -> list[Game]:
        if not self.filter:
            return self.all_games
        needle = self.filter.lower()
        return [g for g in self.all_games
                if needle in g.name.lower() or needle in g.slug.lower()
                or any(needle in t.lower() for t in g.tags)]

    @property
    def current(self) -> Game | None:
        games = self.visible
        return games[self.index] if games and 0 <= self.index < len(games) else None

    def stat(self, game: Game) -> dict:
        return self.stats.get(game.slug, {})

    # ---------------------------------------------------------------- colours
    @staticmethod
    def _init_colors() -> bool:
        if not curses.has_colors():
            return False
        curses.start_color()
        try:
            curses.use_default_colors()
            bg = -1
        except curses.error:
            bg = curses.COLOR_BLACK
        curses.init_pair(C_TITLE, curses.COLOR_CYAN, bg)
        curses.init_pair(C_SEL, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(C_DIM, curses.COLOR_WHITE, bg)
        curses.init_pair(C_ACCENT, curses.COLOR_YELLOW, bg)
        curses.init_pair(C_BAD, curses.COLOR_RED, bg)
        curses.init_pair(C_GOOD, curses.COLOR_GREEN, bg)
        return True

    def attr(self, pair: int, bold: bool = False) -> int:
        if not self.has_color:
            return curses.A_BOLD if bold else curses.A_NORMAL
        a = curses.color_pair(pair)
        return a | curses.A_BOLD if bold else a

    # ---------------------------------------------------------------- drawing
    def _put(self, win, y: int, x: int, text: str, attr: int = curses.A_NORMAL) -> None:
        """Write in picture coordinates -- offset into the bezel, clipped to it."""
        screen = self.screen
        rows, cols = win.getmaxyx()
        if y < 0 or y >= screen.height or x >= screen.width:
            return
        ay, ax = y + screen.y, x + screen.x
        if ay >= rows:
            return
        room = min(screen.width - x, cols - ax - 1)
        try:
            win.addnstr(ay, ax, text, max(0, room), attr)
        except curses.error:
            pass

    def _draw_cabinet(self, stdscr) -> None:
        """Paint the bezel on the raw screen, last cell included."""
        if not self.screen.framed:
            return
        rows, cols = stdscr.getmaxyx()
        attr = self.attr(C_TITLE, bold=True)

        def edge(y: int, x: int, text: str) -> None:
            if y >= rows or x >= cols:
                return
            head, tail = text[: cols - x - 1], text[cols - x - 1 : cols - x]
            try:
                if head:
                    stdscr.addnstr(y, x, head, len(head), attr)
                # insstr reaches the final column without advancing the cursor
                if tail:
                    stdscr.insstr(y, cols - 1, tail, attr)
            except curses.error:
                pass

        for y, x, text in frame_lines(self.screen, brand.NAME, right="CONSOLE"):
            edge(y, x, text)
        for y, x, text in side_runs(self.screen):
            edge(y, x, text)

    def draw(self, stdscr) -> None:
        stdscr.erase()
        term_rows, term_cols = stdscr.getmaxyx()
        self.screen = geometry(term_cols, term_rows)
        self._draw_cabinet(stdscr)
        rows, cols = self.screen.height, self.screen.width
        split = max(24, min(32, cols // 2 - 4))

        # --- header
        y = 0
        if rows >= 16 and cols >= 40:
            banner = brand.LOGO_SMALL
            for i, line in enumerate(banner):
                self._put(stdscr, i, 2, line, self.attr(C_TITLE, bold=True))
            y = len(banner)
        else:
            self._put(stdscr, 0, 2, brand.NAME, self.attr(C_TITLE, bold=True))
            y = 1
        meta = f"profile: {self.profile}   games: {len(self.all_games)}"
        self._put(stdscr, max(0, y - 1), max(2, cols - len(meta) - 1), meta,
                  self.attr(C_DIM))
        self._put(stdscr, y, 0, "─" * cols, self.attr(C_DIM))

        list_top = y + 1
        list_bottom = rows - 2
        height = max(1, list_bottom - list_top)

        # --- game list
        games = self.visible
        if not games:
            empty = "no games found" if not self.filter else f"nothing matches '{self.filter}'"
            self._put(stdscr, list_top + 1, 3, empty, self.attr(C_BAD))
            self._put(stdscr, list_top + 3, 3, "add one with:", self.attr(C_DIM))
            self._put(stdscr, list_top + 4, 3, "lazstation new my-game", self.attr(C_ACCENT))
        else:
            self.index = max(0, min(self.index, len(games) - 1))
            start = max(0, min(self.index - height // 2, len(games) - height))
            for row, game in enumerate(games[start:start + height]):
                gy = list_top + row
                selected = (start + row) == self.index
                played = self.stat(game).get("seconds", 0)
                mark = "▸" if selected else " "
                name = game.name[:split - 12]
                time_tag = library.format_playtime(played) if played else ""
                line = f" {mark} {name}".ljust(split - len(time_tag) - 2) + time_tag + " "
                if selected:
                    self._put(stdscr, gy, 0, line.ljust(split), self.attr(C_SEL, bold=True))
                else:
                    self._put(stdscr, gy, 0, line, self.attr(C_DIM))

        # --- divider
        for gy in range(list_top, list_bottom):
            self._put(stdscr, gy, split, "│", self.attr(C_DIM))

        # --- detail pane
        game = self.current
        dx = split + 2
        dw = max(10, cols - dx - 1)
        if game:
            st = self.stat(game)
            self._put(stdscr, list_top, dx, game.name[:dw], self.attr(C_TITLE, bold=True))
            sub = f"v{game.version}" + (f" · {game.author}" if game.author else "")
            self._put(stdscr, list_top + 1, dx, sub[:dw], self.attr(C_DIM))
            dy = list_top + 3
            for line in _wrap(game.description.strip(), dw):
                if dy >= list_bottom - 6:
                    break
                self._put(stdscr, dy, dx, line, self.attr(C_DIM))
                dy += 1
            if game.tags and dy + 1 < list_bottom - 4:
                dy += 1
                self._put(stdscr, dy, dx, ("· " + "  · ".join(game.tags))[:dw],
                          self.attr(C_ACCENT))
            info = [
                f"played    {st.get('launches', 0)}x",
                f"playtime  {library.format_playtime(st.get('seconds', 0))}",
                f"last      {library.format_last_played(st.get('last_played'))}",
            ]
            for i, line in enumerate(info):
                self._put(stdscr, list_bottom - 4 + i, dx, line, self.attr(C_DIM))
            if st.get("last_exit") not in (None, 0, 130):
                self._put(stdscr, list_bottom - 1, dx,
                          f"! last run exited {st['last_exit']}", self.attr(C_BAD))
            elif not game.fits(term_cols, term_rows):
                self._put(stdscr, list_bottom - 1, dx,
                          f"! wants {game.min_cols}x{game.min_rows}", self.attr(C_ACCENT))

        # --- footer
        self._put(stdscr, rows - 2, 0, "─" * cols, self.attr(C_DIM))
        if self.filter is not None and self.searching:
            bar = f"search: {self.filter}_"
            self._put(stdscr, rows - 1, 1, bar, self.attr(C_ACCENT, bold=True))
        elif self.message:
            self._put(stdscr, rows - 1, 1, self.message[:cols - 2], self.attr(C_GOOD))
        else:
            keys = "↑↓ move  ⏎ play  / search  p profile  b boot-fx  r refresh  q quit"
            if self.problems:
                keys = f"! {len(self.problems)} broken manifest(s)   " + keys
            self._put(stdscr, rows - 1, 1, keys[:cols - 2], self.attr(C_DIM))
        stdscr.noutrefresh()
        curses.doupdate()

    # ---------------------------------------------------------------- loop
    def loop(self, stdscr) -> Action:
        curses.curs_set(0)
        stdscr.keypad(True)
        self.has_color = self._init_colors()
        self.searching = False

        while True:
            self.draw(stdscr)
            try:
                key = stdscr.getch()
            except KeyboardInterrupt:
                return Action("quit")

            if key == curses.KEY_RESIZE:
                continue

            if self.searching:
                if key in (10, 13, curses.KEY_ENTER, 27):
                    self.searching = False
                    if key == 27:
                        self.filter = ""
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    self.filter = self.filter[:-1]
                elif 32 <= key < 127:
                    self.filter += chr(key)
                    self.index = 0
                continue

            self.message = ""
            games = self.visible

            if key in (ord("q"), ord("Q")):
                return Action("quit")
            if key in (curses.KEY_UP, ord("k")) and games:
                self.index = (self.index - 1) % len(games)
            elif key in (curses.KEY_DOWN, ord("j")) and games:
                self.index = (self.index + 1) % len(games)
            elif key in (curses.KEY_HOME, ord("g")):
                self.index = 0
            elif key in (curses.KEY_END, ord("G")) and games:
                self.index = len(games) - 1
            elif key in (10, 13, curses.KEY_ENTER, ord(" ")):
                game = self.current
                if game:
                    return Action("launch", game, self.profile)
            elif key == ord("/"):
                self.searching = True
                self.filter = ""
            elif key == 27:
                self.filter = ""
            elif key in (ord("r"), ord("R")):
                self.refresh_library()
                self.message = "library refreshed"
            elif key in (ord("p"), ord("P")):
                self.profile = _prompt_profile(stdscr, self.profile, self)
            elif key in (ord("b"), ord("B")):
                self.fast_boot = not self.fast_boot
                self.message = "boot animation " + ("off" if self.fast_boot else "on")
            elif key == ord("?"):
                _help_screen(stdscr, self)


def _wrap(text: str, width: int) -> list[str]:
    out: list[str] = []
    for para in text.splitlines():
        if not para.strip():
            out.append("")
            continue
        line = ""
        for word in para.split():
            if len(line) + len(word) + 1 > width:
                out.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        out.append(line)
    return out


def _prompt_profile(stdscr, current: str, console: Console) -> str:
    rows, cols = console.screen.height, console.screen.width
    curses.echo()
    curses.curs_set(1)
    console._put(stdscr, rows - 1, 1, " " * (cols - 2), console.attr(C_DIM))
    console._put(stdscr, rows - 1, 1, "profile name: ", console.attr(C_ACCENT, bold=True))
    stdscr.refresh()
    try:
        raw = stdscr.getstr(console.screen.y + rows - 1,
                            console.screen.x + 15, 24).decode("utf-8", "replace").strip()
    except Exception:
        raw = ""
    curses.noecho()
    curses.curs_set(0)
    name = "".join(c for c in raw if c.isalnum() or c in "-_") or current
    (paths.SAVES / name).mkdir(parents=True, exist_ok=True)
    console.message = f"profile: {name}"
    return name


def _help_screen(stdscr, console: Console) -> None:
    lines = [
        brand.NAME,
        "",
        "  ↑/↓ or j/k    move through the library",
        "  enter         launch the selected game",
        "  /             filter by name or tag      esc clears",
        "  p             switch save profile",
        "  r             rescan for newly added games",
        "  q             power off",
        "",
        "  add a game:   lazstation new <slug>   then edit games/<slug>/main.py",
        "  save data:    ~/.local/share/termstation/saves/<profile>/<slug>/",
        "",
        "  press any key to go back",
    ]
    stdscr.erase()
    console._draw_cabinet(stdscr)
    for i, line in enumerate(lines):
        attr = console.attr(C_TITLE, bold=True) if i == 0 else console.attr(C_DIM)
        console._put(stdscr, i + 1, 3, line, attr)
    stdscr.refresh()
    stdscr.getch()
