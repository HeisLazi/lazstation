"""First playable Gladiator tactical duel.

The rules live in combat.py; this module only turns them into a bounded
full-screen terminal encounter.
"""
from __future__ import annotations

import curses
import time

import termstation_fx as fx
import termstation_sdk as ts

try:
    from .combat import (ActionKind, Arena, Duel, FighterState, Intent, Position,
                         Posture, WEAPONS, marksman_intent, profile_vitals)
except ImportError:
    from combat import (ActionKind, Arena, Duel, FighterState, Intent, Position,
                        Posture, WEAPONS, marksman_intent, profile_vitals)


PLAYER = fx.rgb(120, 220, 150)
ENEMY = fx.rgb(230, 100, 90)
GRID = fx.rgb(105, 100, 90)
FOCUS = fx.rgb(100, 190, 240)
GOLD = fx.rgb(240, 200, 90)
MUTED = fx.rgb(150, 145, 135)


def make_duel(player_name: str = "You", weapon_key: str = "blade",
              profile: dict | None = None) -> Duel:
    profile = profile or {}
    max_hp, max_stamina = profile_vitals(profile)
    return Duel(
        Arena(5, 5, cover={Position(2, 2)}),
        {
            player_name: FighterState(
                player_name, Position(0, 2),
                WEAPONS.get(weapon_key, WEAPONS["blade"]),
                max_hp=max_hp, hp=max_hp, max_stamina=max_stamina,
                stamina=max_stamina, height=profile.get("height", "average"),
                stats=dict(profile.get("stats", {}))),
            "The Marksman": FighterState("The Marksman", Position(4, 2),
                                         WEAPONS["bow"]),
        },
    )


class TacticalScreen:
    def __init__(self, stdscr, duel: Duel, player_name: str) -> None:
        self.stdscr = stdscr
        self.win, self.screen = ts.tv_curses(stdscr, "Gladiator")
        self.palette = fx.Palette(curses)
        self.duel = duel
        self.player_name = player_name
        self.log: list[str] = ["The gate opens. The crowd wants blood."]
        self.message = "Choose an action."
        self.ai_turn_count = 0

    def relayout(self) -> None:
        self.win, self.screen = ts.tv_curses(self.stdscr, "Gladiator")

    def add(self, events) -> None:
        for event in events:
            self.log.append(event.text)
        self.log = self.log[-4:]

    def put(self, canvas, x: int, y: int, text: str, colour=MUTED) -> None:
        canvas.text(x, y, text[:max(0, canvas.w - x)], colour)

    def bar(self, canvas, x: int, y: int, label: str, value: int,
            maximum: int, colour: int) -> None:
        width = 12
        filled = int(width * max(0, value) / max(1, maximum))
        self.put(canvas, x, y, f"{label:<7}[", MUTED)
        self.put(canvas, x + 9, y, "█" * filled, colour)
        self.put(canvas, x + 9 + filled, y, "░" * (width - filled), GRID)
        self.put(canvas, x + 9 + width, y, "]", MUTED)

    def draw(self) -> None:
        width, height = self.screen.width, self.screen.height
        canvas = fx.Canvas(width, height)
        you = self.duel.actor(self.player_name)
        foe = self.duel.actor("The Marksman")
        self.put(canvas, 1, 0, "T A C T I C A L   T R I A L", GOLD)
        self.put(canvas, max(1, width - 18), 0,
                 f"{'MELEE' if not foe.alive else 'DUEL'}", GOLD)
        self.bar(canvas, 1, 1, "YOU HP", you.hp, you.max_hp, PLAYER)
        self.bar(canvas, 1, 2, "STAM", you.stamina, you.max_stamina, FOCUS)
        self.bar(canvas, 1, 3, "POST", you.posture, you.max_posture, GOLD)
        self.bar(canvas, 1, 4, "FOCUS", you.focus, you.max_focus, FOCUS)
        self.put(canvas, 32, 1, f"enemy hp {foe.hp}/{foe.max_hp}", ENEMY)
        self.put(canvas, 32, 2, f"enemy ammo {foe.loaded}", ENEMY)
        self.put(canvas, 32, 3, f"enemy pos {foe.position.x},{foe.position.y}", MUTED)
        self.put(canvas, 32, 4, "cover = ▣", MUTED)

        gx, gy, cell = 3, 7, 5
        threatened = self.duel.threat_cells(self.player_name)
        for y in range(5):
            for x in range(5):
                pos = Position(x, y)
                glyph = "·"
                colour = GRID
                if pos in self.duel.arena.cover:
                    glyph, colour = "▣", GOLD
                if pos in threatened:
                    colour = fx.scale(colour, 1.35)
                if pos == you.position:
                    glyph, colour = "@", PLAYER
                elif pos == foe.position:
                    glyph, colour = "M", ENEMY
                self.put(canvas, gx + x * cell, gy + y * 2, glyph, colour)
        self.put(canvas, 1, 18, " ".join(self.log[-2:]), MUTED)
        self.put(canvas, 1, 19, self.message, GOLD)
        self.put(canvas, 1, height - 2,
                 "arrows move  a strike  g guard  c conceal  f focus  r reload  q quit",
                 PLAYER)
        self.win.erase()
        canvas.blit(self.win, self.palette)
        self.stdscr.noutrefresh()
        self.win.noutrefresh()
        curses.doupdate()

    def enemy_turn(self) -> None:
        foe = self.duel.actor("The Marksman")
        you = self.duel.actor(self.player_name)
        if not foe.alive:
            return
        self.ai_turn_count += 1
        self.duel.queue_intent(
            marksman_intent(self.duel, self.player_name, self.ai_turn_count))
        self.add(self.duel.resolve())

    def player_turn(self, key: int) -> bool:
        you = self.duel.actor(self.player_name)
        foe = self.duel.actor("The Marksman")
        if key == curses.KEY_RESIZE:
            self.relayout()
            return True
        if key in (ord("q"), 27):
            return False
        if key in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_RIGHT):
            directions = {
                curses.KEY_UP: (0, -1), curses.KEY_DOWN: (0, 1),
                curses.KEY_LEFT: (-1, 0), curses.KEY_RIGHT: (1, 0),
            }
            dx, dy = directions[key]
            self.add(self.duel.move(self.player_name, you.position.step(dx, dy)))
        elif key == ord("a"):
            self.add(self.duel.queue_intent(
                Intent(self.player_name, ActionKind.STRIKE, foe.position)))
        elif key == ord("g"):
            self.add(self.duel.queue_intent(Intent(self.player_name, ActionKind.GUARD)))
        elif key == ord("c"):
            self.add(self.duel.queue_intent(Intent(self.player_name, ActionKind.CONCEAL)))
        elif key == ord("f"):
            self.add(self.duel.queue_intent(Intent(self.player_name, ActionKind.FOCUS)))
        elif key == ord("r"):
            self.add(self.duel.queue_intent(Intent(self.player_name, ActionKind.RELOAD)))
        else:
            return True
        self.enemy_turn()
        return True

    def run(self) -> bool:
        self.win.keypad(True)
        while (self.duel.actor(self.player_name).alive
               and self.duel.actor("The Marksman").alive):
            self.draw()
            key = self.win.getch()
            if not self.player_turn(key):
                return False
        self.draw()
        self.message = ("The Marksman falls. The crowd has seen your read."
                        if self.duel.actor("The Marksman").hp <= 0
                        else "You fall beneath the Marksman's shot.")
        self.draw()
        time.sleep(0.35)
        return self.duel.actor(self.player_name).alive


class OpeningScreen:
    def __init__(self, stdscr, save: dict) -> None:
        self.stdscr = stdscr
        self.save = save
        self.win, self.screen = ts.tv_curses(stdscr, "Gladiator")
        self.palette = fx.Palette(curses)

    def draw_lines(self, title: str, lines: list[str], footer: str) -> None:
        canvas = fx.Canvas(self.screen.width, self.screen.height)
        width, height = self.screen.width, self.screen.height
        canvas.fill(0, 0, width, height, " ", fx.PAPER)
        canvas.box(1, 1, width - 2, height - 4, fx.STONE)
        canvas.text(3, 1, f" {title} ", GOLD)

        rail_width = min(27, max(20, width // 3))
        canvas.box(3, 3, rail_width, height - 8, fx.scale(fx.STONE, 0.9))
        canvas.text(5, 4, "SLAVE CHAMBERS", MUTED)
        canvas.text(5, 5, "───────────────", fx.scale(fx.STONE, 0.9))
        if "DUMMY" in title:
            art = [
                "       .---.       ",
                "      /|   |\\      ",
                "       |###|       ",
                "       |###|   o   ",
                "      /|   |\\ /|\\  ",
                "     /_|___|_\\ |   ",
                "       /   \\  / \\  ",
                "      /_____|       ",
            ]
            caption = "straw dummy / practice yard"
        elif "AUCTION" in title:
            art = [
                "       ______       ",
                "  ____/|_||_|\\____  ",
                " /___  |____|  ___\\ ",
                "     \\  ____  /     ",
                "      ||    ||      ",
                "      ||____||      ",
                "       \\____/       ",
            ]
            caption = "the cart leaves the market"
        else:
            art = [
                "       ______       ",
                "      /      \\      ",
                "     /  ____  \\     ",
                "     | |    | |     ",
                "     | |____| |     ",
                "     |   __   |     ",
                "     |__/  \\__|     ",
            ]
            caption = "property ledger / house mark"
        for row, art_line in enumerate(art, 7):
            canvas.text(5, row, art_line[:rail_width - 4], FOCUS)
        canvas.text(5, height - 7, caption[:rail_width - 4], MUTED)
        canvas.text(5, height - 5, "chapter 01", GOLD)
        canvas.text(5, height - 4, "THE FIRST CHAIN", MUTED)

        text_x = 3 + rail_width + 3
        text_width = width - text_x - 3
        canvas.text(text_x, 4, "—", GOLD)
        for index, line in enumerate(lines, 6):
            canvas.text(text_x, index, line[:text_width], MUTED)
        canvas.box(1, height - 2, width - 2, 2, fx.STONE)
        canvas.text(3, height - 1, f"[ {footer[:width - 8]} ]", PLAYER)
        self.win.erase()
        canvas.blit(self.win, self.palette)
        self.stdscr.noutrefresh()
        self.win.noutrefresh()
        curses.doupdate()

    def read_name(self) -> str:
        self.draw_lines("THE LEDGER", [
            "The auctioneer sold your body without asking your name.",
            "In the slave chambers, the clerk asks what to write.",
            "",
            "Name:",
        ], "type the name you claim, then press enter")
        curses.echo()
        try:
            raw = self.win.getstr(5, 9, 24)
        finally:
            curses.noecho()
        name = raw.decode("utf-8", "replace").strip()
        return name[:24] or "Mara"

    def customize_profile(self, name: str) -> dict | None:
        stats = {"might": 1, "agility": 1, "endurance": 1, "wit": 1}
        points = 4
        height = "average"
        while True:
            lines = [
                f"{name}, the chamber keeper measures you before the brands.",
                f"height: {height}   points left: {points}",
                "",
                "1 might      2 agility      3 endurance      4 wit",
                "each choice spends one point; a stat can reach 4",
                "",
            ]
            lines.extend(f"{index + 1}. {key:<10} {value}"
                         for index, (key, value) in enumerate(stats.items()))
            self.draw_lines("THE SLAVE CHAMBERS", lines,
                            "h change height   enter accept   q return")
            key = self.win.getch()
            if key in (ord("q"), 27):
                return None
            if key in (ord("1"), ord("2"), ord("3"), ord("4")) and points:
                chosen = list(stats)[key - ord("1")]
                if stats[chosen] < 4:
                    stats[chosen] += 1
                    points -= 1
            elif key == ord("h"):
                height = {"short": "average", "average": "tall", "tall": "short"}[height]
            elif key in (10, 13, curses.KEY_ENTER) and points == 0:
                return {"height": height, "stats": stats}

    def chores(self, name: str, profile: dict) -> None:
        self.draw_lines("THE FIRST WEEK", [
            f"{name} learns the chambers have no idle hours.",
            "Carry water. Scrub blood. Watch who gets fed first.",
            "",
            "The work is not freedom, but it buys one thing:",
            "a body less likely to be thrown away.",
            "",
            "You earn 3 denarii and a little knowledge of the house.",
        ], "press enter to continue")
        while self.win.getch() not in (10, 13, curses.KEY_ENTER):
            pass
        profile["chores_completed"] = 1
        self.save["gold"] = self.save.get("gold", 0) + 3

    def tutorial_weapon(self, name: str) -> str | None:
        self.draw_lines("THE DUMMY YARD", [
            f"The trainer points at a straw dummy, {name}.",
            "No class is assigned. The weapon you practice becomes",
            "the first language of your fighting style.",
            "",
            "1  Blade       close, precise, forgiving",
            "2  Spear       reach, control, commitment",
            "3  Javelin     ranged pressure, limited ammunition",
        ], "1-3 take a weapon   q return")
        while True:
            key = self.win.getch()
            if key in (ord("q"), 27):
                return None
            if key in (ord("1"), ord("2"), ord("3")):
                return {"1": "blade", "2": "spear", "3": "javelin"}[chr(key)]

    def dummy_lesson(self, name: str, weapon: str) -> None:
        weapon_name = WEAPONS[weapon].name
        lessons = [
            ("FOOTWORK", [
                f"You take the {weapon_name}. The first strike is ugly.",
                "The trainer taps the dirt beside your heel.",
                "Move once. Do not let the dummy decide your distance.",
            ], "arrow key: move"),
            ("COMMITMENT", [
                "The dummy is still, but the lesson is not.",
                "An attack spends stamina and exposes your posture.",
                "Strike once, then read what your body has left.",
            ], "a: attack"),
            ("SURVIVAL", [
                "The trainer swings the dummy's weighted arm at you.",
                "Guard absorbs pressure. Focus restores your read of the fight.",
                "Use one defensive action before the lesson ends.",
            ], "g: guard   f: focus"),
        ]
        for title, lines, footer in lessons:
            self.draw_lines(f"THE DUMMY LESSON — {title}", lines, footer)
            while True:
                key = self.win.getch()
                valid_move = title == "FOOTWORK" and key in (
                    curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT,
                    curses.KEY_RIGHT)
                valid_attack = title == "COMMITMENT" and key == ord("a")
                valid_defence = title == "SURVIVAL" and key in (ord("g"), ord("f"))
                if valid_move or valid_attack or valid_defence:
                    break
        if weapon in {"javelin", "bow"}:
            self.draw_lines("THE DUMMY LESSON — RANGE", [
                "Thrown weapons buy time, but every projectile is a decision.",
                "Aim through open lanes. Reload before the chamber is empty.",
                "Cover can turn a perfect shot into a wasted one.",
            ], "press enter to face your first living opponent")
            while self.win.getch() not in (10, 13, curses.KEY_ENTER):
                pass
        else:
            self.draw_lines("THE DUMMY LESSON — RANGE", [
                "Reach is geometry, not a promise.",
                "A spear controls space. A blade owns the cell beside you.",
                "There is no class screen: your weapon and learned skills evolve.",
            ], "press enter to face your first living opponent")
            while self.win.getch() not in (10, 13, curses.KEY_ENTER):
                pass

    def auction(self) -> None:
        self.draw_lines("THE AUCTION", [
            "The chain is not dramatic. It is paperwork.",
            "A merchant buys your debt, then sells the remainder",
            "to an arena house that needs bodies for the season.",
            "",
            "The cart reaches the slave chambers before dawn.",
        ], "press enter to continue")
        while self.win.getch() not in (10, 13, curses.KEY_ENTER):
            pass

    def choose_weapon(self) -> str | None:
        """Compatibility shim for callers from the earlier prototype."""
        return self.tutorial_weapon("the new arrival")

    def intro(self, name: str) -> None:
        """Compatibility shim for the earlier prototype opener."""
        self.draw_lines("FIRST BLOOD", [
            f"{name}, the first lesson is not glory.",
            "It is learning which mistake leaves you alive.",
            "",
            "The trainer opens the gate to the live sand.",
        ], "press enter to continue")
        while self.win.getch() not in (10, 13, curses.KEY_ENTER):
            pass

    def run(self) -> bool | None:
        self.win.keypad(True)
        has_career = bool(self.save.get("career_started"))
        lines = [
            "The arena remembers every wound.",
            "The gods remember every debt.",
            "Your name begins in the sand.",
            "",
            "n  begin a new career",
        ]
        if has_career:
            lines.append(f"c  continue as {self.save.get('fighter_name') or 'the unnamed'}")
        lines.append("q  leave the gate")
        self.draw_lines("G L A D I A T O R", lines, "choose an option")
        while True:
            key = self.win.getch()
            if key in (ord("q"), 27):
                return None
            if key == ord("c") and has_career:
                break
            if key == ord("n"):
                self.auction()
                name = self.read_name()
                profile = self.customize_profile(name)
                if profile is None:
                    return None
                self.chores(name, profile)
                weapon = self.tutorial_weapon(name)
                if weapon is None:
                    return None
                self.save["fighter_name"] = name
                self.save["weapon_key"] = weapon
                self.save["profile"] = profile
                self.save["career_started"] = True
                self.dummy_lesson(name, weapon)
                self.save["tutorial_complete"] = True
                break
        return TacticalScreen(self.stdscr, make_duel(
            self.save.get("fighter_name", "Mara"),
            self.save.get("weapon_key", "blade"),
            self.save.get("profile", {}),
        ), self.save.get("fighter_name", "Mara")).run()


def run(stdscr, save: dict) -> bool:
    curses.curs_set(0)
    stdscr.keypad(True)
    return OpeningScreen(stdscr, save).run()
