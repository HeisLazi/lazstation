"""Unbound -- the debut fight.

A single bout against the ring's own culled favourite. This is Stage 2 of
the plan (docs/UNBOUND-PLAN.md): the renderer, sitting on top of an engine
(fighter.py, bout.py) that was proven headless first -- telegraphed strikes,
a body with four locations, injury decoupled from who wins.

Everything you'd want to edit -- the opponent, the words -- lives in
content.py. The rules live in fighter.py and bout.py.
"""
import curses
import random
import sys
import time

import termstation_sdk as ts
import termstation_fx as fx

import ai
from bout import ATTACKS, BLOCKS, Bout, RING_W
from content import BARKS_LOSE, BARKS_WIN, DEBUT, LOC_LABEL, PLAYER_NAME
from fighter import LOCATIONS, Fighter

COL_BG = fx.rgb(14, 13, 18)
COL_TEXT = fx.rgb(196, 188, 176)
COL_DIM = fx.rgb(110, 104, 96)
COL_RULE = fx.rgb(58, 52, 46)
COL_YOU = fx.rgb(230, 210, 160)
COL_FOE = fx.rgb(200, 110, 100)
COL_HP = fx.rgb(190, 60, 55)
COL_STAM = fx.rgb(90, 150, 200)
COL_WARN = fx.rgb(226, 78, 60)
COL_SAND = fx.rgb(150, 130, 95)

COND_COLOR = {
    "clean": COL_DIM,
    "light": fx.rgb(210, 190, 90),
    "moderate": fx.rgb(230, 140, 60),
    "severe": fx.rgb(220, 60, 55),
}

ATTACK_KEYS = {"1": "kick", "2": "body", "3": "arm", "4": "head"}
BLOCK_KEYS = {"q": "block_leg", "w": "block_ribs", "e": "block_arm", "r": "block_head"}
MOVE_KEYS = {"a": "advance", "s": "retreat", "d": "dodge", " ": "wait"}
ATTACK_LABEL = {"kick": "Kick (leg)", "body": "Body (ribs)", "arm": "Arm", "head": "Head"}


class Game:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.rng = random.Random()
        self.layout()
        self.reset()

    def layout(self):
        self.win, self.screen = ts.tv_curses(self.stdscr, "Unbound")
        self.pal = fx.Palette(curses)
        self.canvas = fx.Canvas(self.screen.width, self.screen.height)
        self.win.nodelay(False)
        self.win.keypad(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def reset(self):
        self.you = Fighter(PLAYER_NAME, hp=42, stamina=10, power=6, read=0.6, block=0.4)
        self.foe = Fighter(DEBUT["name"], hp=DEBUT["hp"], stamina=DEBUT["stamina"],
                            power=DEBUT["power"], read=DEBUT["read"], block=DEBUT["block"])
        self.bout = Bout(self.you, self.foe, rng=self.rng)
        self.log = list(DEBUT["intro"])
        self.over = None

    # ------------------------------------------------------------ drawing
    def bar(self, cur, mx, width=18):
        cur = max(0, cur)
        fill = int(width * cur / mx) if mx else 0
        return "[" + "#" * fill + "." * (width - fill) + "]"

    def draw_fighter_row(self, c, y, name, f, col, W):
        c.text(1, y, f"{name[:22]:22}", col, COL_BG)
        c.text(24, y, self.bar(f.hp, f.max_hp), COL_HP, COL_BG)
        c.text(24 + 20, y, f"hp {int(f.hp):3}/{f.max_hp}", COL_TEXT, COL_BG)
        x = 1
        for loc in LOCATIONS:
            cond = f.cond(loc)
            label = f"{LOC_LABEL[loc]}:{cond}"
            if x + len(label) >= W - 1:
                break
            c.text(x, y + 1, label, COND_COLOR[cond], COL_BG)
            x += len(label) + 3

    def draw_ring(self, c, y, W):
        ox = max(1, (W - RING_W * 4) // 2)
        for i in range(RING_W):
            c.put(ox + i * 4, y, "·", COL_SAND, COL_BG)
        yx = ox + self.you.pos * 4
        fx_ = ox + self.foe.pos * 4
        c.text(yx, y, "@", COL_YOU, COL_BG)
        c.text(fx_, y, "#", COL_FOE, COL_BG)
        if self.foe.pending:
            loc = self.foe.pending["loc"]
            msg = f"{self.foe.name} is throwing a {LOC_LABEL[loc]} strike -- {loc}!"
            c.text(1, y + 2, msg[:W - 2], COL_WARN, COL_BG)
        elif self.you.pending:
            c.text(1, y + 2, f"you're mid-motion -- committed.", COL_DIM, COL_BG)
        else:
            c.text(1, y + 2, "read him. wait for the opening.", COL_DIM, COL_BG)

    def draw(self):
        c = self.canvas
        W, H = self.screen.width, self.screen.height
        c.clear(" ", COL_TEXT, COL_BG)

        self.draw_fighter_row(c, 0, "You", self.you, COL_YOU, W)
        c.text(0, 2, "-" * W, COL_RULE, COL_BG)
        self.draw_ring(c, 4, W)
        c.text(0, 7, "-" * W, COL_RULE, COL_BG)
        self.draw_fighter_row(c, 8, self.foe.name, self.foe, COL_FOE, W)
        c.text(0, 10, "-" * W, COL_RULE, COL_BG)

        for i, line in enumerate(self.log[-2:]):
            c.text(1, 11 + i, line[:W - 2], COL_TEXT, COL_BG)
        c.text(0, 13, "-" * W, COL_RULE, COL_BG)

        menu1 = "1:Kick 2:Body 3:Arm 4:Head"
        menu2 = "q:BlockLeg w:BlockRibs e:BlockArm r:BlockHead"
        menu3 = "d:Dodge a:Advance s:Retreat space:Wait  ?:help  Q:quit"
        c.text(1, 14, menu1[:W - 2], fx.AMBER, COL_BG)
        c.text(1, 15, menu2[:W - 2], fx.AMBER, COL_BG)
        c.text(1, 16, menu3[:W - 2], COL_DIM, COL_BG)

        self.canvas.blit(self.win, self.pal, 0, 0)
        self.win.noutrefresh()
        curses.doupdate()

    # -------------------------------------------------------------- input
    def prompt(self):
        while True:
            key = self.win.getch()
            if key == curses.KEY_RESIZE:
                self.layout()
                self.draw()
                continue
            if key in (ord("Q"), 27):
                return None
            if key == ord("?"):
                self.help()
                continue
            ch = chr(key) if 32 <= key < 127 else None
            if ch in ATTACK_KEYS:
                return ATTACK_KEYS[ch]
            if ch in BLOCK_KEYS:
                return BLOCK_KEYS[ch]
            if ch in MOVE_KEYS:
                return MOVE_KEYS[ch]

    def help(self):
        self.win.clear()
        c = self.canvas
        W, H = self.screen.width, self.screen.height
        c.clear(" ", COL_TEXT, COL_BG)
        lines = [
            "A committed strike shows what it's aiming at and where --",
            "block the SAME location to blunt it, dodge to try to avoid",
            "it outright, or close in and throw your own strike while he",
            "is still mid-motion: that cancels his strike and lands yours.",
            "",
            "Every hit that lands goes somewhere on your body, and it",
            "outlives this exchange. A hurt leg costs you range. A hurt",
            "head costs you reads. Winning doesn't undo any of it --",
            "only time, or staying out of the way, does that.",
        ]
        top = max(1, (H - len(lines)) // 2)
        for i, line in enumerate(lines):
            c.text(max(1, (W - len(line)) // 2), top + i, line[:W - 2], COL_TEXT, COL_BG)
        c.blit(self.win, self.pal, 0, 0)
        self.win.noutrefresh()
        curses.doupdate()
        self.win.getch()
        self.win.clear()

    # --------------------------------------------------------------- loop
    def run(self):
        while True:
            self.draw()
            action = self.prompt()
            if action is None:
                return "quit"
            foe_action = ai.choose(self.bout, self.foe, self.you, self.rng)
            self.bout.step(action, foe_action)
            self.log = self.bout.log
            if self.bout.over:
                self.over = self.bout.over
                break
        self.draw()
        return self.finish()

    def finish(self):
        self.win.clear()
        c = self.canvas
        W, H = self.screen.width, self.screen.height
        c.clear(" ", COL_TEXT, COL_BG)
        won = self.over is self.you
        title = "YOU'RE STILL STANDING" if won else "THE SAND TAKES YOU DOWN"
        col = fx.rgb(150, 210, 160) if won else COL_WARN
        c.text(max(0, (W - len(title)) // 2), 3, title, col, COL_BG)
        bark = self.rng.choice(BARKS_WIN if won else BARKS_LOSE)
        c.text(max(0, (W - len(bark)) // 2), 5, bark[:W - 2], COL_TEXT, COL_BG)
        stats = (f"you took {self.you.taken:.0f} across the fight -- "
                 f"worst: {self.you.worst_location()} ({self.you.cond(self.you.worst_location())})")
        c.text(max(0, (W - len(stats)) // 2), 7, stats[:W - 2], COL_DIM, COL_BG)
        foot = "press any key"
        c.text(max(0, (W - len(foot)) // 2), 9, foot, COL_DIM, COL_BG)
        c.blit(self.win, self.pal, 0, 0)
        self.win.noutrefresh()
        curses.doupdate()
        self.win.getch()
        return "win" if won else "lose"


def run(stdscr):
    g = Game(stdscr)
    return g.run()


def main() -> int:
    save = ts.load({"version": 1, "fights": 0, "wins": 0})
    try:
        outcome = curses.wrapper(run)
    except KeyboardInterrupt:
        return 130
    save["fights"] = save.get("fights", 0) + 1
    if outcome == "win":
        save["wins"] = save.get("wins", 0) + 1
    ts.save(save)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
