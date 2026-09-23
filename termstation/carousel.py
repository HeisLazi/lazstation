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
import math
import random
import sys
import time

from . import brand, library, paths
from .library import Game

sys.path.insert(0, str(paths.SDK_DIR))
import termstation_fx as fx                              # noqa: E402
from termstation_bezel import frame_lines, geometry, side_runs  # noqa: E402

FPS = 30
PITCH = 22
IDLE_AFTER = 45.0     # seconds before the console starts demoing itself
ATTRACT_EVERY = 3.0   # seconds per cover while it does              # horizontal distance between cover centres
SLIDE_TIME = 0.20

#: Phosphor themes, cycled with 't'. Each is (chrome, dim, paper, ink, glow).
THEMES = {
    "amber":  ((255, 176, 64), (150, 96, 30), (236, 226, 205), (120, 112, 100),
               (255, 210, 120)),
    "green":  ((120, 235, 130), (50, 130, 60), (215, 240, 215), (95, 130, 100),
               (170, 255, 180)),
    "mono":   ((225, 225, 225), (110, 110, 110), (240, 240, 240), (130, 130, 130),
               (255, 255, 255)),
    "ice":    ((130, 200, 255), (55, 105, 160), (220, 235, 250), (110, 130, 150),
               (185, 225, 255)),
}
THEME_ORDER = list(THEMES)

AMBER = fx.rgb(255, 176, 64)
AMBER_DIM = fx.rgb(150, 96, 30)
CYAN = fx.rgb(120, 220, 230)
PAPER = fx.rgb(236, 226, 205)
INK = fx.rgb(120, 112, 100)
GLOW = fx.rgb(255, 210, 120)


class Action:
    def __init__(self, kind: str, game: Game | None = None,
                 profile: str = "default", slot: int = 1,
                 boot: bool = True) -> None:
        self.kind, self.game, self.profile, self.slot = kind, game, profile, slot
        self.boot = boot          # quick start skips the loading screen


def _wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap. Long words are left to be clipped by the caller."""
    out: list[str] = []
    for para in text.splitlines():
        line = ""
        for word in para.split():
            if len(line) + len(word) + 1 > width:
                out.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        out.append(line)
    return [l for l in out if l] or [""]


def accent_for(game: Game) -> int:
    """The game's accent as an xterm-256 index."""
    return fx.rgb(*library.accent_for(game))


def load_cover(game: Game) -> list[str]:
    return library.load_cover(game)


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
        self.motes: list[list[float]] = []
        self.theme = "amber"
        self.last_key = time.monotonic()
        self.attract = False
        self.attract_at = 0.0
        self.focus = "shelf"      # or "panel": down moves into the cards
        self.card = 0
        self.cards: list[str] = []
        self.born = time.monotonic()
        self.prev_game: Game | None = None
        self.change_at = 0.0
        self.refresh_library()

    def load_config(self) -> dict:
        try:
            import json
            return json.loads(paths.CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_config(self) -> None:
        """Remember the look between sessions -- a console that forgets your
        settings every time you switch it on is not a console."""
        import json
        try:
            paths.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = self.load_config()
            data.update(theme=self.theme, fast_boot=self.fast_boot,
                        profile=self.profile)
            tmp = paths.CONFIG_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(paths.CONFIG_FILE)
        except OSError:
            pass

    def apply_theme(self, name: str) -> None:
        """Re-tint the whole dashboard. Module-level colours are rebound so
        every drawing call picks the new phosphor up without threading a
        palette through each one."""
        global AMBER, AMBER_DIM, PAPER, INK, GLOW
        chrome, dim, paper, ink, glow = THEMES[name]
        AMBER, AMBER_DIM = fx.rgb(*chrome), fx.rgb(*dim)
        PAPER, INK, GLOW = fx.rgb(*paper), fx.rgb(*ink), fx.rgb(*glow)
        self.theme = name

    # ------------------------------------------------------------- ambience
    def seed_motes(self, width: int, height: int) -> None:
        """Slow embers drifting up the screen. The dashboard is never still,
        which is most of what separates 'alive' from 'a menu'."""
        self.motes = [[random.uniform(0, width), random.uniform(0, height),
                       random.uniform(0.6, 2.2), random.random()]
                      for _ in range(max(8, width // 6))]

    def drift(self, canvas: fx.Canvas, dt: float, floor: int | None = None) -> None:
        """Embers rise through the upper picture. `floor` keeps them out of
        the information band, where they would read as noise in the text."""
        if not self.motes:
            self.seed_motes(canvas.w, canvas.h)
        for m in self.motes:
            m[1] -= dt * m[2] * 0.6
            m[0] += math.sin(m[1] * 0.6 + m[3] * 6) * dt * 1.2
            if m[1] < 0:
                m[1] = canvas.h - 0.01
                m[0] = random.uniform(0, canvas.w)
            x, y = int(m[0]), int(m[1])
            if floor is not None and y >= floor:
                continue
            if canvas.inside(x, y) and canvas.ch[y * canvas.w + x] == " ":
                glyph = "·" if m[2] < 1.4 else "∙"
                canvas.put(x, y, glyph, fx.scale(AMBER_DIM, 0.35 + 0.3 * m[3]))

    # ------------------------------------------------------------- data
    def refresh_library(self) -> None:
        self.all_games, self.problems = library.discover()
        self.stats = library.load_stats()
        self.awards = self.load_awards()
        self.covers = {g.slug: load_cover(g) for g in self.all_games}
        self.index = min(self.index, max(0, len(self.visible) - 1))
        self.scroll = float(self.index)

    @staticmethod
    def load_awards() -> dict:
        try:
            import json
            return json.loads(paths.ACHIEVEMENTS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def award_count(self, slug: str) -> int:
        return len(self.awards.get(slug, {}))

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
    @staticmethod
    def card(canvas: fx.Canvas, x: int, y: int, w: int, h: int, label: str,
             lines: list[tuple[str, int]], edge: int, label_color: int) -> None:
        """A small titled panel. The label sits in the top border, which is
        what makes a row of these read as a set of cards rather than boxes."""
        canvas.box(x, y, w, h, edge)
        tag = f" {label} "[: max(0, w - 4)]
        canvas.text(x + 2, y, tag, label_color)
        for i, (text, color) in enumerate(lines[: h - 2]):
            canvas.text(x + 2, y + 1 + i, text[: w - 3], color)

    def cover_tile(self, canvas: fx.Canvas, game: Game, cx: int, cy: int,
                   closeness: float, pulse: float = 0.0) -> None:
        """One cover. `closeness` is 1 at the centre and 0 far out."""
        w = int(14 + 6 * closeness)
        h = int(5 + 4 * closeness)
        x = cx - w // 2
        y = cy - h // 2
        if x + w < 0 or x > canvas.w:
            return

        bright = 0.35 + 0.65 * closeness
        tone = accent_for(game)
        edge = fx.scale(tone if closeness > 0.55 else AMBER_DIM, bright)
        canvas.fill(x + 1, y + 1, w - 2, h - 2, " ", PAPER)
        canvas.box(x, y, w, h, edge)

        art = self.covers.get(game.slug, [])
        art_w = max((len(a) for a in art), default=0)
        ax = x + (w - art_w) // 2
        ay = y + (h - len(art)) // 2
        tint = fx.mix(INK, tone, closeness * 0.75)
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
            # The selected cover breathes: a slow swell of light around it.
            canvas.add_light(cx, cy, max(w, h) * 0.85, 0.42 + 0.16 * pulse)

    def compose(self, width: int, height: int, t: float = 0.0,
                dt: float = 0.0) -> fx.Canvas:
        canvas = fx.Canvas(width, height, ambient=0.92)
        games = self.visible
        pulse = 0.5 + 0.5 * math.sin(t * 1.9)
        self.drift(canvas, dt, floor=9)
        game_now = self.current
        tone = accent_for(game_now) if game_now else AMBER

        head = f"{brand.NAME}"
        canvas.text(1, 0, head, fx.scale(tone, 0.85 + 0.15 * pulse))
        total_awards = sum(len(v) for v in self.awards.values())
        meta = f"{self.profile}   {len(self.all_games)} games   ★ {total_awards}"
        canvas.text(max(1, width - len(meta) - 1), 0, meta, INK)

        row_y = 6
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
                self.cover_tile(canvas, game, cx, row_y, closeness, pulse)

            game = self.current
            if game:
                self.game_hub(canvas, game, width, height, tone, t,
                              position="".join("◆" if i == self.index else "◇"
                                               for i in range(len(games))))

        if self.attract:
            note = "▌ ATTRACT MODE — press any key"
            canvas.text(max(1, (width - len(note)) // 2), height - 1,
                        note, fx.scale(tone, 0.55 + 0.45 * pulse))
        elif self.searching:
            bar = f"search: {self.filter}_"
            canvas.text(1, height - 1, bar, GLOW)
        elif self.message and time.monotonic() < self.msg_until:
            canvas.text(1, height - 1, self.message[:width - 2], CYAN)
        else:
            game = self.current
            has_save = False
            if game:
                chosen = self.slots.get(game.slug, 1)
                used = paths.slots_used(self.profile, game.slug)
                has_save = used[chosen - 1] if chosen <= len(used) else False
            verb = "continue" if has_save else "play"
            if self.focus == "panel":
                hint = ("← →  card   ⏎ choose   ↑ back to the shelf   "
                        "t theme   ? help   q off")
            else:
                hint = (f"← →  select   ⏎ {verb}   ↓ options   a awards   "
                        "t theme   / find   ? help   q off")
            canvas.text(max(1, (width - len(hint)) // 2), height - 1, hint, INK)
        return canvas

    def hub_cards(self, game: Game) -> list[tuple[str, list[tuple[str, int]]]]:
        """The contextual cards under a game, in order."""
        st = self.stats.get(game.slug, {})
        chosen = self.slots.get(game.slug, 1)
        used = paths.slots_used(self.profile, game.slug)
        has_save = used[chosen - 1] if chosen <= len(used) else False
        summary = library.save_summary(self.profile, game.slug, chosen)
        tone = accent_for(game)

        got = self.award_count(game.slug)
        total = len(game.award_defs) or got
        stars = ("★" * got) + ("☆" * max(0, total - got))
        filled = int(10 * got / total) if total else 0

        marks = " ".join(f"[{n}]" if n == chosen else f" {n} "
                         for n, _ in enumerate(used, 1))
        return [
            ("CONTINUE" if has_save else "START",
             [(summary or "new run", GLOW if has_save else PAPER),
              ("play now", INK)]),
            ("AWARDS",
             [(f"{stars} {got}/{total}" if total else "none", 
               fx.scale(tone, 0.95) if got else INK),
              ("▓" * filled + "░" * (10 - filled), fx.scale(tone, 0.8))]),
            ("SLOT",
             [(marks, PAPER),
              ("".join("▣" if t else "▢" for t in used), fx.scale(tone, 0.8))]),
            ("MANUAL",
             [("how to play", PAPER), ("controls", INK)]),
        ]

    def game_hub(self, canvas: fx.Canvas, game: Game, width: int, height: int,
                 tone: int, t: float, position: str = "") -> None:
        """The panel under the shelf. Down moves focus into it, so the cards
        are things you operate rather than a readout."""
        top = 12
        panel_h = height - top - 1
        st = self.stats.get(game.slug, {})
        settle = min(1.0, (t - self.change_at) / 0.3)
        edge = fx.mix(fx.scale(tone, 0.3), tone, settle)

        canvas.box(0, top, width, panel_h, edge)
        canvas.text(2, top, f" {game.name.upper()} ", GLOW)

        plays = st.get("launches", 0)
        if plays:
            right = (f"{library.format_playtime(st.get('seconds', 0))}"
                     f" · {plays}× · {library.format_last_played(st.get('last_played'))}")
        else:
            right = "never played"
        canvas.text(max(4, width - len(right) - 4), top, f" {right} ", INK)

        desc = _wrap(game.tagline, width - 6)[0]
        canvas.text(3, top + 1, desc, PAPER)

        cards = self.hub_cards(game)
        self.cards = [label for label, _ in cards]
        gap = 1
        cw = max(11, (width - 6 - gap * (len(cards) - 1)) // len(cards))
        x = 3
        for i, (label, lines) in enumerate(cards):
            live = self.focus == "panel" and i == self.card
            border = GLOW if live else fx.scale(edge, 0.7)
            head = GLOW if live else fx.scale(tone, 0.9)
            self.card_box(canvas, x, top + 2, cw, 4, label, lines, border, head,
                          marker=live)
            x += cw + gap

        if position:
            canvas.text(max(2, (width - len(position)) // 2),
                        top + panel_h - 1, f" {position} ", fx.scale(tone, 0.7))

    @staticmethod
    def card_box(canvas: fx.Canvas, x: int, y: int, w: int, h: int, label: str,
                 lines: list[tuple[str, int]], edge: int, label_color: int,
                 marker: bool = False) -> None:
        canvas.box(x, y, w, h, edge)
        tag = f" {label} "[: max(0, w - 4)]
        canvas.text(x + 2, y, tag, label_color)
        if marker:
            canvas.text(x + w - 3, y, "▾", label_color)
        for i, (text, color) in enumerate(lines[: h - 2]):
            canvas.text(x + 2, y + 1 + i, text[: w - 3], color)

    def crt(self, canvas: fx.Canvas, t: float = 0.0) -> None:
        """Scanlines, vignette, a slow rolling band and a little flicker --
        applied to the light channel only, so the picture dims without
        anything drawn being altered."""
        roll = (t * 7.0) % (canvas.h + 8) - 4
        flick = 1.0 - 0.015 * (1 + math.sin(t * 31.0))
        for y in range(canvas.h):
            scan = 0.80 if y % 2 else 1.0
            band = 1.0 + 0.18 * max(0.0, 1.0 - abs(y - roll) / 2.5)
            for x in range(canvas.w):
                i = y * canvas.w + x
                edge = 1.0 - 0.22 * abs(x - canvas.w / 2) / (canvas.w / 2)
                canvas.lit[i] *= scan * edge * band * flick

    # ------------------------------------------------------------- frame
    def render(self, stdscr, t: float = 0.0, dt: float = 0.0) -> None:
        rows, cols = stdscr.getmaxyx()
        screen = geometry(cols, rows)
        if screen.width != getattr(self, "_last_w", -1):
            self.motes = []          # reseed drift for the new width
            self._last_w = screen.width
        self.screen = screen
        stdscr.erase()
        self.draw_cabinet(stdscr)
        canvas = self.compose(screen.width, screen.height, t, dt)
        self.crt(canvas, t)
        canvas.blit(stdscr, self.palette, screen.x, screen.y)
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

    def select(self, target: int) -> None:
        """Aim the carousel. The loop eases toward it; nothing blocks."""
        self.index = target
        self.change_at = time.monotonic()

    # ------------------------------------------------------------- loop
    def loop(self, stdscr) -> Action:
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.nodelay(True)          # never block: the dashboard keeps moving
        self.palette = fx.Palette(curses)
        self.screen = geometry(*reversed(stdscr.getmaxyx()))
        last = time.monotonic()
        self.change_at = last

        while True:
            now = time.monotonic()
            dt = min(0.1, now - last)
            last = now

            # Ease the carousel toward whatever is selected.
            gap = self.index - self.scroll
            if abs(gap) < 0.002:
                self.scroll = float(self.index)
            else:
                self.scroll += gap * min(1.0, dt * 11.0)

            # Idle long enough and the console starts showing itself off,
            # the way a shop-floor console does.
            if not self.searching and now - self.last_key > IDLE_AFTER:
                if not self.attract:
                    self.attract = True
                    self.attract_at = now
                elif now - self.attract_at > ATTRACT_EVERY:
                    self.attract_at = now
                    games_now = self.visible
                    if games_now:
                        self.select((self.index + 1) % len(games_now))

            self.render(stdscr, now - self.born, dt)

            key = stdscr.getch()
            if key == -1:
                time.sleep(max(0.0, 1 / FPS - (time.monotonic() - now)))
                continue
            self.last_key = now
            if self.attract:
                # The keypress that wakes it only wakes it.
                self.attract = False
                continue
            if key == curses.KEY_RESIZE:
                continue

            if self.searching:
                if key in (10, 13, curses.KEY_ENTER, 27):
                    self.searching = False
                    if key == 27:
                        self.filter = ""
                    self.select(0)
                    self.scroll = 0.0
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    self.filter = self.filter[:-1]
                elif 32 <= key < 127:
                    self.filter += chr(key)
                    self.select(0)
                    self.scroll = 0.0
                continue

            games = self.visible
            if key in (ord("q"), ord("Q")):
                return Action("quit")
            if key in (curses.KEY_DOWN, ord("j")) and games:
                self.focus = "panel"
            elif key in (curses.KEY_UP, ord("k")):
                self.focus = "shelf"
            elif key in (curses.KEY_LEFT, ord("h")) and games:
                if self.focus == "panel":
                    self.card = (self.card - 1) % max(1, len(self.cards))
                else:
                    self.select((self.index - 1) % len(games))
            elif key in (curses.KEY_RIGHT, ord("l")) and games:
                if self.focus == "panel":
                    self.card = (self.card + 1) % max(1, len(self.cards))
                else:
                    self.select((self.index + 1) % len(games))
            elif key in (curses.KEY_HOME, ord("g")) and games:
                self.select(0)
            elif key in (curses.KEY_END, ord("G")) and games:
                self.select(len(games) - 1)
            elif key in (10, 13, curses.KEY_ENTER, ord(" ")):
                game = self.current
                if not game:
                    continue
                if self.focus == "shelf":
                    stdscr.nodelay(False)
                    return Action("launch", game, self.profile,
                                  self.slots.get(game.slug, 1))
                label = self.cards[self.card] if self.cards else ""
                if label in ("CONTINUE", "START"):
                    stdscr.nodelay(False)
                    # Quick start: straight in, no loading screen.
                    return Action("launch", game, self.profile,
                                  self.slots.get(game.slug, 1), boot=False)
                if label == "AWARDS":
                    stdscr.nodelay(False)
                    self.awards_screen(stdscr)
                    stdscr.nodelay(True)
                elif label == "SLOT":
                    nxt = self.slots.get(game.slug, 1) % 3 + 1
                    self.slots[game.slug] = nxt
                    self.say(f"slot {nxt}")
                elif label == "MANUAL":
                    stdscr.nodelay(False)
                    self.manual_screen(stdscr, game)
                    stdscr.nodelay(True)
            elif key == ord("/"):
                self.searching = True
                self.filter = ""
            elif key in (ord("r"), ord("R")):
                self.refresh_library()
                self.say("library refreshed")
            elif key in (ord("b"), ord("B")):
                self.fast_boot = not self.fast_boot
                self.save_config()
                self.say("boot animation " + ("off" if self.fast_boot else "on"))
            elif key in (ord("p"), ord("P")):
                stdscr.nodelay(False)
                self.profile = self.ask_profile(stdscr)
                stdscr.nodelay(True)
            elif key in (ord("1"), ord("2"), ord("3")) and games:
                game = self.current
                if game:
                    self.slots[game.slug] = key - ord("0")
                    self.say(f"slot {key - ord('0')} selected")
            elif key in (ord("t"), ord("T")):
                nxt = THEME_ORDER[(THEME_ORDER.index(self.theme) + 1)
                                  % len(THEME_ORDER)]
                self.apply_theme(nxt)
                self.save_config()
                self.say(f"{nxt} phosphor")
            elif key in (ord("a"), ord("A")):
                stdscr.nodelay(False)
                self.awards_screen(stdscr)
                stdscr.nodelay(True)
            elif key == ord("?"):
                stdscr.nodelay(False)
                self.help_screen(stdscr)
                stdscr.nodelay(True)

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

    def pager(self, stdscr, title: str, lines: list[tuple[str, int]],
              footer: str = "↑↓ scroll    any other key goes back") -> None:
        """A scrollable full-picture page. Used for awards and manuals."""
        offset = 0
        while True:
            width, height = self.screen.width, self.screen.height
            body = height - 4
            canvas = fx.Canvas(width, height, ambient=0.95)
            canvas.text(2, 0, title, GLOW)
            count = f"{len(lines)} lines" if len(lines) > body else ""
            if len(lines) > body:
                count = f"{offset + 1}-{min(len(lines), offset + body)} of {len(lines)}"
                canvas.text(max(2, width - len(count) - 2), 0, count, INK)
            canvas.text(1, 1, "─" * (width - 2), fx.scale(AMBER_DIM, 0.8))
            for i, (text, color) in enumerate(lines[offset:offset + body]):
                canvas.text(2, 2 + i, text[: width - 4], color)
            canvas.text(1, height - 2, "─" * (width - 2), fx.scale(AMBER_DIM, 0.8))
            canvas.text(2, height - 1, footer, INK)
            self.crt(canvas, 0.0)
            stdscr.erase()
            self.draw_cabinet(stdscr)
            canvas.blit(stdscr, self.palette, self.screen.x, self.screen.y)
            stdscr.noutrefresh()
            curses.doupdate()

            key = stdscr.getch()
            if key in (curses.KEY_DOWN, ord("j")) and offset + body < len(lines):
                offset += 1
            elif key in (curses.KEY_UP, ord("k")) and offset > 0:
                offset -= 1
            elif key == curses.KEY_NPAGE:
                offset = min(max(0, len(lines) - body), offset + body)
            elif key == curses.KEY_PPAGE:
                offset = max(0, offset - body)
            elif key == curses.KEY_RESIZE:
                continue
            else:
                return

    def awards_screen(self, stdscr) -> None:
        """Every award on the console, locked ones included.

        Showing what you have *not* earned is the point -- a list of things
        already done is a receipt, a list of what is still out there is a
        reason to play.
        """
        self.awards = self.load_awards()
        lines: list[tuple[str, int]] = []
        earned = total = 0

        for game in self.all_games:
            got = self.awards.get(game.slug, {})
            defs = game.award_defs
            if not defs and not got:
                continue
            tone = accent_for(game)
            have = len([d for d in defs if d["key"] in got]) if defs else len(got)
            of = len(defs) or len(got)
            earned += have
            total += of
            lines.append(("", INK))
            lines.append((f"{game.name.upper()}".ljust(34) + f"{have}/{of}", tone))
            shown = set()
            for d in defs:
                key = d["key"]
                shown.add(key)
                unlocked = key in got
                mark = "★" if unlocked else "☆"
                title = d.get("title", key)
                desc = d.get("description", "") or "—"
                colour = PAPER if unlocked else INK
                lines.append((f"  {mark} {title.ljust(30)}{desc}", colour))
            # awards earned before they were declared in the manifest
            for key, meta in got.items():
                if key in shown:
                    continue
                lines.append((f"  ★ {meta.get('title', key).ljust(30)}"
                              f"{meta.get('description', '')}", PAPER))

        if not lines:
            lines = [("", INK), ("  No games declare awards yet.", PAPER)]
        header = f"AWARDS    {earned} of {total} unlocked" if total else "AWARDS"
        self.pager(stdscr, header, lines)

    def manual_screen(self, stdscr, game: Game) -> None:
        """How to play, from the game's own manual if it ships one."""
        lines: list[tuple[str, int]] = [("", INK)]
        for line in _wrap(game.description.strip(), self.screen.width - 6):
            lines.append((f"  {line}", PAPER))

        text = None
        for name in ("manual.md", "manual.txt", "README.md"):
            try:
                text = (game.root / name).read_text(encoding="utf-8")
                break
            except OSError:
                continue
        if text:
            room = self.screen.width - 6
            lines.append(("", INK))
            para: list[str] = []

            def flush() -> None:
                # Wrap whole paragraphs, not source lines: wrapping each line
                # on its own strands the last word or two of every one.
                if para:
                    for part in _wrap(" ".join(para), room):
                        lines.append((f"  {part}", PAPER))
                    para.clear()

            for raw in text.splitlines():
                stripped = raw.strip()
                if not stripped:
                    flush()
                    lines.append(("", INK))
                elif stripped.startswith("#"):
                    flush()
                    lines.append((f"  {stripped.lstrip('#').strip()}", GLOW))
                elif stripped.startswith(("  ", "\t")) or "  " in raw[:4]:
                    flush()
                    lines.append((f"  {raw.rstrip()}", PAPER))
                else:
                    para.append(stripped)
            flush()
        else:
            lines.append(("", INK))
            lines.append(("  This game ships no manual.", INK))
            lines.append(("  Drop a manual.md in its folder and it appears here.",
                          INK))

        lines.append(("", INK))
        lines.append((f"  version {game.version}"
                      + (f"    by {game.author}" if game.author else ""), INK))
        lines.append((f"  saves    {paths.save_dir(self.profile, game.slug)}", INK))
        self.pager(stdscr, f"MANUAL — {game.name.upper()}", lines)

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
            "  t          cycle the phosphor: amber, green, mono, ice",
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
        self.crt(canvas, 0.0)
        stdscr.erase()
        self.draw_cabinet(stdscr)
        canvas.blit(stdscr, self.palette, self.screen.x, self.screen.y)
        stdscr.noutrefresh()
        curses.doupdate()
        stdscr.getch()
