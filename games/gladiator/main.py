#!/usr/bin/env python3
"""Gladiator -- full-screen arena combat.

A curses game. It takes over the whole terminal, which is the other shape a
TermStation game can have; the launcher hands the TTY over completely and
takes it back when this process exits.
"""
from __future__ import annotations

import curses
import random
import sys
import time

import termstation_fx as fx
import termstation_sdk as ts

P_HP = fx.rgb(110, 210, 110)
P_STAM = fx.rgb(90, 160, 240)
P_CROWD = fx.rgb(210, 120, 220)
P_WARN = fx.rgb(230, 80, 70)
P_GOOD = fx.rgb(120, 220, 230)
P_DIM = fx.rgb(150, 145, 135)
P_GOLD = fx.rgb(240, 200, 90)
DIM_ = fx.rgb(95, 90, 85)
SAND = fx.rgb(190, 165, 120)

OPPONENTS = [
    ("Straw Dummy",     18, 3, "flails wildly"),
    ("Drunk Legionary", 26, 4, "swings hard and slow"),
    ("Net Fighter",     32, 5, "keeps his distance"),
    ("Thracian",        40, 6, "reads your feet"),
    ("Beast Handler",   46, 7, "smells of iron and dog"),
    ("Twin of Capua",   52, 8, "moves like a mirror"),
    ("The Butcher",     60, 10, "does not blink"),
    ("Champion of Rome",70, 11, "has never lost"),
    ("The Undefeated",  82, 13, "wears your name on his shield"),
    ("Editor's Chosen", 95, 15, "fights for the emperor"),
]

STANCES = {
    "aggressive": ("lunges forward", 1.35, 1.30),
    "measured":   ("circles slowly", 1.00, 1.00),
    "defensive":  ("raises his shield", 0.70, 0.65),
}


class Fighter:
    def __init__(self, name: str, hp: int, power: int) -> None:
        self.name = name
        self.max_hp = self.hp = hp
        self.power = power
        self.stance = "measured"
        self.guard = 0

    @property
    def alive(self) -> bool:
        return self.hp > 0


class Arena:
    def __init__(self, stdscr, save: dict) -> None:
        self.stdscr = stdscr
        self.s, self.screen = ts.tv_curses(stdscr, "Gladiator")
        self.save = save
        self.palette = fx.Palette(curses)
        self.canvas = fx.Canvas(self.screen.width, self.screen.height)
        self.sparks = fx.Particles()
        self.bout = 1
        self.shake = fx.Shake()
        self.log: list[tuple[str, int]] = []
        self.crowd = 50
        self.stamina = 100
        self.max_stamina = 100

    # ------------------------------------------------------------- rendering
    def relayout(self) -> None:
        """Redraw the cabinet and re-inset the picture after a resize."""
        self.s, self.screen = ts.tv_curses(self.stdscr, "Gladiator")

    def put(self, y: int, x: int, text: str, color: int = SAND) -> None:
        self.canvas.text(x, y, text, color)

    def bar(self, y: int, x: int, label: str, value: int, maximum: int,
            width: int, color: int) -> None:
        value = max(0, value)
        filled = int(width * value / maximum) if maximum else 0
        self.put(y, x, f"{label:<8}", fx.PAPER)
        self.put(y, x + 8, "[", DIM_)
        self.put(y, x + 9, "█" * filled, color)
        self.put(y, x + 9 + filled, "░" * (width - filled), DIM_)
        self.put(y, x + 9 + width, f"] {value}/{maximum}", DIM_)

    def say(self, text: str, pair: int = P_DIM) -> None:
        self.log.append((text, pair))
        self.log = self.log[-5:]

    def draw(self, you: Fighter, foe: Fighter, bout: int) -> None:
        """Laid out for the picture area, not the terminal: at 80x24 the
        bezel leaves 76x20, so every row below is budgeted."""
        rows, cols = self.s.getmaxyx()
        width = cols - 2
        self.canvas = fx.Canvas(cols, rows, ambient=1.0)
        bar_w = max(10, min(22, width - 34))

        head = "T H E   A R E N A"
        self.put(0, 1, head, P_GOLD)
        right = f"bout {bout}/{len(OPPONENTS)}"
        self.put(0, max(len(head) + 3, width - len(right)), right, DIM_)

        self.bar(1, 1, "YOU", you.hp, you.max_hp, bar_w, P_HP)
        self.bar(2, 1, "stamina", self.stamina, self.max_stamina, bar_w, P_STAM)
        self.bar(3, 1, foe.name[:8].upper(), foe.hp, foe.max_hp, bar_w, P_WARN)
        self.put(4, 10, f"{foe.stance}: {STANCES[foe.stance][0]}"[:width - 10],
                 DIM_)
        self.bar(5, 1, "crowd", self.crowd, 100, bar_w, P_CROWD)
        mood = ("silent", "restless", "warming", "roaring")[min(3, self.crowd // 26)]
        self.put(5, min(width - 20, bar_w + 24), f"crowd {mood}",
                 P_CROWD)

        log_top, log_rows = 7, max(3, rows - 14)
        self.put(6, 0, "─" * width, DIM_)
        for i, (line, pair) in enumerate(self.log[-log_rows:]):
            self.put(log_top + i, 1, line[:width - 1], pair)

        actions = [
            ("a", "attack", "solid strike, 12 stamina"),
            ("h", "heavy", "risky, big damage, 25 stamina"),
            ("d", "defend", "guard up, recover stamina"),
            ("f", "feint", "bait his swing, works the crowd"),
            ("t", "taunt", "crowd favour, no defence"),
        ]
        base = rows - len(actions)
        self.put(base - 1, 0, "─" * width, DIM_)
        for i, (key, name, hint) in enumerate(actions):
            self.put(base + i, 1, f" {key} ", P_GOOD)
            self.put(base + i, 5, f"{name:<8}", SAND)
            self.put(base + i, 14, hint[:width - 15], DIM_)
        self.present()

    def present(self) -> None:
        """One blit: sparks over the picture, shaken if something just landed."""
        self.sparks.draw(self.canvas)
        self.s.erase()
        self.canvas.blit(self.s, self.palette,
                         shake=self.shake.update(1 / 30))
        self.stdscr.noutrefresh()
        self.s.noutrefresh()
        curses.doupdate()

    def impact(self, x: int, y: int, color: int, power: float = 1.6,
               frames: int = 9) -> None:
        """Play a hit: sparks, a shake, and a few animated frames so the blow
        is something you see rather than only read in the log."""
        # Thrown upward and outward, then pulled down: sparks that arc read
        # as an impact, sparks that drift read as smoke.
        # Speed and gravity are tuned so the arc peaks under a cell: sparks
        # that climb into the header read as a rendering fault, not an impact.
        self.sparks.emit(x, y, 12, speed=10, life=0.38, glyphs="*∙·",
                         color=color, angle=-1.57, spread=2.2, gravity=44)
        self.shake.kick(power)
        for _ in range(frames):
            self.sparks.update(1 / 30)
            self.present()
            time.sleep(1 / 45)

    def flash(self, text: str, pair: int = P_WARN) -> None:
        """A banner that fades up, holds, and fades away."""
        self.s.clear()
        rows, cols = self.s.getmaxyx()
        y = rows // 2
        x = max(0, (cols - len(text)) // 2)
        base = self.canvas
        for step in range(10):
            self.canvas = fx.Canvas(cols, rows, ambient=1.0)
            self.canvas.ch = list(base.ch)
            self.canvas.fg = list(base.fg)
            self.canvas.bg = list(base.bg)
            glow = fx.scale(pair, 0.35 + 0.65 * min(1.0, step / 4))
            self.canvas.text(x, y, text, glow)
            self.present()
            time.sleep(0.035)
        time.sleep(0.3)

    # ------------------------------------------------------------- combat
    def player_turn(self, you: Fighter, foe: Fighter, key: int) -> bool:
        """Returns False if the key was not a valid action."""
        ch = chr(key).lower() if 32 <= key < 127 else ""
        damage = 0

        if ch == "a":
            if self.stamina < 12:
                self.say("you are too winded to swing", P_WARN)
                return True
            self.stamina -= 12
            damage = random.randint(6, 11)
        elif ch == "h":
            if self.stamina < 25:
                self.say("no strength left for that", P_WARN)
                return True
            self.stamina -= 25
            if random.random() < 0.72:
                damage = random.randint(14, 22)
                self.crowd = min(100, self.crowd + 6)
                self.say("a heavy blow — the crowd rises!", P_CROWD)
            else:
                self.say("you overswing and stumble", P_WARN)
                you.guard = -3
        elif ch == "d":
            you.guard = 8
            self.stamina = min(self.max_stamina, self.stamina + 22)
            self.say("you set your shield and breathe", P_GOOD)
        elif ch == "f":
            self.stamina = max(0, self.stamina - 6)
            if random.random() < 0.6:
                foe.stance = "aggressive"
                self.crowd = min(100, self.crowd + 9)
                self.say("your feint draws him in — they love it", P_CROWD)
                you.guard = 5
            else:
                self.say("he does not take the bait", P_DIM)
        elif ch == "t":
            self.crowd = min(100, self.crowd + 14)
            you.guard = -5
            self.say("you raise your arms to the stands!", P_CROWD)
        else:
            return False

        if damage:
            if foe.stance == "defensive":
                damage = int(damage * 0.6)
            foe.hp -= damage
            self.say(f"you strike for {damage}", P_GOOD)
            self.draw(you, foe, self.bout)
            self.impact(34, 4, P_GOLD if damage > 14 else P_GOOD,
                        power=2.4 if damage > 14 else 1.4)
        return True

    def foe_turn(self, you: Fighter, foe: Fighter) -> None:
        if not foe.alive:
            return
        # He fights harder as he bleeds.
        hurt = foe.hp / foe.max_hp
        foe.stance = random.choices(
            list(STANCES), weights=[3 if hurt < 0.4 else 1, 3, 2 if hurt < 0.5 else 1]
        )[0]
        verb, atk_mult, _ = STANCES[foe.stance]

        if random.random() < 0.12:
            self.say(f"{foe.name} {verb} and holds", P_DIM)
            return

        damage = int(random.randint(3, foe.power) * atk_mult)
        damage = max(0, damage - max(0, you.guard))
        you.guard = max(0, you.guard - 4)
        if damage <= 0:
            self.say("you turn his blade aside", P_GOOD)
            self.crowd = min(100, self.crowd + 3)
        else:
            you.hp -= damage
            self.say(f"{foe.name} hits you for {damage}", P_WARN)
            self.draw(you, foe, self.bout)
            self.impact(12, 2, P_WARN, power=2.0)

    def fight(self, you: Fighter, foe: Fighter, bout: int) -> bool:
        """One bout. Returns True if the player survives it."""
        self.bout = bout
        self.s.clear()
        self.log.clear()
        self.say(f"{foe.name} enters the sand.", P_WARN)
        self.say(f"He {OPPONENTS[bout - 1][3]}.", P_DIM)

        while you.alive and foe.alive:
            self.draw(you, foe, bout)
            try:
                key = self.s.getch()
            except KeyboardInterrupt:
                return False
            if key in (ord("q"), 27):
                if self.confirm("Yield the bout? (y/n)"):
                    return False
                continue
            if key == curses.KEY_RESIZE:
                self.relayout()
                continue
            if not self.player_turn(you, foe, key):
                continue

            if not foe.alive:
                break
            self.foe_turn(you, foe)
            self.stamina = min(self.max_stamina, self.stamina + 4)

            if not you.alive:
                # The crowd can call for your life to be spared.
                if self.crowd >= 70 and not self.save.get("_spared_this_run"):
                    self.save["_spared_this_run"] = True
                    you.hp = max(8, you.max_hp // 4)
                    self.draw(you, foe, bout)
                    self.flash("MITTE!  THE CROWD SPARES YOU", P_CROWD)
                    self.say("the editor turns his thumb — you live", P_CROWD)
                    self.crowd = 40

        self.draw(you, foe, bout)
        if foe.alive:
            self.flash("YOU FALL", P_WARN)
            return False
        self.flash(f"{foe.name.upper()} IS DOWN", P_GOOD)
        return True

    def confirm(self, question: str) -> bool:
        rows, cols = self.s.getmaxyx()
        self.put(rows - 1, 2, question + " ", P_WARN)
        self.present()
        return self.s.getch() in (ord("y"), ord("Y"))

    def between_bouts(self, you: Fighter, gold: int) -> None:
        # A screen transition needs a forced repaint: erase() only queues the
        # change, and curses may leave the previous screen's text standing.
        self.s.clear()
        rows, cols = self.s.getmaxyx()
        self.canvas = fx.Canvas(cols, rows, ambient=1.0)
        lines = [
            ("The gate closes behind you.", P_DIM),
            ("", P_DIM),
            (f"purse        {gold} denarii", P_GOLD),
            (f"wounds       {you.max_hp - you.hp} taken", P_WARN),
            (f"crowd favour {self.crowd}/100", P_CROWD),
            ("", P_DIM),
            ("  r  rest      heal 25, crowd forgets you (-10)", P_GOOD),
            ("  t  train     +6 max health, costs 30 denarii", P_GOOD),
            ("  o  oil up    +15 crowd favour, costs 20 denarii", P_CROWD),
            ("  enter        back to the sand", P_DIM),
        ]
        for i, (line, pair) in enumerate(lines):
            self.put(1 + i, 3, line, pair)
        self.present()
        return None


def run(stdscr, save: dict) -> dict:
    curses.curs_set(0)
    stdscr.keypad(True)

    arena = Arena(stdscr, save)
    you = Fighter("You", 60 + save.get("training", 0) * 6, 10)
    gold = save.get("gold", 0)
    bout = 1

    for name, hp, power, _ in OPPONENTS:
        foe = Fighter(name, hp, power)
        if not arena.fight(you, foe, bout):
            save["deaths"] = save.get("deaths", 0) + 1
            save["best_bout"] = max(save.get("best_bout", 0), bout - 1)
            save["gold"] = gold
            return {"won": False, "bout": bout, "gold": gold}

        if bout == 1:
            ts.unlock("first-blood", "First Blood", "Survived your first bout")
        if arena.crowd >= 90:
            ts.unlock("crowd-darling", "They Chant Your Name",
                      "Won the crowd almost completely over")
        purse = 20 + bout * 15 + arena.crowd // 5
        gold += purse
        save["wins"] = save.get("wins", 0) + 1
        bout += 1

        if bout > len(OPPONENTS):
            break

        # camp between bouts
        while True:
            arena.between_bouts(you, gold)
            key = stdscr.getch()
            if key in (10, 13, curses.KEY_ENTER):
                break
            if key in (ord("r"), ord("R")):
                you.hp = min(you.max_hp, you.hp + 25)
                arena.crowd = max(0, arena.crowd - 10)
            elif key in (ord("t"), ord("T")) and gold >= 30:
                gold -= 30
                you.max_hp += 6
                you.hp += 6
                save["training"] = save.get("training", 0) + 1
            elif key in (ord("o"), ord("O")) and gold >= 20:
                gold -= 20
                arena.crowd = min(100, arena.crowd + 15)
            elif key in (ord("q"), 27):
                save["gold"] = gold
                return {"won": False, "bout": bout, "gold": gold, "retired": True}
        arena.stamina = arena.max_stamina

    save["gold"] = gold
    save["best_bout"] = len(OPPONENTS)
    save["rudis"] = True
    ts.unlock("rudis", "The Wooden Sword", "Won your freedom in the arena")
    return {"won": True, "bout": len(OPPONENTS), "gold": gold}


def main() -> int:
    save = ts.load({"wins": 0, "deaths": 0, "gold": 0, "training": 0, "best_bout": 0})
    save["_spared_this_run"] = False

    try:
        outcome = curses.wrapper(run, save)
    except KeyboardInterrupt:
        ts.save(save)
        return 130

    save.pop("_spared_this_run", None)
    ts.save(save)

    ts.tv("Gladiator")
    ts.tv_print(ts.title("G L A D I A T O R"))
    if outcome["won"]:
        ts.tv_print(ts.color("\n  You are handed the rudis — the wooden sword.", "bright_yellow"))
        ts.tv_print(ts.color("  You walk out of the arena a free man.\n", "bright_yellow"))
    elif outcome.get("retired"):
        ts.tv_print(ts.color(f"\n  You walk away after {outcome['bout'] - 1} bouts.\n", "cyan"))
    else:
        ts.tv_print(ts.color(f"\n  You fall in bout {outcome['bout']}. The sand drinks it up.\n",
                       "bright_red"))
    ts.tv_print(ts.box([
        f"  career wins    {save['wins']}",
        f"  deaths         {save['deaths']}",
        f"  furthest bout  {save['best_bout']}/{len(OPPONENTS)}",
        f"  denarii        {save['gold']}",
        f"  training       +{save['training'] * 6} max health",
    ], fg="yellow"))
    ts.tv_print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
