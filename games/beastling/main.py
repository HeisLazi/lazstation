#!/usr/bin/env python3
"""Beastling -- catch, raise and battle creatures in the Hollow Vale.

Line-based: everything is printed into the TV picture and read with prompts,
which keeps the systems (types, growth, evolution, catching) the interesting
part rather than the rendering.

All content lives in beasts.py. The rules live here.
"""
from __future__ import annotations

import random
import sys

import termstation_sdk as ts
from beasts import (ABILITY_DESC, CHAMPIONS, CHART, MOVES, ROUTES, SPECIES, STARTERS,
                    TYPE_ABILITY)

PAGE = 19          # rows a battle screen uses, for vertical centring
PARTY_MAX = 6
BAR_W = 16


# ---------------------------------------------------------------- creature

class Beast:
    """One creature. Stats grow with level; nothing is stored that can be
    derived, so a save is small and old saves keep working."""

    def __init__(self, slug: str, level: int, nickname: str = "") -> None:
        self.slug = slug
        self.level = level
        self.nickname = nickname
        self.xp = 0
        self.moves = self._known_moves()
        self.hp = self.max_hp
        # --- transient combat state: never saved (see to_dict/from_dict),
        # always reset at the top of `Game.battle` and again on send-out,
        # so nothing leaks between encounters or between party members.
        self.status: str | None = None       # None | "burn" | "paralyze"
        self.atk_stage = 0
        self.def_stage = 0
        self.spd_stage = 0
        self.vengeful_used = False           # Vengeful triggers once per battle

    def reset_combat_state(self) -> None:
        self.status = None
        self.atk_stage = self.def_stage = self.spd_stage = 0
        self.vengeful_used = False

    @staticmethod
    def _stage_mult(stage: int) -> float:
        # The standard formula: +1 = 1.5x, +2 = 2x, +3 = 2.5x (capped);
        # -1 = 0.67x, -2 = 0.5x, -3 = 0.4x. Capped at +-3 rather than the
        # usual +-6 -- this game's fights are short enough that +-3 already
        # swings an exchange hard.
        stage = max(-3, min(3, stage))
        return (2 + stage) / 2 if stage >= 0 else 2 / (2 - stage)

    @property
    def eff_atk(self) -> int:
        return max(1, int(self.atk * self._stage_mult(self.atk_stage)))

    @property
    def eff_def(self) -> int:
        return max(1, int(self.dfn * self._stage_mult(self.def_stage)))

    @property
    def eff_spd(self) -> float:
        mult = self._stage_mult(self.spd_stage)
        return self.spd * mult * (0.5 if self.status == "paralyze" else 1.0)

    # --- identity
    @property
    def base(self) -> dict:
        return SPECIES[self.slug]

    @property
    def name(self) -> str:
        return self.nickname or self.base["name"]

    @property
    def type(self) -> str:
        return self.base["type"]

    @property
    def ability(self) -> str:
        return TYPE_ABILITY[self.type]

    # --- stats: flat growth, so a level-20 beast is roughly twice a level-5 one
    def _stat(self, key: str, scale: float) -> int:
        return int(self.base[key] + self.level * scale)

    @property
    def max_hp(self) -> int:
        return self._stat("hp", 2.2)

    @property
    def atk(self) -> int:
        return self._stat("atk", 1.1)

    @property
    def dfn(self) -> int:
        return self._stat("dfn", 1.0)

    @property
    def spd(self) -> int:
        return self._stat("spd", 0.9)

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def _known_moves(self) -> list[str]:
        """The four most recent moves learned by this level."""
        learned = [m for lv, m in self.base["learn"] if lv <= self.level]
        return learned[-4:] or ["Tackle"]

    def xp_needed(self) -> int:
        return 12 + self.level * self.level // 2

    # --- progression
    def gain_xp(self, amount: int) -> list[str]:
        """Returns the lines to show the player."""
        notes: list[str] = []
        self.xp += amount
        notes.append(f"{self.name} gained {amount} XP.")
        while self.xp >= self.xp_needed() and self.level < 60:
            self.xp -= self.xp_needed()
            self.level += 1
            before = set(self.moves)
            self.moves = self._known_moves()
            self.hp = self.max_hp
            notes.append(f"{self.name} grew to level {self.level}!")
            for move in set(self.moves) - before:
                notes.append(f"  it learned {move}.")
            evo = self.base.get("evolve")
            if evo and self.level >= evo[0]:
                old = self.name
                self.slug = evo[1]
                if not self.nickname:
                    notes.append(f"  {old} became {self.base['name']}!")
                else:
                    notes.append(f"  {old} evolved into {self.base['name']}!")
                self.moves = self._known_moves()
                self.hp = self.max_hp
        return notes

    # --- persistence
    def to_dict(self) -> dict:
        return {"slug": self.slug, "level": self.level, "xp": self.xp,
                "hp": self.hp, "nickname": self.nickname}

    @classmethod
    def from_dict(cls, data: dict) -> "Beast":
        b = cls(data.get("slug", "sproutling"), int(data.get("level", 5)),
                data.get("nickname", ""))
        b.xp = int(data.get("xp", 0))
        b.hp = max(0, min(int(data.get("hp", b.max_hp)), b.max_hp))
        return b


# ---------------------------------------------------------------- combat maths

def effectiveness(move_type: str, defender_type: str) -> float:
    return CHART.get(move_type, {}).get(defender_type, 1.0)


def effect_word(mult: float) -> str:
    if mult >= 2.0:
        return "It's super effective!"
    if mult <= 0.5:
        return "It barely scratches."
    return ""


CRIT_CHANCE = 1 / 16   # Gen-1-flavoured: rare enough to feel earned, not spammy
CRIT_MULT = 1.5


def damage(attacker: Beast, defender: Beast, move: str) -> tuple[int, float, bool, bool]:
    """Returns (damage, type multiplier, hit?, crit?)."""
    spec = MOVES[move]
    m_type, power, accuracy = spec["type"], spec["power"], spec["accuracy"]
    if random.randint(1, 100) > accuracy:
        return 0, 1.0, False, False
    mult = effectiveness(m_type, defender.type)
    if m_type == attacker.type:
        mult *= 1.25                      # it suits them
    crit = random.random() < CRIT_CHANCE
    # The divisor is tuned against these stat sizes: a neutral hit between
    # equal levels should take about five exchanges, so a super-effective
    # choice (two or three) is a real decision rather than a rounding error.
    base = ((2 * attacker.level / 5 + 2) * power * attacker.eff_atk / max(1, defender.eff_def)) / 26
    dealt = (base + 2) * mult * (CRIT_MULT if crit else 1.0) * random.uniform(0.85, 1.0)
    if defender.ability == "Thick Hide" and mult >= 2.0:
        dealt *= 0.75
    return max(1, int(dealt)), mult, True, crit


STAGE_NAME = {"atk": "Atk", "def": "Def", "spd": "Spd"}


def apply_move_effect(attacker: Beast, defender: Beast, move: str) -> list[str]:
    """Rolls and applies a move's secondary effect, if it has one and the
    roll succeeds. Returns log lines, empty if nothing happened."""
    effect = MOVES[move]["effect"]
    if not effect or random.random() >= effect[-1]:
        return []
    if effect[0] == "status":
        _, status, _ = effect
        if defender.status is not None or not defender.alive:
            return []
        if status == "burn" and defender.ability == "Riptide":
            return [f"  {defender.name}'s Riptide keeps it from burning!"]
        defender.status = status
        verb = "is burned!" if status == "burn" else "is paralyzed!"
        return [f"  {defender.name} {verb}"]
    # ("stage", stat, delta, target, chance)
    _, stat, delta, target, _ = effect
    who = attacker if target == "self" else defender
    if who is defender and delta < 0 and who.ability == "Unshaken":
        return [f"  {who.name}'s Unshaken holds its stats steady!"]
    field = f"{stat}_stage"
    before = getattr(who, field)
    after = max(-3, min(3, before + delta))
    setattr(who, field, after)
    if after == before:
        return []
    word = "rose" if after > before else "fell"
    return [f"  {who.name}'s {STAGE_NAME[stat]} {word}!"]


TINDER_CHANCE = 0.12
STATIC_CHARGE_CHANCE = 0.15


def apply_ability_on_hit(attacker: Beast, defender: Beast) -> list[str]:
    """Hooks that fire after ANY successful, damaging hit -- independent of
    the move's own `effect`, since abilities are a property of the beast,
    not the move. Tinder (attacker's) and Static Charge (defender's) can
    both fire off the same hit; order is attacker-first, matching who
    acted."""
    lines: list[str] = []
    if (attacker.ability == "Tinder" and defender.status is None and defender.alive
            and defender.ability != "Riptide" and random.random() < TINDER_CHANCE):
        defender.status = "burn"
        lines.append(f"  {attacker.name}'s Tinder catches {defender.name} alight!")
    if (defender.ability == "Static Charge" and defender.alive and attacker.status is None
            and random.random() < STATIC_CHARGE_CHANCE):
        attacker.status = "paralyze"
        lines.append(f"  {defender.name}'s Static Charge locks up {attacker.name}!")
    return lines


def check_vengeful(beast: Beast) -> list[str]:
    """Once per battle, the instant a Vengeful beast drops below a quarter
    HP, its Atk rises -- checked right after any damage that could have
    crossed the threshold, not on a timer."""
    if (beast.ability == "Vengeful" and not beast.vengeful_used and beast.alive
            and beast.hp <= beast.max_hp * 0.25):
        beast.vengeful_used = True
        beast.atk_stage = max(-3, min(3, beast.atk_stage + 1))
        return [f"  {beast.name}'s Vengeful flares -- its Atk rose!"]
    return []


def resolve_status_upkeep(beast: Beast) -> list[str]:
    """End-of-turn status damage (burn only -- paralysis is checked at
    action time instead, via `may_act`)."""
    if beast.status == "burn" and beast.alive:
        dot = max(1, beast.max_hp // 16)
        beast.hp = max(0, beast.hp - dot)
        line = f"  {beast.name} is hurt by its burn. ({dot} HP)"
        if not beast.alive:
            line += f" {beast.name} is out of the fight!"
        lines = [line]
        if beast.alive:
            lines.extend(check_vengeful(beast))  # burn can cross the threshold too
        return lines
    return []


def may_act(beast: Beast) -> bool:
    """Paralysis has a real chance to no-sell a turn entirely."""
    if beast.status == "paralyze" and random.random() < 0.25:
        return False
    return True


def choose_ai_move(attacker: Beast, defender: Beast) -> str:
    """Weighted toward whatever hits hardest into the current matchup --
    not perfect play (there's still real randomness), but no longer a
    trainer who might Tackle into something 4x resistant for no reason."""
    weights = []
    for move in attacker.moves:
        spec = MOVES[move]
        mult = effectiveness(spec["type"], defender.type)
        weights.append(max(0.15, mult) ** 2 * spec["power"])
    return random.choices(attacker.moves, weights=weights, k=1)[0]


def catch_chance(beast: Beast, lure_bonus: float = 1.0) -> float:
    """Weaker and lower-level things come quietly."""
    hp_ratio = beast.hp / beast.max_hp
    base = 0.62 - 0.30 * hp_ratio - min(0.28, beast.level * 0.010)
    return max(0.04, min(0.92, base * lure_bonus))


# ---------------------------------------------------------------- presentation

def bar(value: int, maximum: int, width: int = BAR_W) -> str:
    value = max(0, value)
    filled = int(width * value / maximum) if maximum else 0
    colour = "bright_green" if value > maximum * 0.5 else (
        "bright_yellow" if value > maximum * 0.2 else "bright_red")
    return (ts.color("█" * filled, colour) + ts.color("░" * (width - filled), "grey"))


STATUS_TAG = {"burn": ("BRN", "bright_red"), "paralyze": ("PAR", "bright_yellow")}


def beast_line(b: Beast, wild: bool = False) -> list[str]:
    tag = "Wild " if wild else ""
    head = f"  {tag}{b.name}"
    lv = f"Lv {b.level}"
    stages = "".join(f" {STAGE_NAME[s].upper()}{v:+d}" for s, v in
                      (("atk", b.atk_stage), ("def", b.def_stage), ("spd", b.spd_stage)) if v)
    status = ""
    if b.status:
        word, colour = STATUS_TAG[b.status]
        status = "  " + ts.color(word, colour)
    return [
        f"{head}{lv.rjust(max(1, 44 - len(head)))}  {ts.color(b.type, 'cyan')}"
        f" {ts.color('· ' + b.ability, 'grey')}",
        f"   HP [{bar(b.hp, b.max_hp)}] {b.hp}/{b.max_hp}{status}{ts.color(stages, 'grey')}",
    ]


def show_log(lines: list[str], keep: int = 4) -> None:
    for line in lines[-keep:]:
        ts.tv_print(f"  {line}")
    for _ in range(keep - len(lines[-keep:])):
        ts.tv_print()


# ---------------------------------------------------------------- the game

class Game:
    def __init__(self, save: dict) -> None:
        self.save = save
        self.party: list[Beast] = [Beast.from_dict(d) for d in save.get("party", [])]
        self.box: list[Beast] = [Beast.from_dict(d) for d in save.get("box", [])]
        self.badges = int(save.get("badges", 0))
        self.seen = set(save.get("seen", []))
        self.caught = set(save.get("caught", []))
        self.lures = int(save.get("lures", 8))
        self.money = int(save.get("money", 300))

    # --- persistence
    def store(self) -> None:
        self.save.update(
            party=[b.to_dict() for b in self.party],
            box=[b.to_dict() for b in self.box],
            badges=self.badges, seen=sorted(self.seen), caught=sorted(self.caught),
            lures=self.lures, money=self.money)
        self.save["_summary"] = (f"{self.badges} badges · {len(self.caught)} caught")
        ts.save(self.save)

    # --- helpers
    def healthy(self) -> list[Beast]:
        return [b for b in self.party if b.alive]

    def lead(self) -> Beast | None:
        healthy = self.healthy()
        return healthy[0] if healthy else None

    def heal_all(self) -> None:
        for b in self.party:
            b.hp = b.max_hp

    def header(self, title: str) -> None:
        ts.tv_clear(page=PAGE)
        badge = "◆" * self.badges + "◇" * (len(CHAMPIONS) - self.badges)
        left = f"  {title}"
        right = f"{badge}   ⛁ {self.money}   lures {self.lures}  "
        width = ts.size()[0]
        ts.tv_print(ts.color(left + right.rjust(max(1, width - len(left) - 1)),
                             "bright_cyan"))
        ts.tv_print(ts.rule("─"))

    # ------------------------------------------------------------- battle
    def battle(self, foe: Beast, wild: bool, title: str,
               trainer: str = "") -> str:
        """Returns 'won', 'lost', 'caught' or 'fled'."""
        self.seen.add(foe.slug)
        # A clean slate every encounter: status and stat stages never
        # persist between battles (only within one), regardless of swap
        # history -- simplest correct rule, see the comment on
        # Beast.reset_combat_state.
        foe.reset_combat_state()
        for b in self.party:
            b.reset_combat_state()
        log: list[str] = []
        if wild:
            log.append(f"A wild {foe.name} appears!")
        else:
            log.append(f"{trainer} sends out {foe.name}!")

        while True:
            me = self.lead()
            if me is None:
                return "lost"

            self.header(title)
            for line in beast_line(foe, wild=wild):
                ts.tv_print(line)
            ts.tv_print()
            for line in beast_line(me):
                ts.tv_print(line)
            ts.tv_print(ts.rule("─"))
            show_log(log)
            ts.tv_print(ts.rule("─"))

            options = []
            for i, move in enumerate(me.moves, 1):
                spec = MOVES[move]
                quick = ts.color(" quick", "bright_yellow") if spec["priority"] > 0 else ""
                ts.tv_print(f"   {ts.color(str(i), 'bright_cyan')}  "
                            f"{move.ljust(13)} {spec['type'].ljust(6)} "
                            f"pow {spec['power']:>2}  acc {spec['accuracy']}{quick}")
                options.append(str(i))
            extra = len(me.moves)
            tail = f"   {ts.color(str(extra + 1), 'bright_cyan')}  lure"
            if not wild:
                tail = f"   {ts.color(str(extra + 1), 'grey')}  (no lures in a duel)"
            tail += f"    {ts.color(str(extra + 2), 'bright_cyan')}  swap"
            tail += f"    {ts.color(str(extra + 3), 'bright_cyan')}  run"
            ts.tv_print(tail)
            choice = ts.ask_int("your move", 1, extra + 3)

            # ---- player's turn
            player_action = None
            if choice <= extra:
                player_action = me.moves[choice - 1]
            elif choice == extra + 1:
                if not wild:
                    log.append("You can't lure another trainer's beast.")
                    continue
                if self.lures <= 0:
                    log.append("You are out of lures.")
                    continue
                self.lures -= 1
                chance = catch_chance(foe)
                log.append(f"You set a lure... ({int(chance * 100)}% chance)")
                if random.random() < chance:
                    self.capture(foe)
                    log.append(f"{foe.name} was caught!")
                    self.header(title)
                    ts.tv_print()
                    ts.tv_print(ts.box([f"  {foe.name} (Lv {foe.level}) joins you.",
                                        "", f"  {SPECIES[foe.slug]['flavour']}"]))
                    ts.tv_print()
                    ts.tv_pause()
                    return "caught"
                log.append("It shook free!")
            elif choice == extra + 2:
                # A voluntary swap now costs the turn (the incoming beast's
                # own player_action stays None, so the "you" entry below is
                # skipped and only the foe acts) -- a forced swap, after
                # your active beast faints, is still free: the loop just
                # restarts with `me = self.lead()` picking the next one up
                # before any of this menu code runs again.
                if self.swap_menu():
                    log.append(f"You send out {self.lead().name}!")
                else:
                    continue
            else:
                if wild:
                    if random.random() < 0.7:
                        return "fled"
                    log.append("You couldn't get away!")
                else:
                    log.append("You can't run from a duel.")
                    continue

            # ---- resolve the exchange
            # `player_action` is None on a swap or a failed lure -- both
            # consume the whole turn, so only the foe's entry is included
            # and the fix-up below naturally handles what used to be a
            # crash (MOVES[None]) on a failed lure in the old code.
            me = self.lead()
            foe_move = choose_ai_move(foe, me)
            order = []
            if player_action is not None:
                order.append(("you", me, foe, player_action))
            order.append(("foe", foe, me, foe_move))
            # Priority first, then effective speed (which already folds in
            # stat stages and a paralysis penalty) -- a stable sort keeps
            # "you" first on an exact tie, matching the old tie-break.
            order.sort(key=lambda e: (-MOVES[e[3]]["priority"], -e[1].eff_spd))

            for who, attacker, defender, move in order:
                if not attacker.alive or not defender.alive:
                    continue
                if not may_act(attacker):
                    log.append(f"{attacker.name} is fully paralyzed! It can't move!")
                    continue
                dealt, mult, hit, crit = damage(attacker, defender, move)
                if not hit:
                    log.append(f"{attacker.name}'s {move} missed.")
                    continue
                defender.hp = max(0, defender.hp - dealt)
                note = effect_word(mult)
                if crit:
                    note = ("A critical hit! " + note).strip()
                log.append(f"{attacker.name} used {move}. {note}".strip())
                log.append(f"  {defender.name} lost {dealt} HP.")
                log.extend(apply_ability_on_hit(attacker, defender))
                log.extend(check_vengeful(defender))
                if not defender.alive:
                    log.append(f"{defender.name} is out of the fight!")
                    break
                log.extend(apply_move_effect(attacker, defender, move))

            for b in (foe, me):
                if b.alive:
                    log.extend(resolve_status_upkeep(b))

            if not foe.alive:
                gained = max(4, int(foe.level * 3.2))
                self.money += 8 + foe.level * 2
                for note in me.gain_xp(gained):
                    log.append(note)
                self.header(title)
                ts.tv_print()
                show_log(log, keep=10)
                ts.tv_print()
                ts.tv_pause()
                return "won"

            if not self.healthy():
                return "lost"

    def capture(self, foe: Beast) -> None:
        self.caught.add(foe.slug)
        ts.unlock("first-catch", "Something Followed You Home",
                  "Caught your first beast")
        if len(self.caught) >= len(SPECIES) // 2:
            ts.unlock("half-journal", "Half the Journal",
                      "Caught half of everything in the Vale")
        foe.hp = foe.max_hp
        if len(self.party) < PARTY_MAX:
            self.party.append(foe)
        else:
            self.box.append(foe)

    def swap_menu(self) -> bool:
        options = [f"{b.name}  Lv {b.level}  {b.hp}/{b.max_hp} HP"
                   + ("  (down)" if not b.alive else "")
                   for b in self.party]
        if len(options) < 2:
            return False
        pick = ts.menu("Send out which beast?", options, back="Cancel")
        if pick == -1 or pick == 0:
            # pick == 0 is already the active lead -- selecting it is a
            # no-op, not a real swap, and must not cost a turn now that
            # voluntary swaps do (see battle()).
            return False
        chosen = self.party[pick]
        if not chosen.alive:
            return False
        self.party.remove(chosen)
        self.party.insert(0, chosen)
        return True

    # ------------------------------------------------------------- world
    def explore(self, route: dict) -> None:
        steps = 0
        while True:
            self.header(route["name"])
            ts.tv_print()
            ts.tv_print(f"  {ts.color(route['blurb'], 'grey')}")
            ts.tv_print()
            ts.tv_print(f"  You are walking through {route['tall']}.")
            ts.tv_print(f"  Steps taken: {steps}")
            ts.tv_print()
            lead = self.lead()
            if lead:
                ts.tv_print(f"  Leading: {lead.name} Lv {lead.level} "
                            f"({lead.hp}/{lead.max_hp} HP)")
            ts.tv_print()
            pick = ts.menu("What do you do?",
                           ["Walk on (look for beasts)", "Check your team"],
                           back="Head back to camp")
            if pick == -1:
                return
            if pick == 1:
                self.team_screen()
                continue

            steps += 1
            if random.random() < 0.72:
                lo, hi = route["levels"]
                slug = random.choice(route["wild"])
                foe = Beast(slug, random.randint(lo, hi))
                result = self.battle(foe, wild=True, title=route["name"])
                if result == "lost":
                    self.blackout()
                    return
            else:
                self.header(route["name"])
                ts.tv_print()
                ts.tv_print("  The grass is still. Nothing about.")
                ts.tv_print()
                ts.tv_pause()
            self.store()

    def challenge(self, champ: dict) -> None:
        self.header(champ["name"])
        ts.tv_print()
        ts.tv_print(ts.box([
            f"  {champ['name']}  —  {champ['type']}",
            "",
            f"  {champ['blurb']}",
            "",
            f"  Team of {len(champ['team'])}. Beat them all without losing yours.",
        ]))
        ts.tv_print()
        if not ts.confirm("  Challenge them?", default=True):
            return

        for slug, level in champ["team"]:
            foe = Beast(slug, level)
            result = self.battle(foe, wild=False, title=champ["name"],
                                 trainer=champ["name"])
            if result in ("lost",):
                self.blackout()
                return
            if result == "fled":
                return

        self.badges += 1
        ts.unlock("first-badge", "First Badge", "Beat a champion of the roads")
        if self.badges >= len(CHAMPIONS):
            ts.unlock("all-badges", "Keeper of the Roads",
                      "Beat every champion in the Hollow Vale")
        self.money += 200 + self.badges * 100
        self.lures += 5
        self.heal_all()
        self.header(champ["name"])
        ts.tv_print()
        ts.tv_print(ts.box([
            f"  You beat {champ['name']}.",
            "",
            f"  {champ['win']}",
            "",
            f"  Badges: {self.badges}/{len(CHAMPIONS)}   +5 lures, and a purse.",
        ], fg="yellow"))
        ts.tv_print()
        ts.tv_pause()
        self.store()

    def blackout(self) -> None:
        self.header("Camp")
        ts.tv_print()
        ts.tv_print(ts.color("  Your last beast goes down.", "bright_red"))
        ts.tv_print()
        ts.tv_print("  Someone walks you back to camp. Your team is patched up,")
        ts.tv_print(f"  but it costs you {min(self.money, 100)} coins.")
        self.money = max(0, self.money - 100)
        self.heal_all()
        ts.tv_print()
        ts.tv_pause()
        self.store()

    # ------------------------------------------------------------- menus
    def team_screen(self) -> None:
        while True:
            self.header("Your team")
            ts.tv_print()
            if not self.party:
                ts.tv_print("  You have no beasts.")
            for i, b in enumerate(self.party, 1):
                state = "" if b.alive else ts.color("  (down)", "bright_red")
                ts.tv_print(f"  {i}. {b.name.ljust(13)} Lv {str(b.level).rjust(2)}  "
                            f"{b.type.ljust(6)} [{bar(b.hp, b.max_hp, 12)}] "
                            f"{b.hp}/{b.max_hp}{state}")
                ts.tv_print(f"     {ts.color('  '.join(b.moves), 'grey')}")
            ts.tv_print()
            if self.box:
                ts.tv_print(f"  {len(self.box)} more waiting in the box at camp.")
            ts.tv_print()
            pick = ts.menu("Team", ["Reorder (choose a leader)", "Read about one"],
                           back="Back")
            if pick == -1:
                return
            if pick == 0:
                self.swap_menu()
            else:
                which = ts.menu("Read about", [b.name for b in self.party], back="Back")
                if which >= 0:
                    b = self.party[which]
                    self.header(b.name)
                    ts.tv_print()
                    ts.tv_print(ts.box([
                        f"  {b.name}   {b.type}   Lv {b.level}",
                        "",
                        f"  {SPECIES[b.slug]['flavour']}",
                        "",
                        f"  HP {b.max_hp}   ATK {b.atk}   DEF {b.dfn}   SPD {b.spd}",
                        f"  XP {b.xp}/{b.xp_needed()} to the next level",
                        "",
                        f"  Ability: {b.ability} -- {ABILITY_DESC[b.ability]}",
                        "",
                        f"  Moves: {', '.join(b.moves)}",
                    ]))
                    ts.tv_print()
                    ts.tv_pause()

    def box_screen(self) -> None:
        if not self.box:
            self.header("The box")
            ts.tv_print()
            ts.tv_print("  The box is empty.")
            ts.tv_print()
            ts.tv_pause()
            return
        while True:
            self.header("The box")
            ts.tv_print()
            names = [f"{b.name}  Lv {b.level}  {b.type}" for b in self.box]
            pick = ts.menu("Bring one into your team", names, back="Back")
            if pick == -1:
                return
            if len(self.party) >= PARTY_MAX:
                ts.tv_print(ts.color("  Your team is full — send one back first.",
                                     "bright_red"))
                ts.tv_pause()
                continue
            self.party.append(self.box.pop(pick))
            self.store()

    def shop(self) -> None:
        while True:
            self.header("Camp supplies")
            ts.tv_print()
            ts.tv_print(f"  You have {ts.color(str(self.money), 'bright_yellow')} coins"
                        f" and {self.lures} lures.")
            ts.tv_print()
            pick = ts.menu("Buy", ["Lure  — 40 coins", "Five lures — 180 coins"],
                           back="Back")
            if pick == -1:
                return
            cost, amount = (40, 1) if pick == 0 else (180, 5)
            if self.money < cost:
                ts.tv_print(ts.color("  Not enough coins.", "bright_red"))
                ts.tv_pause()
                continue
            self.money -= cost
            self.lures += amount
            self.store()

    def dex(self) -> None:
        self.header("Field notes")
        ts.tv_print()
        ts.tv_print(f"  Seen {len(self.seen)}/{len(SPECIES)}   "
                    f"caught {len(self.caught)}/{len(SPECIES)}")
        ts.tv_print()
        rows = []
        for slug, data in SPECIES.items():
            mark = "●" if slug in self.caught else ("○" if slug in self.seen else "·")
            name = data["name"] if slug in self.seen else "?????"
            rows.append(f"{mark} {name.ljust(13)}")
        for i in range(0, len(rows), 3):
            ts.tv_print("  " + "".join(rows[i:i + 3]))
        ts.tv_print()
        ts.tv_pause()

    # ------------------------------------------------------------- start
    def choose_starter(self) -> None:
        ts.tv_clear(page=PAGE)
        ts.tv_print(ts.title("B E A S T L I N G"))
        ts.tv_print()
        ts.tv_print("  Three of them are awake and looking at you.")
        ts.tv_print()
        for slug in STARTERS:
            d = SPECIES[slug]
            ts.tv_print(f"  {ts.color(d['name'].ljust(12), 'bright_cyan')}"
                        f"{d['type'].ljust(7)}{ts.color(d['flavour'], 'grey')}")
        ts.tv_print()
        pick = ts.menu("Which one comes with you?",
                       [SPECIES[s]["name"] for s in STARTERS], back=None)
        starter = Beast(STARTERS[pick], 5)
        name = ts.prompt(f"  Name your {starter.base['name']} (enter to keep it)")
        if name:
            starter.nickname = name[:12]
        self.party.append(starter)
        self.caught.add(starter.slug)
        self.seen.add(starter.slug)
        self.store()

    def camp(self) -> None:
        while True:
            self.header("Camp")
            ts.tv_print()
            lead = self.lead()
            hurt = [b for b in self.party if b.hp < b.max_hp]
            ts.tv_print(f"  Badges {self.badges}/{len(CHAMPIONS)}    "
                        f"team of {len(self.party)}    "
                        f"{len(self.caught)}/{len(SPECIES)} caught")
            if lead:
                ts.tv_print(f"  Leading {lead.name} (Lv {lead.level})")
            if hurt:
                ts.tv_print(ts.color(f"  {len(hurt)} of your team are hurt.", "yellow"))
            ts.tv_print()

            options = ["Travel", "Rest (heal the team)", "Your team",
                       "Field notes", "The box", "Supplies"]
            if self.badges < len(CHAMPIONS):
                champ = CHAMPIONS[self.badges]
                options.insert(1, f"Challenge {champ['name']}")
            pick = ts.menu("Camp", options, back="Save and quit")
            if pick == -1:
                self.store()
                return
            label = options[pick]
            if label == "Travel":
                self.travel()
            elif label.startswith("Challenge"):
                self.challenge(CHAMPIONS[self.badges])
            elif label.startswith("Rest"):
                self.heal_all()
                self.store()
                self.header("Camp")  # same reasoning as travel()'s fix above
                ts.tv_print()
                ts.tv_print(ts.color("  Everyone is patched up.", "bright_green"))
                ts.tv_pause()
            elif label == "Your team":
                self.team_screen()
            elif label == "Field notes":
                self.dex()
            elif label == "The box":
                self.box_screen()
            elif label == "Supplies":
                self.shop()

    def travel(self) -> None:
        # A clear before this menu, not just before explore()'s own screen:
        # without it, this call inherits whatever row Camp's own (now
        # 9-option) menu left `_tv_state` at, and once that's close enough
        # to the bottom, `_seat_cursor` silently clears the picture right
        # before the "choose:" prompt -- the menu prints, then vanishes
        # before the player ever sees it. Found by actually driving the
        # game through a PTY, not by reading the code.
        self.header("Travel")
        ts.tv_print()
        open_routes = [r for r in ROUTES if r["need"] <= self.badges]
        locked = len(ROUTES) - len(open_routes)
        names = [f"{r['name']}  (Lv {r['levels'][0]}-{r['levels'][1]})"
                 for r in open_routes]
        if locked:
            names.append(ts.color(f"  {locked} more open up with badges", "grey"))
        pick = ts.menu("Where to?", names, back="Stay at camp")
        if pick == -1 or pick >= len(open_routes):
            return
        self.explore(open_routes[pick])


def run_story() -> None:
    save = ts.load({"party": [], "box": [], "badges": 0, "seen": [], "caught": [],
                    "lures": 8, "money": 300, "version": 1})
    game = Game(save)

    if not game.party:
        ts.tv_clear(page=PAGE)
        ts.tv_print(ts.title("B E A S T L I N G"))
        ts.tv_print()
        ts.tv_print(ts.box([
            "  The Hollow Vale is full of creatures and short of people",
            "  who will walk out and meet them.",
            "",
            "  Catch them with lures, raise them, and beat the five",
            "  champions who keep the roads.",
            "",
            "  Type the number next to a choice and press enter.",
        ]))
        ts.tv_print()
        ts.tv_pause()
        game.choose_starter()

    game.camp()

    ts.tv_clear(page=14)
    ts.tv_print(ts.title("B E A S T L I N G"))
    ts.tv_print()
    ts.tv_print(ts.box([
        f"  badges     {game.badges}/{len(CHAMPIONS)}",
        f"  caught     {len(game.caught)}/{len(SPECIES)}",
        f"  seen       {len(game.seen)}/{len(SPECIES)}",
        f"  team       {', '.join(b.name for b in game.party) or 'nobody'}",
    ], fg="yellow"))
    ts.tv_print()
    ts.tv_pause()


def main() -> int:
    ts.tv("Beastling")
    while True:
        ts.tv_clear(page=PAGE)
        ts.tv_print(ts.title("B E A S T L I N G"))
        ts.tv_print()
        ts.tv_print(ts.box([
            "  Story Mode -- catch, raise and battle creatures in the",
            "  Hollow Vale. Beat the five champions who keep the roads.",
            "",
            "  Tournament -- draft a squad from every known species and",
            "  climb the Circuit. No catching required: create a",
            "  trainer, draft a team, fight the bracket.",
        ]))
        ts.tv_print()
        pick = ts.menu("Beastling", ["Story Mode", "Tournament"], back="Quit")
        if pick == -1:
            return 0
        if pick == 0:
            run_story()
        else:
            import circuit
            circuit.run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
