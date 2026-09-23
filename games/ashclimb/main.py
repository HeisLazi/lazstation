#!/usr/bin/env python3
"""Ashclimb -- a short roguelike deckbuilder.

A run is twelve floors and takes about fifteen minutes. You start with ten
cards, and every card you add makes the deck stronger and less reliable, which
is the whole game: what you refuse to pick up matters as much as what you take.

Enemies telegraph what they will do before you commit, so a turn is a real
decision rather than a guess.

All content is in content.py; the rules here never name a specific card.
"""
from __future__ import annotations

import random
import sys

import termstation_sdk as ts
from content import (BOSS, CARDS, ELITES, ENCOUNTERS, ENEMIES, FLOORS,
                     HAND_SIZE, INTRO, MAX_ENERGY, RELICS, START_HP,
                     STARTING_DECK)

# The combat screen is budgeted at 16 rows so the input prompt still
# fits inside a 20-row picture without forcing a page flip.
PAGE = 17
LOG_ROWS = 2


# ---------------------------------------------------------------- fighters

class Fighter:
    def __init__(self, name: str, hp: int) -> None:
        self.name = name
        self.max_hp = self.hp = hp
        self.block = 0
        self.strength = 0
        self.weak = 0
        self.vuln = 0

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def take(self, amount: int) -> int:
        """Apply damage through block. Returns health actually lost."""
        if self.vuln > 0:
            amount = int(amount * 1.5)
        absorbed = min(self.block, amount)
        self.block -= absorbed
        rest = amount - absorbed
        self.hp = max(0, self.hp - rest)
        return rest

    def outgoing(self, amount: int) -> int:
        amount += self.strength
        if self.weak > 0:
            amount = int(amount * 0.75)
        return max(0, amount)

    def tick_statuses(self) -> None:
        self.weak = max(0, self.weak - 1)
        self.vuln = max(0, self.vuln - 1)


class Enemy(Fighter):
    def __init__(self, name: str) -> None:
        data = ENEMIES[name]
        lo, hi = data["hp"]
        super().__init__(name, random.randint(lo, hi))
        self.moves = data["moves"]
        self.glyph = data["glyph"]
        self.tier = data["tier"]
        self.intent = random.choice(self.moves)

    def pick_intent(self) -> None:
        self.intent = random.choice(self.moves)

    def intent_text(self) -> str:
        kind, value, flavour = self.intent
        if kind == "attack":
            return f"attack {self.outgoing(value)}"
        return {"block": f"block {value}", "weak": "weaken you",
                "vuln": "expose you", "strength": f"+{value} strength"}[kind]


# ---------------------------------------------------------------- the run

class Run:
    def __init__(self, save: dict) -> None:
        self.save = save
        state = save.get("run") or {}
        self.deck: list[str] = list(state.get("deck") or STARTING_DECK)
        self.max_hp = int(state.get("max_hp", START_HP))
        self.hp = int(state.get("hp", self.max_hp))
        self.gold = int(state.get("gold", 0))
        self.floor = int(state.get("floor", 1))
        self.relics: list[str] = list(state.get("relics") or [])
        self.active = bool(state.get("active", False))

    def store(self) -> None:
        self.save["run"] = dict(deck=self.deck, max_hp=self.max_hp, hp=self.hp,
                                gold=self.gold, floor=self.floor,
                                relics=self.relics, active=self.active)
        ts.save(self.save)

    def clear_run(self) -> None:
        self.save["run"] = {}
        ts.save(self.save)

    def has(self, relic: str) -> bool:
        return relic in self.relics

    def add_relic(self, relic: str) -> None:
        self.relics.append(relic)
        if relic == "Coal Heart":
            self.max_hp += 12
            self.hp += 12


# ---------------------------------------------------------------- combat

class Combat:
    def __init__(self, run: Run, enemies: list[Enemy], title: str) -> None:
        self.run = run
        self.you = Fighter("You", run.max_hp)
        self.you.hp = run.hp
        self.enemies = enemies
        self.title = title
        self.draw_pile: list[str] = list(run.deck)
        random.shuffle(self.draw_pile)
        self.hand: list[str] = []
        self.discard: list[str] = []
        self.exhausted: list[str] = []
        self.energy = MAX_ENERGY
        self.log: list[str] = []
        self.turn = 0
        self.first_attack = True

        if run.has("Iron Ration"):
            self.you.hp = min(self.you.max_hp, self.you.hp + 3)
            self.say("Iron Ration: healed 3.")
        if run.has("Ballast Stone"):
            self.you.block = 5

    # --- helpers
    def say(self, text: str) -> None:
        self.log.append(text)
        self.log = self.log[-LOG_ROWS:]

    def living(self) -> list[Enemy]:
        return [e for e in self.enemies if e.alive]

    def draw(self, count: int) -> None:
        for _ in range(count):
            if not self.draw_pile:
                if not self.discard:
                    return
                self.draw_pile = self.discard
                self.discard = []
                random.shuffle(self.draw_pile)
                self.say("(reshuffled the discard pile)")
            self.hand.append(self.draw_pile.pop())

    # --- rendering
    def draw_screen(self) -> None:
        ts.tv_clear(page=PAGE)
        r = self.run
        relics = " ".join(x[0] for x in r.relics)
        head = (f"  Floor {r.floor}/{FLOORS}   ♥ {self.you.hp}/{self.you.max_hp}"
                f"   ⛁ {r.gold}   ⚡ {self.energy}/{MAX_ENERGY}"
                f"   draw {len(self.draw_pile)}  disc {len(self.discard)}")
        ts.tv_print(ts.color(head, "bright_cyan"))
        ts.tv_print(ts.rule("─"))

        for i, e in enumerate(self.living(), 1):
            tags = []
            if e.block:
                tags.append(f"blk {e.block}")
            if e.weak:
                tags.append(f"weak {e.weak}")
            if e.vuln:
                tags.append(f"vuln {e.vuln}")
            if e.strength:
                tags.append(f"str +{e.strength}")
            extra = ("  " + " ".join(tags)) if tags else ""
            ts.tv_print(f"  {ts.color(str(i), 'bright_cyan')} {e.name.ljust(15)}"
                        f"♥ {str(e.hp).rjust(3)}/{str(e.max_hp).ljust(4)}"
                        f"{ts.color('→ ' + e.intent_text(), 'bright_red')}{extra}")
        for _ in range(3 - len(self.living())):
            ts.tv_print()

        ts.tv_print(ts.rule("─"))
        you_tags = []
        if self.you.block:
            you_tags.append(ts.color(f"block {self.you.block}", "bright_cyan"))
        if self.you.strength:
            you_tags.append(f"str +{self.you.strength}")
        if self.you.weak:
            you_tags.append(f"weak {self.you.weak}")
        if self.you.vuln:
            you_tags.append(f"vuln {self.you.vuln}")
        ts.tv_print(f"  You   ♥ {self.you.hp}/{self.you.max_hp}   "
                    + "   ".join(you_tags))
        for line in self.log[-LOG_ROWS:]:
            ts.tv_print(f"  {line}")
        for _ in range(LOG_ROWS - len(self.log[-LOG_ROWS:])):
            ts.tv_print()
        ts.tv_print(ts.rule("─"))

        for i, name in enumerate(self.hand, 1):
            card = CARDS[name]
            afford = "bright_cyan" if card["cost"] <= self.energy else "grey"
            ts.tv_print(f"  {ts.color(str(i), afford)}  "
                        f"{ts.color(name.ljust(12), afford)}"
                        f"{card['cost']}⚡  {ts.color(card['text'], 'grey')}")
        for _ in range(HAND_SIZE - len(self.hand)):
            ts.tv_print()
        ts.tv_print(ts.color("  0  end turn", "bright_yellow"))

    # --- playing a card
    def resolve(self, name: str, target: Enemy | None) -> None:
        card = CARDS[name]
        exhaust = False
        for step in card["effect"]:
            op = step[0]
            n = step[1] if len(step) > 1 else 0
            if op == "damage" and target:
                dealt = self.you.outgoing(n)
                if self.first_attack and self.run.has("Cracked Whetstone"):
                    dealt += 3
                    self.first_attack = False
                    self.say("Cracked Whetstone adds 3.")
                lost = target.take(dealt)
                self.say(f"{name}: {target.name} takes {lost}.")
                if not target.alive:
                    self.say(f"{target.name} falls.")
            elif op == "damage_all":
                for e in self.living():
                    lost = e.take(self.you.outgoing(n))
                    self.say(f"{name}: {e.name} takes {lost}.")
            elif op == "block":
                self.you.block += n
                self.say(f"{name}: +{n} block.")
            elif op == "draw":
                self.draw(n)
            elif op == "energy":
                self.energy += n
            elif op == "weak" and target:
                target.weak += n
                self.say(f"{target.name} is weakened.")
            elif op == "vuln" and target:
                target.vuln += n
                self.say(f"{target.name} is exposed.")
            elif op == "strength":
                self.you.strength += n
                self.say(f"+{n} strength.")
            elif op == "heal":
                self.you.hp = min(self.you.max_hp, self.you.hp + n)
                self.say(f"healed {n}.")
            elif op == "exhaust_self":
                exhaust = True
        if exhaust:
            self.exhausted.append(name)
        else:
            self.discard.append(name)

    def choose_target(self) -> Enemy | None:
        alive = self.living()
        if len(alive) <= 1:
            return alive[0] if alive else None
        pick = ts.ask_int("which enemy", 1, len(alive))
        return alive[pick - 1]

    # --- turns
    def player_turn(self) -> str:
        self.turn += 1
        self.energy = MAX_ENERGY + (1 if self.turn == 1 and
                                    self.run.has("Tinderbox") else 0)
        self.you.block = 0 if self.turn > 1 else self.you.block
        self.draw(HAND_SIZE + (1 if self.run.has("Ash Lens") else 0))

        while True:
            if not self.living():
                return "won"
            self.draw_screen()
            pick = ts.ask_int("play a card (0 ends your turn)", 0, len(self.hand))
            if pick == 0:
                break
            name = self.hand[pick - 1]
            card = CARDS[name]
            if card["cost"] > self.energy:
                self.say(f"{name} costs {card['cost']}, you have {self.energy}.")
                continue
            target = self.choose_target() if card["target"] == "one" else None
            if card["target"] == "one" and target is None:
                return "won"
            self.energy -= card["cost"]
            self.hand.pop(pick - 1)
            self.resolve(name, target)

        self.discard.extend(self.hand)
        self.hand = []
        return "ok"

    def enemy_turn(self) -> str:
        for e in self.living():
            kind, value, flavour = e.intent
            if kind == "attack":
                lost = self.you.take(e.outgoing(value))
                self.say(f"{e.name} {flavour}: you take {lost}.")
            elif kind == "block":
                e.block += value
                self.say(f"{e.name} {flavour}.")
            elif kind == "weak":
                self.you.weak += value
                self.say(f"{e.name} {flavour}.")
            elif kind == "vuln":
                self.you.vuln += value
                self.say(f"{e.name} {flavour}.")
            elif kind == "strength":
                e.strength += value
                self.say(f"{e.name} {flavour}.")
            e.tick_statuses()
            e.pick_intent()
            if not self.you.alive:
                return "lost"
        self.you.tick_statuses()
        return "ok"

    def fight(self) -> str:
        names = " and ".join(e.name for e in self.enemies)
        verb = "block" if len(self.enemies) > 1 else "blocks"
        self.say(f"{names} {verb} the stair.")
        while True:
            if self.player_turn() == "won" or not self.living():
                self.run.hp = self.you.hp
                return "won"
            if self.enemy_turn() == "lost":
                return "lost"
            self.run.hp = self.you.hp
            if not self.you.alive:
                return "lost"


# ---------------------------------------------------------------- the game

def header(run: Run, title: str) -> None:
    ts.tv_clear(page=PAGE)
    ts.tv_print(ts.color(
        f"  {title}".ljust(40)
        + f"Floor {run.floor}/{FLOORS}   ♥ {run.hp}/{run.max_hp}   ⛁ {run.gold}",
        "bright_cyan"))
    ts.tv_print(ts.rule("─"))


def card_line(name: str) -> str:
    c = CARDS[name]
    return f"{name.ljust(12)} {c['cost']}⚡  {c['text']}"


def pick_reward(run: Run) -> None:
    pool = [n for n, c in CARDS.items() if c["rarity"] != "basic"]
    weights = {"common": 6, "uncommon": 3, "rare": 1}
    offer: list[str] = []
    while len(offer) < 3 and pool:
        name = random.choices(pool, [weights[CARDS[n]["rarity"]] for n in pool])[0]
        pool.remove(name)
        offer.append(name)
    header(run, "Spoils")
    ts.tv_print()
    ts.tv_print("  Take one card — or take none, and keep the deck lean.")
    ts.tv_print()
    pick = ts.menu("Add to your deck", [card_line(n) for n in offer],
                   back="Skip (take nothing)")
    if pick >= 0:
        run.deck.append(offer[pick])
        ts.tv_print(ts.color(f"  {offer[pick]} joins the deck "
                             f"({len(run.deck)} cards).", "bright_green"))
        ts.tv_pause()


def rest_site(run: Run) -> None:
    header(run, "A guttering fire")
    ts.tv_print()
    ts.tv_print("  You can sit a while, or work on the deck.")
    ts.tv_print()
    heal = max(6, run.max_hp // 3)
    pick = ts.menu("At the fire",
                   [f"Rest — heal {heal}",
                    "Burn a card — remove one from your deck for good"],
                   back=None)
    if pick == 0:
        run.hp = min(run.max_hp, run.hp + heal)
        ts.tv_print(ts.color(f"  You heal {heal}.", "bright_green"))
        ts.tv_pause()
    else:
        counts: dict[str, int] = {}
        for n in run.deck:
            counts[n] = counts.get(n, 0) + 1
        names = sorted(counts)
        choice = ts.menu("Burn which card?",
                         [f"{n}  x{counts[n]}" for n in names], back="Change your mind")
        if choice >= 0:
            run.deck.remove(names[choice])
            ts.tv_print(ts.color(f"  {names[choice]} burns away "
                                 f"({len(run.deck)} cards left).", "bright_yellow"))
            ts.tv_pause()


def treasure(run: Run) -> None:
    header(run, "A cold alcove")
    ts.tv_print()
    unowned = [r for r in RELICS if r not in run.relics]
    if not unowned:
        run.gold += 40
        ts.tv_print("  Nothing left but coin. You take 40.")
        ts.tv_pause()
        return
    relic = random.choice(unowned)
    run.add_relic(relic)
    ts.tv_print(ts.box([f"  You find the {relic}.", "", f"  {RELICS[relic]}"],
                       fg="yellow"))
    ts.tv_pause()


def make_encounter(floor: int) -> list[Enemy]:
    valid = [groups for need, groups in ENCOUNTERS if need <= floor]
    groups = random.choice(valid or [ENCOUNTERS[0][1]])
    out: list[Enemy] = []
    for name, count in groups:
        out.extend(Enemy(name) for _ in range(count))
    return out[:3]


def run_floor(run: Run) -> str:
    """Returns 'ok', 'dead' or 'won'."""
    if run.floor == FLOORS:
        header(run, "The top of the stair")
        ts.tv_print()
        ts.tv_print(ts.box(["  The Cinder King is waiting, and does not get up.",
                            "", "  This is the last fight."]))
        ts.tv_print()
        ts.tv_pause()
        combat = Combat(run, [Enemy(BOSS)], BOSS)
        return "won" if combat.fight() == "won" else "dead"

    options = ["Fight your way up"]
    if run.floor % 4 == 0:
        options.append("Take the hard stair (elite — better spoils)")
    options.append("Look for a fire" if run.floor % 3 == 0 else "Search the floor")

    header(run, f"Floor {run.floor}")
    ts.tv_print()
    ts.tv_print(f"  Deck: {len(run.deck)} cards"
                + (f"    Relics: {', '.join(run.relics)}" if run.relics else ""))
    ts.tv_print()
    pick = ts.menu("Which way?", options, back=None)
    choice = options[pick]

    if choice.startswith("Take the hard"):
        combat = Combat(run, [Enemy(random.choice(ELITES))], "Elite")
        if combat.fight() == "lost":
            return "dead"
        run.gold += 60
        pick_reward(run)
        pick_reward(run)
    elif choice.startswith("Fight"):
        combat = Combat(run, make_encounter(run.floor), f"Floor {run.floor}")
        if combat.fight() == "lost":
            return "dead"
        run.gold += 20 + run.floor * 3
        pick_reward(run)
    elif choice == "Look for a fire":
        rest_site(run)
    else:
        treasure(run)

    run.floor += 1
    run.store()
    return "ok"


def main() -> int:
    ts.tv("Ashclimb")
    save = ts.load({"run": {}, "best_floor": 0, "runs": 0, "wins": 0, "version": 1})
    run = Run(save)

    if not run.active:
        ts.tv_clear(page=PAGE)
        ts.tv_print(ts.title("A S H C L I M B"))
        ts.tv_print()
        ts.tv_print(ts.box(["  " + line for line in INTRO] + [
            "",
            "  Type the number beside a card to play it, 0 to end your turn.",
            "  Enemies show what they will do before you commit.",
        ]))
        ts.tv_print()
        ts.tv_pause()
        run.active = True
        save["runs"] = save.get("runs", 0) + 1
        run.store()

    outcome = "quit"
    while True:
        result = run_floor(run)
        if result == "dead":
            outcome = "dead"
            break
        if result == "won":
            outcome = "won"
            break

    save["best_floor"] = max(save.get("best_floor", 0), run.floor)
    if outcome == "won":
        save["wins"] = save.get("wins", 0) + 1
        ts.unlock("cinder-king", "Kingslayer", "Cleared the spire")
        if len(run.deck) <= 12:
            ts.unlock("lean-deck", "Nothing Spare",
                      f"Cleared it with only {len(run.deck)} cards")
    if run.floor >= 6:
        ts.unlock("halfway", "Halfway Up", "Reached floor 6")
    run.clear_run()

    ts.tv_clear(page=16)
    ts.tv_print(ts.title("A S H C L I M B"))
    ts.tv_print()
    if outcome == "won":
        ts.tv_print(ts.box([
            "  The Cinder King goes out like a spent coal.",
            "  You walk down twelve floors of quiet tower.",
            "", f"  Cleared with {run.hp}/{run.max_hp} health and "
            f"{len(run.deck)} cards.",
        ], fg="yellow"))
    else:
        ts.tv_print(ts.box([
            f"  You fall on floor {run.floor}.",
            "", f"  Deck of {len(run.deck)} cards, "
            f"{len(run.relics)} relics, {run.gold} gold.",
        ], fg="red"))
    ts.tv_print()
    ts.tv_print(f"  best floor {save['best_floor']}    runs {save['runs']}"
                f"    wins {save['wins']}")
    ts.tv_print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
