#!/usr/bin/env python3
"""Pipe Jumper -- a real-time side-scrolling platformer for the terminal.

Terminals report key presses but never releases, so "still holding jump" is
inferred from auto-repeat (see ts.Loop). That is the one real fidelity loss
against a console platformer; everything else -- 30fps, variable jump height,
tile collision, a scrolling camera -- behaves as you would expect.

Character cells are about twice as tall as they are wide, so horizontal speed
is roughly double the vertical scale or the jump arc reads floaty.

Because a release cannot be seen, a tap and a hold look alike for the first
fraction of a second, and how much extra height a hold gives depends on the
terminal's key-repeat delay. So the plain tap jump is tuned to clear every
jump the levels require; holding is a bonus that reaches the high platforms,
never a requirement.
"""
from __future__ import annotations

import curses
import sys

import termstation_sdk as ts
from levels import LEVELS

# ---------------------------------------------------------------- tuning
GRAVITY = 62.0          # cells/second^2
JUMP_SPEED = 23.6       # a plain tap must clear every jump the levels ask for
JUMP_HOLD = 0.30        # seconds of extra lift while jump keeps repeating
RUN_SPEED = 17.0        # cells/second
MAX_FALL = 34.0
STOMP_BOUNCE = 13.0
ENEMY_SPEED = 4.5
FPS = 30

SOLID = set("#=|")
DEADLY = set("^")

C_SKY, C_GROUND, C_BRICK, C_COIN, C_PLAYER, C_ENEMY, C_SPIKE, C_FLAG, C_HUD = range(1, 10)

TILE_COLOR = {"#": C_GROUND, "=": C_BRICK, "|": C_BRICK, "^": C_SPIKE, "f": C_FLAG}
TILE_GLYPH = {"#": "▓", "=": "═", "|": "║", "^": "▲", "f": "⚑"}


class Level:
    def __init__(self, data: dict) -> None:
        self.name = data["name"]
        rows = data["rows"]
        self.w = max(len(r) for r in rows)
        self.rows = [r.ljust(self.w, ".") for r in rows]
        self.h = len(self.rows)
        self.coins: set[tuple[int, int]] = set()
        self.enemies: list[Enemy] = []
        self.start = (2.0, 1.0)
        self.flag_x = self.w - 2

        for y, row in enumerate(self.rows):
            for x, ch in enumerate(row):
                if ch == "o":
                    self.coins.add((x, y))
                elif ch == "g":
                    self.enemies.append(Enemy(float(x), float(y)))
                elif ch == "@":
                    self.start = (float(x), float(y))
                elif ch == "f":
                    self.flag_x = min(self.flag_x, x)
        # Entities are not terrain; blank them out of the tile map.
        self.rows = [r.replace("o", ".").replace("g", ".").replace("@", ".")
                     for r in self.rows]

    def tile(self, x: int, y: int) -> str:
        if y < 0 or y >= self.h:
            return "."
        if x < 0 or x >= self.w:
            return "#"          # walls at the edges of the world
        return self.rows[y][x]

    def solid(self, x: float, y: float) -> bool:
        return self.tile(int(x), int(y)) in SOLID


class Enemy:
    def __init__(self, x: float, y: float) -> None:
        self.x, self.y = x, y
        self.dx = -ENEMY_SPEED
        self.alive = True
        self.squash = 0.0

    def update(self, level: Level, dt: float) -> None:
        if not self.alive:
            self.squash = max(0.0, self.squash - dt)
            return
        nx = self.x + self.dx * dt
        # Turn around at a wall, or at the lip of a ledge.
        if level.solid(nx, self.y) or not level.solid(nx, self.y + 1):
            self.dx = -self.dx
        else:
            self.x = nx


class Player:
    def __init__(self, x: float, y: float) -> None:
        self.x, self.y = x, y
        self.vx = self.vy = 0.0
        self.on_ground = False
        self.jump_time = 0.0
        self.dead = False
        self.face = 1

    def update(self, level: Level, loop: ts.Loop, dt: float) -> None:
        left = loop.held(curses.KEY_LEFT, ord("a"), ord("A"))
        right = loop.held(curses.KEY_RIGHT, ord("d"), ord("D"))
        jump_now = loop.pressed(ord(" "), curses.KEY_UP, ord("w"), ord("W"))
        jump_held = loop.held(ord(" "), curses.KEY_UP, ord("w"), ord("W"))

        self.vx = 0.0
        if left and not right:
            self.vx, self.face = -RUN_SPEED, -1
        elif right and not left:
            self.vx, self.face = RUN_SPEED, 1

        if jump_now and self.on_ground:
            self.vy = -JUMP_SPEED
            self.jump_time = 0.0
            self.on_ground = False
        elif self.jump_time >= 0 and jump_held and self.vy < 0:
            # Extra lift while the key keeps repeating: the taller jump.
            self.jump_time += dt
            if self.jump_time < JUMP_HOLD:
                self.vy -= GRAVITY * 0.55 * dt
            else:
                self.jump_time = -1.0
        else:
            self.jump_time = -1.0

        self.vy = min(MAX_FALL, self.vy + GRAVITY * dt)

        # Never travel more than half a cell per collision test: a single
        # long frame would otherwise step clean through the floor.
        travel = max(abs(self.vx), abs(self.vy)) * dt
        steps = max(1, int(travel / 0.5) + 1)
        # on_ground is decided across the whole frame: a later sub-step with
        # zero velocity must not erase the landing an earlier one detected.
        self.on_ground = False
        for _ in range(steps):
            self._move(level, dt / steps)

    def _move(self, level: Level, dt: float) -> None:
        # Axis-separated collision: resolve x, then y, so a wall never
        # cancels a fall and a floor never cancels a run.
        nx = self.x + self.vx * dt
        if self.vx:
            edge = nx + (0.99 if self.vx > 0 else 0.0)
            if level.solid(edge, self.y):
                nx = float(int(edge)) + (-0.01 if self.vx > 0 else 1.0)
                nx = max(0.0, nx)
            self.x = max(0.0, min(level.w - 1.01, nx))

        ny = self.y + self.vy * dt
        if self.vy > 0:
            if level.solid(self.x, ny + 0.99):
                ny = float(int(ny + 0.99)) - 1.0
                self.vy = 0.0
                self.on_ground = True
        elif self.vy < 0:
            if level.solid(self.x, ny):
                ny = float(int(ny)) + 1.0
                self.vy = 0.0
        self.y = ny
        if self.y > level.h + 2:
            self.dead = True


def init_colors() -> bool:
    if not curses.has_colors():
        return False
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    for pair, fg in ((C_SKY, curses.COLOR_BLUE), (C_GROUND, curses.COLOR_GREEN),
                     (C_BRICK, curses.COLOR_YELLOW), (C_COIN, curses.COLOR_YELLOW),
                     (C_PLAYER, curses.COLOR_RED), (C_ENEMY, curses.COLOR_MAGENTA),
                     (C_SPIKE, curses.COLOR_RED), (C_FLAG, curses.COLOR_CYAN),
                     (C_HUD, curses.COLOR_WHITE)):
        curses.init_pair(pair, fg, bg)
    return True


class Game:
    def __init__(self, stdscr, save: dict) -> None:
        self.stdscr = stdscr
        self.save = save
        self.color = init_colors()
        self.win, self.screen = ts.tv_curses(stdscr, "Pipe Jumper")
        self.loop = ts.Loop(self.win, fps=FPS)
        self.score = 0
        self.coins = 0
        self.lives = 3
        self.paused = False

    def attr(self, pair: int, bold: bool = False) -> int:
        if not self.color:
            return curses.A_BOLD if bold else curses.A_NORMAL
        a = curses.color_pair(pair)
        return a | curses.A_BOLD if bold else a

    def put(self, y: int, x: int, text: str, attr: int = 0) -> None:
        h, w = self.win.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                self.win.addnstr(y, x, text, max(0, w - x - 1), attr)
            except curses.error:
                pass

    def relayout(self) -> None:
        self.win, self.screen = ts.tv_curses(self.stdscr, "Pipe Jumper")
        self.loop.win = self.win
        self.win.nodelay(True)
        self.win.keypad(True)

    # ------------------------------------------------------------- drawing
    def draw(self, level: Level, player: Player, cam: int, message: str = "") -> None:
        self.win.erase()
        h, w = self.win.getmaxyx()
        view_h = min(level.h, h - 3)
        top = 1                      # row 0 is the HUD

        for sy in range(view_h):
            ly = sy + max(0, level.h - view_h)
            line_chars = []
            for sx in range(w - 1):
                lx = sx + cam
                ch = level.tile(lx, ly)
                line_chars.append(TILE_GLYPH.get(ch, " ") if ch != "." else " ")
            self.put(top + sy, 0, "".join(line_chars), self.attr(C_GROUND))
            # Recolour the non-ground glyphs individually.
            for sx in range(w - 1):
                ch = level.tile(sx + cam, ly)
                if ch in TILE_COLOR and ch != "#":
                    self.put(top + sy, sx, TILE_GLYPH[ch],
                             self.attr(TILE_COLOR[ch], bold=True))

        for (cx, cy) in level.coins:
            sx, sy = cx - cam, cy - max(0, level.h - view_h)
            if 0 <= sx < w - 1 and 0 <= sy < view_h:
                self.put(top + sy, sx, "○", self.attr(C_COIN, bold=True))

        for e in level.enemies:
            if not e.alive and e.squash <= 0:
                continue
            sx, sy = int(e.x) - cam, int(e.y) - max(0, level.h - view_h)
            if 0 <= sx < w - 1 and 0 <= sy < view_h:
                glyph = "▂" if not e.alive else "ᗣ"
                self.put(top + sy, sx, glyph, self.attr(C_ENEMY, bold=True))

        psx = int(player.x) - cam
        psy = int(player.y) - max(0, level.h - view_h)
        if 0 <= psx < w - 1 and 0 <= psy < view_h:
            glyph = "◄" if player.face < 0 else "►"
            if not player.on_ground:
                glyph = "▲"
            self.put(top + psy, psx, glyph, self.attr(C_PLAYER, bold=True))

        hud = (f" {level.name}   coins {self.coins:02d}   score {self.score:05d}"
               f"   lives {self.lives}")
        self.put(0, 0, hud.ljust(w - 1), self.attr(C_HUD, bold=True))
        hint = " ←/→ or a/d move    space or ↑ jump (hold for height)    p pause    q quit"
        self.put(h - 1, 0, hint[:w - 1], self.attr(C_HUD))
        if message:
            self.put(h - 2, max(0, (w - len(message)) // 2), message,
                     self.attr(C_FLAG, bold=True))
        self.stdscr.noutrefresh()
        self.win.noutrefresh()
        curses.doupdate()

    def banner(self, lines: list[str]) -> int:
        """Full-picture message. Returns the key that dismissed it."""
        self.win.clear()
        h, w = self.win.getmaxyx()
        top = max(0, h // 2 - len(lines) // 2)
        for i, line in enumerate(lines):
            self.put(top + i, max(0, (w - len(line)) // 2), line,
                     self.attr(C_FLAG, bold=True) if i == 0 else self.attr(C_HUD))
        self.stdscr.noutrefresh()
        self.win.noutrefresh()
        curses.doupdate()
        self.win.nodelay(False)
        key = self.win.getch()
        self.win.nodelay(True)
        return key

    # ------------------------------------------------------------- the game
    def play_level(self, data: dict) -> str:
        """Returns 'won', 'died' or 'quit'."""
        level = Level(data)
        player = Player(*level.start)
        cam = 0
        self.loop.resume()   # the intro/death banner just blocked for seconds
        h, w = self.win.getmaxyx()

        while True:
            self.loop.poll()
            if self.loop.pressed(ord("q"), 27):
                return "quit"
            if self.loop.pressed(ord("p"), ord("P")):
                self.loop.release(ord("p"), ord("P"))
                if self.banner(["PAUSED", "", "any key to continue, q to quit"]) in (
                        ord("q"), 27):
                    return "quit"
                self.win.clear()
                self.loop.resume()

            dt = self.loop.tick()
            player.update(level, self.loop, dt)
            for e in level.enemies:
                e.update(level, dt)

            px, py = int(player.x), int(player.y)

            if (px, py) in level.coins:
                level.coins.discard((px, py))
                self.coins += 1
                self.score += 100

            if level.tile(px, py) in DEADLY:
                player.dead = True

            for e in level.enemies:
                if not e.alive or abs(e.x - player.x) > 0.9 or abs(e.y - player.y) > 0.9:
                    continue
                if player.vy > 0 and player.y < e.y:
                    e.alive = False
                    e.squash = 0.4
                    player.vy = -STOMP_BOUNCE
                    self.score += 200
                else:
                    player.dead = True

            if player.dead:
                return "died"
            if px >= level.flag_x:
                self.score += 1000
                return "won"

            # Camera follows once the player passes a third of the view.
            target = px - (w // 3)
            cam = max(0, min(level.w - (w - 1), target))
            self.draw(level, player, cam)

    def run(self) -> None:
        self.banner([
            "P I P E   J U M P E R", "",
            "run and jump to the flag",
            "stomp the walkers, collect the coins", "",
            "←/→ or a/d to move,  space or ↑ to jump",
            "hold jump longer to jump higher", "",
            "any key to start",
        ])
        index = 0
        while index < len(LEVELS):
            self.win.clear()
            result = self.play_level(LEVELS[index])
            if result == "quit":
                break
            if result == "won":
                index += 1
                if index < len(LEVELS):
                    self.banner([f"LEVEL CLEAR", "",
                                 f"score {self.score}   coins {self.coins}",
                                 "", "any key for the next level"])
                continue
            self.lives -= 1
            if self.lives <= 0:
                self.banner(["GAME OVER", "", f"final score {self.score}",
                             "", "any key to leave"])
                break
            self.banner([f"{self.lives} lives left", "", "any key to try again"])

        best = self.save.get("best_score", 0)
        self.save["best_score"] = max(best, self.score)
        self.save["coins_total"] = self.save.get("coins_total", 0) + self.coins
        self.save["runs"] = self.save.get("runs", 0) + 1
        if index >= len(LEVELS):
            self.save["cleared"] = True
            self.banner(["YOU WIN", "", f"final score {self.score}",
                         "", "any key to leave"])


def run(stdscr, save: dict) -> None:
    curses.curs_set(0)
    Game(stdscr, save).run()


def main() -> int:
    save = ts.load({"best_score": 0, "coins_total": 0, "runs": 0, "cleared": False})
    try:
        curses.wrapper(run, save)
    finally:
        ts.save(save)
    ts.tv("Pipe Jumper")
    ts.tv_print(ts.title("P I P E   J U M P E R"))
    ts.tv_print()
    ts.tv_print(ts.box([
        f"  best score    {save['best_score']}",
        f"  coins found   {save['coins_total']}",
        f"  runs          {save['runs']}",
        f"  cleared       {'yes' if save['cleared'] else 'not yet'}",
    ], fg="yellow"))
    ts.tv_print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
