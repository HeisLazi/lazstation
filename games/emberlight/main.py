#!/usr/bin/env python3
"""Emberlight -- a top-down action adventure.

Real-time: the world keeps moving whether or not you press anything, driven by
ts.Loop's fixed timestep. Movement is cell-by-cell on a repeating timer rather
than free floating, which is what makes a character grid read as a map rather
than as soup.

The world is text art in world.py. Editing a room edits the game.
"""
from __future__ import annotations

import curses
import random
import sys

import termstation_sdk as ts
from world import DUNGEON, INTRO, OVERWORLD, ROOM_H, ROOM_W, STAIRS, WIN

FPS = 30
STEP_X = 0.055          # seconds per cell sideways
STEP_Y = 0.085          # slower vertically: cells are about twice as tall
ENEMY_STEP = 0.42
FLITTER_STEP = 0.20
BOSS_STEP = 0.30
IFRAMES = 0.9
SWING_TIME = 0.16
MAX_HEARTS = 5
BOSS_HP = 14

WALLS = set("#T~D")
HURTS = set("^")

C_WALL, C_GRASS, C_WATER, C_PLAYER, C_ENEMY, C_ITEM, C_HUD, C_BOSS, C_DOOR = range(1, 10)

GLYPH = {"#": "▓", "T": "♣", "~": "≈", "=": "═", "^": "▲", "D": "▒", "d": " ",
         ".": " ", ",": "\"", "C": "▣", "$": "•", "K": "⚿", "H": "♥",
         "<": "▼", ">": "▲"}
COLOR = {"#": C_WALL, "T": C_GRASS, "~": C_WATER, "=": C_WALL, "^": C_ENEMY,
         "D": C_DOOR, ",": C_GRASS, "C": C_ITEM, "$": C_ITEM, "K": C_ITEM,
         "H": C_ITEM, "<": C_DOOR, ">": C_DOOR}


class Enemy:
    def __init__(self, x: int, y: int, kind: str) -> None:
        self.x, self.y, self.kind = x, y, kind
        self.timer = random.uniform(0, 0.3)
        self.hp = BOSS_HP if kind == "B" else (2 if kind == "e" else 1)
        self.alive = True
        self.hurt = 0.0

    @property
    def speed(self) -> float:
        return {"e": ENEMY_STEP, "b": FLITTER_STEP, "B": BOSS_STEP}[self.kind]

    @property
    def glyph(self) -> str:
        return {"e": "ᗢ", "b": "ᘛ", "B": "☗"}[self.kind]


class Room:
    """One screen. Terrain is mutable (doors open, pots break); entities are
    rebuilt from the art each time you walk in."""

    def __init__(self, data: dict, taken: set, key: tuple) -> None:
        self.name = data["name"]
        self.grid = [list(r) for r in data["rows"]]
        self.enemies: list[Enemy] = []
        self.key = key
        for y, row in enumerate(self.grid):
            for x, ch in enumerate(row):
                if ch in "ebB":
                    if (key, x, y) not in taken or ch != "B":
                        self.enemies.append(Enemy(x, y, ch))
                    self.grid[y][x] = "."
                elif ch == "S":
                    self.grid[y][x] = ","
                elif ch in "C$KH" and (key, x, y) in taken:
                    self.grid[y][x] = "."

    def at(self, x: int, y: int) -> str:
        if 0 <= y < len(self.grid) and 0 <= x < len(self.grid[y]):
            return self.grid[y][x]
        return "#"

    def walkable(self, x: int, y: int) -> bool:
        return self.at(x, y) not in WALLS


class Game:
    def __init__(self, stdscr, save: dict) -> None:
        self.stdscr = stdscr
        self.save = save
        self.color = self._colors()
        self.win, self.screen = ts.tv_curses(stdscr, "Emberlight")
        self.loop = ts.Loop(self.win, fps=FPS, hold=0.12)

        self.hearts = int(save.get("hearts", 3))
        self.max_hearts = int(save.get("max_hearts", 3))
        self.keys = int(save.get("keys", 0))
        self.embers = int(save.get("embers", 0))
        self.taken = {tuple(t) for t in save.get("taken", [])}
        self.map = save.get("map", "overworld")
        self.rpos = tuple(save.get("room", (0, 0)))
        self.px = int(save.get("px", 23))
        self.py = int(save.get("py", 3))
        self.won = bool(save.get("won", False))

        self.face = (0, 1)
        self.swing = 0.0
        self.invuln = 0.0
        self.mx = self.my = 0.0
        self.message = ""
        self.msg_timer = 0.0
        self.room = self.load_room()

    # ------------------------------------------------------------- setup
    def _colors(self) -> bool:
        if not curses.has_colors():
            return False
        curses.start_color()
        try:
            curses.use_default_colors()
            bg = -1
        except curses.error:
            bg = curses.COLOR_BLACK
        for pair, fg in ((C_WALL, curses.COLOR_WHITE), (C_GRASS, curses.COLOR_GREEN),
                         (C_WATER, curses.COLOR_BLUE), (C_PLAYER, curses.COLOR_YELLOW),
                         (C_ENEMY, curses.COLOR_RED), (C_ITEM, curses.COLOR_CYAN),
                         (C_HUD, curses.COLOR_WHITE), (C_BOSS, curses.COLOR_MAGENTA),
                         (C_DOOR, curses.COLOR_YELLOW)):
            curses.init_pair(pair, fg, bg)
        return True

    def attr(self, pair: int, bold: bool = False) -> int:
        if not self.color:
            return curses.A_BOLD if bold else curses.A_NORMAL
        a = curses.color_pair(pair)
        return a | curses.A_BOLD if bold else a

    def rooms(self) -> dict:
        return OVERWORLD if self.map == "overworld" else DUNGEON

    def load_room(self) -> Room:
        data = self.rooms()[self.rpos]
        return Room(data, self.taken, (self.map, self.rpos))

    def say(self, text: str, seconds: float = 2.2) -> None:
        self.message, self.msg_timer = text, seconds

    # ------------------------------------------------------------- drawing
    def put(self, y: int, x: int, text: str, attr: int = 0) -> None:
        h, w = self.win.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                self.win.addnstr(y, x, text, max(0, w - x - 1), attr)
            except curses.error:
                pass

    def draw(self) -> None:
        self.win.erase()
        h, w = self.win.getmaxyx()
        ox = max(0, (w - ROOM_W) // 2)
        oy = 1

        hearts = ("♥" * self.hearts).ljust(self.max_hearts, "♡")
        hud = f" {hearts}   ⚿ {self.keys}   • {self.embers}"
        self.put(0, ox, hud, self.attr(C_PLAYER, bold=True))
        label = self.room.name
        self.put(0, max(ox, ox + ROOM_W - len(label)), label, self.attr(C_HUD))

        for y in range(min(ROOM_H, h - 3)):
            for x in range(min(ROOM_W, w - ox - 1)):
                ch = self.room.at(x, y)
                glyph = GLYPH.get(ch, ch)
                if glyph == " ":
                    continue
                self.put(oy + y, ox + x, glyph,
                         self.attr(COLOR.get(ch, C_HUD),
                                   bold=ch in "C$KH<>"))

        for e in self.room.enemies:
            if not e.alive:
                continue
            pair = C_BOSS if e.kind == "B" else C_ENEMY
            glyph = "✸" if e.hurt > 0 else e.glyph
            self.put(oy + e.y, ox + e.x, glyph, self.attr(pair, bold=True))

        if self.swing > 0:
            sx, sy = self.px + self.face[0], self.py + self.face[1]
            blade = "─" if self.face[1] == 0 else "│"
            self.put(oy + sy, ox + sx, blade, self.attr(C_PLAYER, bold=True))

        hero = "◉" if self.invuln <= 0 or int(self.invuln * 12) % 2 == 0 else "○"
        self.put(oy + self.py, ox + self.px, hero, self.attr(C_PLAYER, bold=True))

        if self.message:
            self.put(h - 2, ox, self.message[:ROOM_W], self.attr(C_ITEM, bold=True))
        hint = " arrows move   space swing   q leave "
        self.put(h - 1, ox, hint, self.attr(C_HUD))
        self.stdscr.noutrefresh()
        self.win.noutrefresh()
        curses.doupdate()

    def banner(self, lines: list[str], wait: bool = True) -> int:
        self.win.clear()
        h, w = self.win.getmaxyx()
        top = max(0, h // 2 - len(lines) // 2)
        for i, line in enumerate(lines):
            self.put(top + i, max(0, (w - len(line)) // 2), line,
                     self.attr(C_ITEM, bold=True) if i == 0 else self.attr(C_HUD))
        self.stdscr.noutrefresh()
        self.win.noutrefresh()
        curses.doupdate()
        if not wait:
            return -1
        self.win.nodelay(False)
        key = self.win.getch()
        self.win.nodelay(True)
        self.loop.resume()
        self.win.clear()
        return key

    # ------------------------------------------------------------- rules
    def pickup(self, ch: int, x: int, y: int) -> None:
        key = (self.map, self.rpos)
        if ch == "$":
            self.embers += 1
            self.say("an ember")
        elif ch == "K":
            self.keys += 1
            self.say("a small key")
        elif ch == "H":
            self.max_hearts = min(MAX_HEARTS, self.max_hearts + 1)
            self.hearts = self.max_hearts
            self.say("a heart piece — your whole heart comes back")
        elif ch == "C":
            roll = random.random()
            if roll < 0.45:
                self.keys += 1
                self.say("the chest holds a small key")
            elif roll < 0.8:
                self.embers += 3
                self.say("the chest holds three embers")
            else:
                self.hearts = min(self.max_hearts, self.hearts + 2)
                self.say("the chest holds a flask — two hearts back")
        self.taken.add((key, x, y))
        self.room.grid[y][x] = "."

    def try_move(self, dx: int, dy: int) -> None:
        self.face = (dx, dy)
        nx, ny = self.px + dx, self.py + dy

        if not (0 <= nx < ROOM_W and 0 <= ny < ROOM_H):
            self.change_room(dx, dy)
            return

        target = self.room.at(nx, ny)
        if target == "D":
            if self.keys > 0:
                self.keys -= 1
                self.room.grid[ny][nx] = "d"
                self.say("the lock gives")
            else:
                self.say("locked — you need a key")
            return
        if target in WALLS:
            return
        if target in "C$KH":
            self.pickup(target, nx, ny)
        self.px, self.py = nx, ny
        if self.room.at(nx, ny) in HURTS:
            self.hurt(1, "the spikes bite")
        if self.room.at(nx, ny) in "<>":
            self.take_stairs()

    def change_room(self, dx: int, dy: int) -> None:
        nxt = (self.rpos[0] + dx, self.rpos[1] + dy)
        if nxt not in self.rooms():
            return
        self.rpos = nxt
        self.room = self.load_room()
        if dx:
            self.px = ROOM_W - 1 if dx < 0 else 0
        if dy:
            self.py = ROOM_H - 1 if dy < 0 else 0
        # Never arrive inside a wall.
        if not self.room.walkable(self.px, self.py):
            for probe in range(ROOM_H):
                for cand in ((self.px, probe), (probe, self.py)):
                    if self.room.walkable(*cand):
                        self.px, self.py = cand
                        break
                else:
                    continue
                break
        self.save_state()

    def take_stairs(self) -> None:
        dest = STAIRS.get((self.map, self.rpos))
        if not dest:
            return
        self.map, self.rpos = dest[0], dest[1]
        self.room = self.load_room()
        for y in range(ROOM_H):
            for x in range(ROOM_W):
                if self.room.walkable(x, y) and self.room.at(x, y) not in "<>^":
                    self.px, self.py = x, y
                    self.say(self.room.name)
                    self.save_state()
                    return

    def hurt(self, amount: int, why: str) -> None:
        if self.invuln > 0:
            return
        self.hearts -= amount
        self.invuln = IFRAMES
        self.say(why)

    def swing_sword(self) -> None:
        self.swing = SWING_TIME
        tx, ty = self.px + self.face[0], self.py + self.face[1]
        for e in self.room.enemies:
            if e.alive and (e.x, e.y) == (tx, ty):
                e.hp -= 1
                e.hurt = 0.18
                if e.hp <= 0:
                    e.alive = False
                    self.embers += 1
                    if e.kind == "B":
                        self.taken.add(((self.map, self.rpos), e.x, e.y))
                        self.won = True

    def move_enemies(self, dt: float) -> None:
        for e in self.room.enemies:
            if not e.alive:
                continue
            e.hurt = max(0.0, e.hurt - dt)
            e.timer -= dt
            if e.timer > 0:
                continue
            e.timer = e.speed
            if e.kind == "b" and random.random() < 0.45:
                dx, dy = random.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
            else:
                dx = (self.px > e.x) - (self.px < e.x)
                dy = (self.py > e.y) - (self.py < e.y)
                if dx and dy:                      # one axis at a time
                    if random.random() < 0.5:
                        dy = 0
                    else:
                        dx = 0
            nx, ny = e.x + dx, e.y + dy
            if self.room.walkable(nx, ny) and self.room.at(nx, ny) != "^":
                if (nx, ny) != (self.px, self.py):
                    e.x, e.y = nx, ny

            if (e.x, e.y) == (self.px, self.py) or (
                    abs(e.x - self.px) + abs(e.y - self.py) == 0):
                self.hurt(2 if e.kind == "B" else 1, f"the {e.kind and 'thing'} hits you")

    # ------------------------------------------------------------- state
    def save_state(self) -> None:
        self.save.update(hearts=self.hearts, max_hearts=self.max_hearts,
                         keys=self.keys, embers=self.embers,
                         taken=[list(t) for t in self.taken],
                         map=self.map, room=list(self.rpos),
                         px=self.px, py=self.py, won=self.won)
        ts.save(self.save)

    # ------------------------------------------------------------- loop
    def run(self) -> None:
        self.banner(["E M B E R L I G H T", ""] + INTRO + ["", "any key to begin"])
        while True:
            self.loop.poll()
            if self.loop.pressed(ord("q"), 27):
                self.save_state()
                return
            if self.loop.pressed(ord(" ")):
                self.swing_sword()

            dt = self.loop.tick()
            self.swing = max(0.0, self.swing - dt)
            self.invuln = max(0.0, self.invuln - dt)
            if self.msg_timer > 0:
                self.msg_timer -= dt
                if self.msg_timer <= 0:
                    self.message = ""

            self.mx -= dt
            self.my -= dt
            left = self.loop.held(curses.KEY_LEFT, ord("a"))
            right = self.loop.held(curses.KEY_RIGHT, ord("d"))
            up = self.loop.held(curses.KEY_UP, ord("w"))
            down = self.loop.held(curses.KEY_DOWN, ord("s"))
            if self.mx <= 0 and (left or right):
                self.mx = STEP_X
                self.try_move(-1 if left else 1, 0)
            elif self.my <= 0 and (up or down):
                self.my = STEP_Y
                self.try_move(0, -1 if up else 1)

            self.move_enemies(dt)

            if self.won:
                self.save_state()
                self.banner(["T H E   L A N T E R N   I S   L I T", ""] + WIN +
                            ["", "any key to leave"])
                return
            if self.hearts <= 0:
                self.hearts = self.max_hearts
                self.embers = max(0, self.embers - 3)
                self.map, self.rpos = "overworld", (0, 0)
                self.px, self.py = 23, 3
                self.room = self.load_room()
                self.save_state()
                self.banner(["YOU GO DOWN", "",
                             "Someone carries you back to the field.",
                             "You lose a few embers for the trouble.",
                             "", "any key to continue"])
            self.draw()


def run(stdscr, save: dict) -> None:
    curses.curs_set(0)
    Game(stdscr, save).run()


def main() -> int:
    save = ts.load({"hearts": 3, "max_hearts": 3, "keys": 0, "embers": 0,
                    "taken": [], "map": "overworld", "room": [0, 0],
                    "px": 23, "py": 3, "won": False, "version": 1})
    try:
        curses.wrapper(run, save)
    finally:
        ts.save(save)
    ts.tv("Emberlight")
    ts.tv_print(ts.title("E M B E R L I G H T"))
    ts.tv_print()
    ts.tv_print(ts.box([
        f"  hearts     {save['hearts']}/{save['max_hearts']}",
        f"  keys       {save['keys']}",
        f"  embers     {save['embers']}",
        f"  lantern    {'lit' if save['won'] else 'still dark'}",
    ], fg="yellow"))
    ts.tv_print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
