"""The Hollow -- vertical slice.

One room, two echoes, everything the finished game has: telegraphed attacks,
the punish, knockback, charges, barks, animation, the Rival, and a death
screen that tells you a story instead of a score.

The rules live here. Everything you would want to change -- the room, the
enemies, the words -- lives in content.py.

THE ONE IDEA: an enemy winding up is an enemy that is open. Hit it mid-ritual
and you do full damage and break the loop, so the blow never lands. Every
telegraph is therefore both a threat and an invitation.
"""
import curses
import math
import random
import sys
import time

import termstation_sdk as ts
import termstation_fx as fx

from content import (BARKS, DEATH_TITLE, ENEMIES, RIVAL, ROOM, TILES,
                     VICTORY_TITLE)

RW, RH = len(ROOM[0]), len(ROOM)

IDLE, WINDUP, RECOVER = "idle", "windup", "recover"

PLAYER_HP = 6
START_CHARGES = 2
PUNISH_DAMAGE = 3
GRAZE_DAMAGE = 1

DIRS = {
    "h": (-1, 0), "j": (0, 1), "k": (0, -1), "l": (1, 0),
    "a": (-1, 0), "s": (0, 1), "w": (0, -1), "d": (1, 0),
    curses.KEY_LEFT: (-1, 0), curses.KEY_RIGHT: (1, 0),
    curses.KEY_UP: (0, -1), curses.KEY_DOWN: (0, 1),
}

COL_BG = fx.rgb(16, 15, 22)
COL_PLAYER = fx.rgb(250, 240, 220)
COL_WARN = fx.rgb(226, 78, 60)
COL_WARN_HOT = fx.rgb(255, 170, 120)
COL_TEXT = fx.rgb(190, 182, 172)
COL_DIM = fx.rgb(112, 106, 100)
COL_HEART = fx.rgb(220, 70, 70)
COL_CHARGE = fx.rgb(120, 200, 230)


class Echo:
    """One of the dead, repeating itself."""

    def __init__(self, kind, x, y):
        spec = ENEMIES[kind]
        self.kind = kind
        self.spec = spec
        self.name = spec["name"]
        self.x, self.y = x, y
        self.hp = spec["hp"]
        self.state = IDLE
        self.timer = 0
        self.marks = []          # the tiles it has committed to
        self.flash = 0.0

    @property
    def alive(self):
        return self.hp > 0


class Game:
    def __init__(self, stdscr, save):
        self.stdscr = stdscr
        self.save = save
        self.rng = random.Random()
        self.layout()
        self.reset()

    # ------------------------------------------------------------- layout
    def layout(self):
        self.win, self.screen = ts.tv_curses(self.stdscr, "The Hollow")
        self.pal = fx.Palette(curses)
        self.canvas = fx.Canvas(self.screen.width, self.screen.height)
        self.win.nodelay(True)
        self.win.keypad(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.shake = fx.Shake()

    def reset(self):
        self.grid = [list(r) for r in ROOM]
        self.enemies = []
        self.px = self.py = 0
        for y in range(RH):
            for x in range(RW):
                ch = self.grid[y][x]
                if ch == "@":
                    self.px, self.py = x, y
                    self.grid[y][x] = "."
                elif ch == "1":
                    self.enemies.append(Echo("duelist", x, y))
                    self.grid[y][x] = "."
                elif ch == "2":
                    self.enemies.append(Echo("censer", x, y))
                    self.grid[y][x] = "."
                elif ch == "R":
                    self.grid[y][x] = "."
                    self.rival_at = (x, y)
        self.hp = PLAYER_HP
        self.charges = START_CHARGES
        self.turns = 0
        self.log = []
        self.pending_step = False
        self.read_note = False
        self.over = None
        self.killed_by = None
        self.hits_taken = 0
        self.punishes = 0
        self.grazes = 0
        self.say("You step into the transept. Two shapes in the dark.")

    # -------------------------------------------------------------- world
    def tile(self, x, y):
        if 0 <= x < RW and 0 <= y < RH:
            return self.grid[y][x]
        return "#"

    def walkable(self, x, y):
        return TILES.get(self.tile(x, y), TILES["#"])["walk"]

    def enemy_at(self, x, y):
        for e in self.enemies:
            if e.alive and e.x == x and e.y == y:
                return e
        return None

    def say(self, text):
        self.log.append(text)
        del self.log[:-40]

    def bark(self, key, e=None):
        opts = BARKS.get(key)
        if not opts:
            return
        line = self.rng.choice(opts)
        if e is not None:
            line = line.format(name=e.name, tell=e.spec["tell"])
        self.say(line)

    # --------------------------------------------------------- telegraphs
    def commit(self, e):
        """Lock in the tiles this echo will strike. Locked = dodgeable."""
        e.state = WINDUP
        e.timer = e.spec["windup"]
        e.marks = self.shape_tiles(e)
        self.bark("windup", e)

    def shape_tiles(self, e):
        shape = e.spec["shape"]
        if shape == "burst":
            return [(e.x + dx, e.y + dy)
                    for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                    if self.tile(e.x + dx, e.y + dy) != "#"]
        # line: toward the player, along the dominant axis
        dx = self.px - e.x
        dy = self.py - e.y
        if abs(dx) >= abs(dy):
            step = (1 if dx > 0 else -1, 0)
        else:
            step = (0, 1 if dy > 0 else -1)
        out = []
        x, y = e.x, e.y
        for _ in range(e.spec["reach"]):
            x += step[0]; y += step[1]
            if TILES.get(self.tile(x, y), TILES["#"])["blocks"]:
                break
            out.append((x, y))
        return out

    def in_range(self, e):
        d = max(abs(e.x - self.px), abs(e.y - self.py))
        if e.spec["shape"] == "burst":
            return d <= 1
        return d <= e.spec["reach"] and (e.x == self.px or e.y == self.py
                                         or abs(e.x - self.px) == abs(e.y - self.py))

    def marked(self, x, y):
        return [e for e in self.enemies
                if e.alive and e.state == WINDUP and (x, y) in e.marks]

    # --------------------------------------------------------- the player
    def act_move(self, dx, dy, stepping=False):
        nx, ny = self.px + dx, self.py + dy
        target = self.enemy_at(nx, ny)
        if target:
            self.attack(target)
            return True
        if not self.walkable(nx, ny):
            return False
        if stepping:
            if self.charges <= 0:
                self.say("No charges left.")
                return False
            self.charges -= 1
            self.step_guard = True
            self.bark("stepthrough")
        self.px, self.py = nx, ny
        if self.tile(nx, ny) == "~":
            self.say("You wade. The water is colder than it should be.")
        return True

    def attack(self, e):
        if e.state == WINDUP:
            # The whole game, in four lines.
            e.hp -= PUNISH_DAMAGE
            e.state = RECOVER
            e.timer = 1
            e.marks = []
            e.flash = 1.0
            self.punishes += 1
            self.shake.kick(3.0)
            if e.alive:
                self.bark("staggered", e)
        else:
            e.hp -= GRAZE_DAMAGE
            e.flash = 0.6
            self.grazes += 1
            self.shake.kick(1.0)
            if e.alive:
                self.bark("hit_weak", e)
        if e.alive:
            self.knock(e)
        else:
            self.bark("kill", e)

    def knock(self, e):
        """Force, not damage. The board finishes what you start."""
        dx = (e.x > self.px) - (e.x < self.px)
        dy = (e.y > self.py) - (e.y < self.py)
        nx, ny = e.x + dx, e.y + dy
        if self.tile(nx, ny) == "^":
            e.hp -= 3
            self.bark("knock_brazier", e)
            if not e.alive:
                self.bark("kill", e)
            return
        if self.walkable(nx, ny) and not self.enemy_at(nx, ny):
            e.x, e.y = nx, ny
            if e.state == WINDUP:
                e.marks = self.shape_tiles(e)   # it re-aims from where it lands

    # ------------------------------------------------------------- a turn
    def turn(self):
        self.turns += 1
        struck = False
        for e in self.enemies:
            if not e.alive:
                continue
            if e.state == IDLE:
                if self.in_range(e):
                    self.commit(e)
                else:
                    self.approach(e)
            elif e.state == WINDUP:
                e.timer -= 1
                if e.timer <= 0:
                    struck |= self.strike(e)
            elif e.state == RECOVER:
                e.timer -= 1
                if e.timer <= 0:
                    e.state = IDLE
        self.enemies = [e for e in self.enemies if e.alive]
        self.step_guard = False
        if not self.enemies and self.over is None:
            self.over = "win"
        if self.hp <= 0 and self.over is None:
            self.over = "dead"
        if not struck and self.rng.random() < 0.10:
            self.bark("idle")

    def strike(self, e):
        hit = (self.px, self.py) in e.marks
        e.state = RECOVER
        e.timer = 1
        e.marks = []
        if hit and not getattr(self, "step_guard", False):
            self.hp -= e.spec["damage"]
            self.hits_taken += 1
            self.killed_by = e.name
            self.shake.kick(5.0)
            self.bark("struck")
            return True
        if hit:
            self.say("The blow passes through where you were.")
        return False

    def approach(self, e):
        dx = (self.px > e.x) - (self.px < e.x)
        dy = (self.py > e.y) - (self.py < e.y)
        for nx, ny in ((e.x + dx, e.y + dy), (e.x + dx, e.y), (e.x, e.y + dy)):
            if self.walkable(nx, ny) and not self.enemy_at(nx, ny) \
                    and (nx, ny) != (self.px, self.py):
                e.x, e.y = nx, ny
                return

    # ------------------------------------------------------------ drawing
    def draw(self, t):
        c = self.canvas
        W, H = self.screen.width, self.screen.height
        c.clear(" ", COL_TEXT, COL_BG)
        ox = max(0, (W - RW) // 2)
        oy = 2
        rows = H - 5

        # the room
        for y in range(min(RH, rows)):
            for x in range(RW):
                spec = TILES.get(self.grid[y][x], TILES["."])
                col = fx.rgb(*spec["rgb"])
                if spec["name"] == "brazier":
                    col = fx.mix(col, fx.rgb(255, 210, 120),
                                 0.5 + 0.5 * math.sin(t * 3 + x))
                c.put(ox + x, oy + y, spec["glyph"], col, COL_BG)

        # the Rival's mark, still there
        rx, ry = getattr(self, "rival_at", (-1, -1))
        if rx >= 0:
            c.put(ox + rx, oy + ry, "‡", fx.rgb(150, 190, 160), COL_BG)

        # telegraphs -- pulsing, because a threat should breathe
        pulse = 0.45 + 0.55 * abs(math.sin(t * 4.2))
        for e in self.enemies:
            if e.state != WINDUP:
                continue
            hot = e.timer <= 1
            base = COL_WARN_HOT if hot else COL_WARN
            for (mx, my) in e.marks:
                if 0 <= my < rows:
                    col = fx.mix(fx.rgb(70, 24, 24), base, pulse if hot else pulse * 0.7)
                    c.put(ox + mx, oy + my, "▒", col, COL_BG)

        # the echoes
        for e in self.enemies:
            col = fx.rgb(*e.spec["rgb"])
            if e.state == WINDUP:
                col = fx.mix(col, COL_WARN_HOT, 0.35 + 0.35 * pulse)
            elif e.state == RECOVER:
                col = fx.scale(col, 0.55)
            if e.flash > 0:
                col = fx.mix(col, fx.rgb(255, 255, 255), e.flash)
            c.put(ox + e.x, oy + e.y, e.spec["glyph"], col, COL_BG)

        c.put(ox + self.px, oy + self.py, "@", COL_PLAYER, COL_BG)

        self.draw_hud(c, W, t)
        self.draw_log(c, W, H)
        dx, dy = self.shake.update(1 / 30)
        c.blit(self.win, self.pal, 0, 0, shake=(dx, dy))
        self.win.noutrefresh()
        curses.doupdate()

    def draw_hud(self, c, W, t):
        hearts = "♥ " * self.hp + "· " * (PLAYER_HP - self.hp)
        c.text(1, 0, hearts.rstrip(), COL_HEART, COL_BG)
        ch = "◆ " * self.charges + "◇ " * (START_CHARGES - self.charges)
        c.text(15, 0, ch.rstrip(), COL_CHARGE, COL_BG)
        right = ""
        for e in self.enemies:
            if e.state == WINDUP:
                right = f"{e.name} strikes in {max(1, e.timer)}"
                break
        if not right:
            right = "read them. wait for the turn."
        c.text(max(24, W - len(right) - 1), 0, right[:W - 25],
               COL_WARN if "strikes" in right else COL_DIM, COL_BG)
        c.text(0, 1, "─" * W, fx.rgb(56, 52, 62), COL_BG)

    def draw_log(self, c, W, H):
        c.text(0, H - 3, "─" * W, fx.rgb(56, 52, 62), COL_BG)
        lines = self.log[-2:]
        for i, line in enumerate(lines):
            c.text(1, H - 2 + i, line[:W - 2], COL_TEXT, COL_BG)
        if self.pending_step:
            c.text(1, H - 1, "step through -- which way?"[:W - 2],
                   COL_CHARGE, COL_BG)

    # ------------------------------------------------------------ screens
    def screen_lines(self, title, lines, colour):
        self.win.clear()
        c = self.canvas
        W, H = self.screen.width, self.screen.height
        c.clear(" ", COL_TEXT, COL_BG)
        top = max(1, (H - len(lines) - 4) // 2)
        c.text(max(0, (W - len(title)) // 2), top, title, colour, COL_BG)
        for i, line in enumerate(lines):
            c.text(max(0, (W - len(line)) // 2), top + 2 + i, line[:W], COL_TEXT, COL_BG)
        foot = "press any key"
        c.text(max(0, (W - len(foot)) // 2), min(H - 1, top + 3 + len(lines)),
               foot, COL_DIM, COL_BG)
        c.blit(self.win, self.pal, 0, 0)
        self.win.noutrefresh()
        curses.doupdate()
        self.win.nodelay(False)
        self.win.getch()
        self.win.nodelay(True)
        self.win.clear()

    def death_story(self):
        """Not a score. A paragraph you could tell someone."""
        bits = [
            f"You lasted {self.turns} turns in the transept.",
            "",
            f"{self.killed_by} finished you." if self.killed_by
            else "The Hollow finished you.",
        ]
        if self.punishes:
            bits.append(f"You broke {self.punishes} ritual"
                        f"{'s' if self.punishes != 1 else ''} before it did.")
        else:
            bits.append("You never once caught one mid-ritual.")
            bits.append("That is the whole game, and you did not play it.")
        if self.grazes > self.punishes:
            bits.append("You traded more than you read.")
        if self.charges == START_CHARGES:
            bits.append("You died with both charges unspent.")
        bits.append("")
        bits.append("Ines Cabral is still below you, and still ahead.")
        return bits

    def victory_story(self):
        return [
            f"Two echoes stopped repeating. It took {self.turns} turns.",
            "",
            f"punished {self.punishes}   traded {self.grazes}   "
            f"hit {self.hits_taken}   charges left {self.charges}",
            "",
            "The stair down is behind the altar.",
            "Someone has already gone through it.",
        ]

    # --------------------------------------------------------------- loop
    def run(self):
        t0 = time.perf_counter()
        while True:
            t = time.perf_counter() - t0
            try:
                self.draw(t)
            except curses.error:
                pass
            key = self.win.getch()
            if key == -1:
                time.sleep(1 / 30)
                continue
            if key == curses.KEY_RESIZE:
                self.layout()
                continue
            if key in (ord("q"), 27):
                return "quit"
            if key == ord("?"):
                self.help()
                continue
            acted = self.handle(key)
            if acted:
                self.turn()
                self.check_note()
                if self.over:
                    return self.finish()
            for e in self.enemies:
                e.flash = max(0.0, e.flash - 0.25)

    def handle(self, key):
        ch = chr(key) if 32 <= key < 127 else key
        if self.pending_step:
            self.pending_step = False
            if ch in DIRS or key in DIRS:
                d = DIRS.get(ch, DIRS.get(key))
                return self.act_move(*d, stepping=True)
            self.say("Cancelled.")
            return False
        if ch == "e":
            if self.charges <= 0:
                self.say("No charges left. You are out of second chances.")
                return False
            self.pending_step = True
            return False
        if ch in (" ", "."):
            self.say("You wait. Let it commit first.")
            return True
        d = DIRS.get(ch, DIRS.get(key))
        if d:
            return self.act_move(*d)
        return False

    def check_note(self):
        if self.read_note:
            return
        rx, ry = getattr(self, "rival_at", (-1, -1))
        if max(abs(self.px - rx), abs(self.py - ry)) <= 1:
            self.read_note = True
            self.screen_lines(f"{RIVAL['name']} was here", RIVAL["note"],
                              fx.rgb(150, 190, 160))

    def help(self):
        self.screen_lines("HOW TO READ A FIGHT", [
            "move / attack   arrows, wasd or hjkl -- walk into a thing to hit it",
            "step through    e then a direction -- costs a charge, ignores the marks",
            "wait            space -- let it commit first",
            "",
            "Red tiles are where a blow is ALREADY going to land.",
            "An echo winding up is an echo that is OPEN:",
            "hit it now for full damage and the blow never happens.",
            "",
            "Hitting one that is not winding up barely scratches it.",
            "Knock them into the braziers.",
        ], fx.AMBER)

    def finish(self):
        if self.over == "win":
            self.screen_lines(VICTORY_TITLE, self.victory_story(), fx.rgb(150, 210, 160))
        else:
            self.screen_lines(DEATH_TITLE, self.death_story(), COL_WARN)
        return self.over


def run(stdscr, save):
    g = Game(stdscr, save)
    return g.run()


def main() -> int:
    save = ts.load({"version": 1, "runs": 0, "wins": 0, "best_turns": None})
    try:
        outcome = curses.wrapper(run, save)
    except KeyboardInterrupt:
        return 130
    save["runs"] = save.get("runs", 0) + 1
    if outcome == "win":
        save["wins"] = save.get("wins", 0) + 1
    ts.save(save)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
