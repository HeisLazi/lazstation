"""The console front-end: a horizontal carousel of game covers.

Shaped like a living-room console dashboard -- one big cover in the middle,
its neighbours shrinking away to either side, sliding as you move. The retro
half is the treatment: amber phosphor, scanlines across the picture, a warm
glow pooling around whatever is selected, and a faint flicker, all applied by
the fx layer after the frame is composed.

Curses is torn down completely before a game launches (see cli.run_console),
so this never fights a child process for the terminal.
"""
from __future__ import annotations

import curses
import sys
import time

from . import brand, library, paths
from .library import Game

sys.path.insert(0, str(paths.SDK_DIR))
import termstation_fx as fx                              # noqa: E402
from termstation_bezel import frame_lines, geometry, side_runs  # noqa: E402

FPS = 30
PITCH = 22              # horizontal distance between cover centres
SLIDE_TIME = 0.20

AMBER = fx.rgb(255, 176, 64)
AMBER_DIM = fx.rgb(150, 96, 30)
CYAN = fx.rgb(120, 220, 230)
PAPER = fx.rgb(236, 226, 205)
INK = fx.rgb(120, 112, 100)
GLOW = fx.rgb(255, 210, 120)


class Action:
    def __init__(self, kind: str, game: Game | None = None,
                 profile: str = "default", slot: int = 1) -> None:
        self.kind, self.game, self.profile, self.slot = kind, game, profile, slot


def load_cover(game: Game) -> list[str]:
    """A game's cover art, or a generated one if it ships none."""
    path = game.root / "cover.txt"
    try:
        lines = path.read_text(encoding="utf-8").rstrip("\n").splitlines()
        if lines:
            return lines[:8]
    except OSError:
        pass
    # Procedural fallback: a stable pattern from the slug, so a game without
    # art still gets something of its own rather than a blank square.
    seed = sum(ord(c) * (i + 3) for i, c in enumerate(game.slug))
    glyphs = "░▒▓█▚▞"
    rows = []
    for y in range(6):
        row = ""
        for x in range(11):
            row += glyphs[(seed + x * 7 + y * 13) % len(glyphs)]
        rows.append(row)
    return rows


class Console:
    def __init__(self, profile: str = "default") -> None:
        self.profile = profile
        self.index = 0
        self.scroll = 0.0
        self.filter = ""
        self.searching = False
        self.message = ""
        self.msg_until = 0.0
        self.fast_boot = False
        self.covers: dict[str, list[str]] = {}
        self.flicker = 1.0
        self.slots: dict[str, int] = {}
        self.refresh_library()

    # ------------------------------------------------------------- data
    def refresh_library(self) -> None:
        self.all_games, self.problems = library.discover()
        self.stats = library.load_stats()
        self.covers = {g.slug: load_cover(g) for g in self.all_games}
        self.index = min(self.index, max(0, len(self.visible) - 1))
        self.scroll = float(self.index)

    @property
    def visible(self) -> list[Game]:
        if not self.filter:
            return self.all_games
        n = self.filter.lower()
        return [g for g in self.all_games
                if n in g.name.lower() or n in g.slug.lower()
                or any(n in t.lower() for t in g.tags)]

    @property
    def current(self) -> Game | None:
        games = self.visible
        return games[self.index] if games and 0 <= self.index < len(games) else None

    def say(self, text: str, seconds: float = 2.0) -> None:
        self.message = text
        self.msg_until = time.monotonic() + seconds

    # ------------------------------------------------------------- drawing
    def cover_tile(self, canvas: fx.Canvas, game: Game, cx: int, cy: int,
                   closeness: float) -> None:
        """One cover. `closeness` is 1 at the centre and 0 far out."""
        w = int(14 + 8 * closeness)
        h = int(7 + 4 * closeness)
        x = cx - w // 2
        y = cy - h // 2
        if x + w < 0 or x > canvas.w:
            return

        bright = 0.35 + 0.65 * closeness
        edge = fx.scale(AMBER if closeness > 0.55 else AMBER_DIM, bright)
        canvas.fill(x + 1, y + 1, w - 2, h - 2, " ", PAPER)
        canvas.box(x, y, w, h, edge)

        art = self.covers.get(game.slug, [])
        art_w = max((len(a) for a in art), default=0)
        ax = x + (w - art_w) // 2
        ay = y + (h - len(art)) // 2
        tint = fx.mix(INK, AMBER, closeness * 0.7)
        for row, line in enumerate(art):
            if y < ay + row < y + h - 1:
                canvas.text(ax, ay + row, line[:w - 2], fx.scale(tint, bright))

        # Name plate under the cover -- skipped for the selected one, whose
        # name is already shown large beneath the carousel.
        if closeness <= 0.9:
            label = game.name[:w + 2]
            canvas.text(cx - len(label) // 2, y + h, label,
                        fx.scale(INK, 0.5 + 0.5 * closeness))

        if closeness > 0.9:
            canvas.add_light(cx, cy, max(w, h) * 0.8, 0.55)

    def compose(self, width: int, height: int) -> fx.Canvas:
        canvas = fx.Canvas(width, height, ambient=0.92)
        games = self.visible

        head = f"{brand.NAME}"
        canvas.text(1, 0, head, AMBER)
        meta = f"{self.profile}   {len(self.all_games)} games"
        canvas.text(max(1, width - len(meta) - 1), 0, meta, INK)

        row_y = 7
        if not games:
            msg = "no games found" if not self.filter else f"nothing matches '{self.filter}'"
            canvas.text(max(1, (width - len(msg)) // 2), row_y, msg, AMBER)
            canvas.text(max(1, (width - 22) // 2), row_y + 2,
                        "lazstation new my-game", INK)
        else:
            centre = width // 2
            for i, game in enumerate(games):
                dist = abs(i - self.scroll)
                if dist > 2.6:
                    continue
                closeness = max(0.0, 1.0 - dist)
                cx = int(centre + (i - self.scroll) * PITCH)
                self.cover_tile(canvas, game, cx, row_y, closeness)

            game = self.current
            if game:
                st = self.stats.get(game.slug, {})
                name = game.name.upper()
                canvas.text(max(1, (width - len(name)) // 2), 13,
                            name, GLOW)
                room = width - 6
                tag = game.tagline
                if len(tag) > room:
                    tag = tag[:room - 1].rsplit(" ", 1)[0] + "…"
                canvas.text(max(1, (width - len(tag)) // 2), 14, tag, PAPER)
                bits = []
                if st.get("launches"):
                    n = st["launches"]
                    bits.append(f"{n} play" + ("" if n == 1 else "s"))
                    bits.append(library.format_playtime(st.get("seconds", 0)))
                    bits.append(library.format_last_played(st.get("last_played")))
                else:
                    bits.append("never played")
                if game.tags:
                    bits.append(" ".join(f"·{t}" for t in game.tags))
                line = "    ".join(bits)
                canvas.text(max(1, (width - len(line)) // 2), 15, line, INK)

                chosen = self.slots.get(game.slug, 1)
                used = paths.slots_used(self.profile, game.slug)
                marks = []
                for n, taken in enumerate(used, 1):
                    glyph = "▣" if taken else "▢"
                    marks.append(f"{glyph}{n}" if n != chosen else f"[{glyph}{n}]")
                slot_line = "slot  " + " ".join(marks)
                canvas.text(max(1, (width - len(slot_line)) // 2), 16,
                            slot_line, AMBER if chosen != 1 else INK)

                # position dots, like a console dashboard
                dots = "".join("◆" if i == self.index else "◇"
                               for i in range(len(games)))
                canvas.text(max(1, (width - len(dots)) // 2), 17, dots, AMBER_DIM)

        if self.searching:
            bar = f"search: {self.filter}_"
            canvas.text(1, height - 1, bar, GLOW)
        elif self.message and time.monotonic() < self.msg_until:
            canvas.text(1, height - 1, self.message[:width - 2], CYAN)
        else:
            hint = ("← →  select   ⏎ play   1-3 slot   a awards   "
                    "/ find   p profile   ? help   q off")
            canvas.text(max(1, (width - len(hint)) // 2), height - 1, hint, INK)
        return canvas

    def crt(self, canvas: fx.Canvas) -> None:
        """Scanlines, vignette and a little flicker -- applied to light only,
        so it dims the picture without touching what is drawn."""
        for y in range(canvas.h):
            scan = 0.80 if y % 2 else 1.0
            for x in range(canvas.w):
                i = y * canvas.w + x
                edge = 1.0 - 0.22 * abs(x - canvas.w / 2) / (canvas.w / 2)
                canvas.lit[i] *= scan * edge * self.flicker

    # ------------------------------------------------------------- frame
    def render(self, stdscr) -> None:
        rows, cols = stdscr.getmaxyx()
        self.screen = geometry(cols, rows)
        stdscr.erase()
        self.draw_cabinet(stdscr)
        canvas = self.compose(self.screen.width, self.screen.height)
        self.crt(canvas)
        canvas.blit(stdscr, self.palette, self.screen.x, self.screen.y)
        stdscr.noutrefresh()
        curses.doupdate()

    def draw_cabinet(self, stdscr) -> None:
        if not self.screen.framed:
            return
        rows, cols = stdscr.getmaxyx()
        attr = self.palette.pair(AMBER_DIM)

        def edge(y: int, x: int, text: str) -> None:
            if y >= rows or x >= cols:
                return
            try:
                if x + len(text) < cols:
                    stdscr.addnstr(y, x, text, len(text), attr)
                    return
                head, tail = text[: cols - x - 1], text[cols - x - 1: cols - x]
                if head:
                    stdscr.addnstr(y, x, head, len(head), attr)
                if tail:
                    stdscr.insstr(y, cols - 1, tail, attr)
            except curses.error:
                pass

        for y, x, text in frame_lines(self.screen, brand.NAME, right="CONSOLE"):
            edge(y, x, text)
        for y, x, text in side_runs(self.screen):
            edge(y, x, text)

    def slide_to(self, stdscr, target: int) -> None:
        """Animate the carousel rather than snapping: the motion is what
        tells you which way you moved."""
        tween = fx.Tween(self.scroll, float(target), SLIDE_TIME, fx.ease_out)
        last = time.monotonic()
        stdscr.nodelay(True)
        while not tween.done:
            now = time.monotonic()
            dt = min(0.05, now - last)
            last = now
            self.scroll = tween.update(dt)
            self.render(stdscr)
            time.sleep(1 / FPS)
        stdscr.nodelay(False)
        self.scroll = float(target)
        self.index = target

    # ------------------------------------------------------------- loop
    def loop(self, stdscr) -> Action:
        curses.curs_set(0)
        stdscr.keypad(True)
        self.palette = fx.Palette(curses)
        self.screen = geometry(*reversed(stdscr.getmaxyx()))

        while True:
            self.render(stdscr)
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
                    self.index = 0
                    self.scroll = 0.0
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    self.filter = self.filter[:-1]
                elif 32 <= key < 127:
                    self.filter += chr(key)
                    self.index = 0
                    self.scroll = 0.0
                continue

            games = self.visible
            if key in (ord("q"), ord("Q")):
                return Action("quit")
            if key in (curses.KEY_LEFT, ord("h"), ord("a")) and games:
                self.slide_to(stdscr, (self.index - 1) % len(games))
            elif key in (curses.KEY_RIGHT, ord("l"), ord("d")) and games:
                self.slide_to(stdscr, (self.index + 1) % len(games))
            elif key in (curses.KEY_HOME, ord("g")) and games:
                self.slide_to(stdscr, 0)
            elif key in (curses.KEY_END, ord("G")) and games:
                self.slide_to(stdscr, len(games) - 1)
            elif key in (10, 13, curses.KEY_ENTER, ord(" ")):
                game = self.current
                if game:
                    return Action("launch", game, self.profile,
                                  self.slots.get(game.slug, 1))
            elif key == ord("/"):
                self.searching = True
                self.filter = ""
            elif key in (ord("r"), ord("R")):
                self.refresh_library()
                self.say("library refreshed")
            elif key in (ord("b"), ord("B")):
                self.fast_boot = not self.fast_boot
                self.say("boot animation " + ("off" if self.fast_boot else "on"))
            elif key in (ord("p"), ord("P")):
                self.profile = self.ask_profile(stdscr)
            elif key in (ord("1"), ord("2"), ord("3")) and games:
                game = self.current
                if game:
                    self.slots[game.slug] = key - ord("0")
                    self.say(f"slot {key - ord('0')} selected")
            elif key in (ord("a"), ord("A")):
                self.achievements_screen(stdscr)
            elif key == ord("?"):
                self.help_screen(stdscr)

    # ------------------------------------------------------------- screens
    def ask_profile(self, stdscr) -> str:
        rows, cols = stdscr.getmaxyx()
        y = self.screen.y + self.screen.height - 1
        curses.echo()
        curses.curs_set(1)
        try:
            stdscr.addnstr(y, self.screen.x + 1, "profile name: ".ljust(
                self.screen.width - 2), self.screen.width - 2,
                self.palette.pair(GLOW))
            raw = stdscr.getstr(y, self.screen.x + 15, 20).decode("utf-8", "replace")
        except Exception:
            raw = ""
        curses.noecho()
        curses.curs_set(0)
        name = "".join(c for c in raw.strip() if c.isalnum() or c in "-_")
        if not name:
            return self.profile
        (paths.SAVES / name).mkdir(parents=True, exist_ok=True)
        self.say(f"profile: {name}")
        return name

    def achievements_screen(self, stdscr) -> None:
        """Everything unlocked, across every game."""
        import json
        try:
            data = json.loads(paths.ACHIEVEMENTS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        names = {g.slug: g.name for g in self.all_games}

        lines: list[tuple[str, int]] = [("AWARDS", GLOW), ("", INK)]
        total = sum(len(v) for v in data.values())
        if not total:
            lines += [("  Nothing unlocked yet.", PAPER), ("", INK),
                      ("  Games award these as you play.", INK)]
        else:
            lines.append((f"  {total} unlocked", INK))
            lines.append(("", INK))
            for slug, got in sorted(data.items()):
                lines.append((f"  {names.get(slug, slug)}", AMBER))
                for key, meta in sorted(got.items(),
                                        key=lambda kv: kv[1].get("at", "")):
                    title = meta.get("title", key)
                    desc = meta.get("description", "")
                    lines.append((f"    ★ {title}" + (f" — {desc}" if desc else ""),
                                  PAPER))
        lines += [("", INK), ("  any key to go back", INK)]

        canvas = fx.Canvas(self.screen.width, self.screen.height, ambient=0.95)
        for i, (text, color) in enumerate(lines[: self.screen.height - 1]):
            canvas.text(3, i + 1, text[: self.screen.width - 4], color)
        self.crt(canvas)
        stdscr.erase()
        self.draw_cabinet(stdscr)
        canvas.blit(stdscr, self.palette, self.screen.x, self.screen.y)
        stdscr.noutrefresh()
        curses.doupdate()
        stdscr.getch()

    def help_screen(self, stdscr) -> None:
        lines = [
            brand.NAME, "",
            "  ← →        move along the shelf",
            "  enter      play",
            "  1 2 3      choose a save slot for this game",
            "  a          awards you have unlocked",
            "  /          search by name or tag      esc clears",
            "  p          switch save profile",
            "  r          rescan for new games",
            "  b          toggle the boot animation",
            "  q          power off",
            "",
            "  new game:  lazstation new <name>",
            "  saves:     ~/.local/share/termstation/saves/<profile>/",
            "",
            "  any key to go back",
        ]
        canvas = fx.Canvas(self.screen.width, self.screen.height, ambient=0.95)
        for i, line in enumerate(lines):
            canvas.text(3, i + 2, line, GLOW if i == 0 else PAPER)
        self.crt(canvas)
        stdscr.erase()
        self.draw_cabinet(stdscr)
        canvas.blit(stdscr, self.palette, self.screen.x, self.screen.y)
        stdscr.noutrefresh()
        curses.doupdate()
        stdscr.getch()
