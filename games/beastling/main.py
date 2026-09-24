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
from beasts import (ABILITY_DESC, CHAMPIONS, CHART, ITEMS, MOVES, ROUTES, SPECIES,
                    STARTERS, TYPE_ABILITY, TYPE_SYNERGY, WEATHER_DESC,
                    WEATHER_DURATION, WEATHER_EFFECTS)

# Vertical-centring target for `ts.tv_clear(page=PAGE)`. The real content
# height of the worst-case battle screen is 17 print calls (verified by
# direct execution, not arithmetic -- an earlier pass here claimed 15 and
# was wrong by 2). Do not "fix" PAGE to 17 to match that. `tv_clear`'s
# centring offset is `max(0, (screen.height - page) // 2)`, and at this
# game's declared minimum terminal size (game.toml: 66x24, inner height
# 20) PAGE=19 already gives `max(0, (20-19)//2) == 0` -- no offset, content
# starts at row 0. That leaves a real but THIN margin of 1 row before
# `_seat_cursor`'s own silent-clear threshold (height-2). Correcting PAGE
# to 17 would introduce a real 1-row centring offset at that same size and
# consume that entire margin, reopening the exact bug this constant is
# protecting against -- silently, since no test suite exists for this
# project to catch it.
#
# Known, accepted, out-of-scope limitation: nothing in termstation
# actually enforces a game's declared min_cols/min_rows (`Game.fits()` in
# termstation/library.py has zero callers anywhere in the console), so a
# real terminal smaller than the declared minimum -- a raw 66x22 or 66x23,
# both ordinary tmux/terminal sizes -- still hits the same silent wipe
# today. That's a termstation-wide gap (no game here enforces its own
# minimum), not something one game's code can fix by itself. Separately,
# `Game.fits()`'s own semantics check the declared min against the
# BEZEL-INNER size, not raw terminal size, while this file's min_rows was
# raised against the RAW reading -- the two disagree with each other. Both
# are real, both are pre-existing/project-wide, and fixing either belongs
# in termstation's own launcher code, not here.
PAGE = 19
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
        self.item: str | None = None         # persisted (see to_dict/from_dict) --
                                              # a player equip choice, not combat state
        # --- transient combat state: never saved (see to_dict/from_dict),
        # always reset at the top of `Game.battle` and again on send-out,
        # so nothing leaks between encounters or between party members.
        self.status: str | None = None       # None|"burn"|"paralyze"|"sleep"|"confused"
        self.status_turns = 0                # sleep/confused duration; burn/paralyze
                                              # ignore this, they last the whole battle
        self.atk_stage = 0
        self.def_stage = 0
        self.spd_stage = 0
        self.vengeful_used = False           # Vengeful triggers once per battle
        self.item_used = False               # Mending Berry is once per battle too

    def reset_combat_state(self) -> None:
        self.status = None
        self.status_turns = 0
        self.atk_stage = self.def_stage = self.spd_stage = 0
        self.vengeful_used = False
        self.item_used = False

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
        mult *= ITEMS.get(self.item, {}).get("speed", 1.0)
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
                "hp": self.hp, "nickname": self.nickname, "item": self.item}

    @classmethod
    def from_dict(cls, data: dict) -> "Beast":
        b = cls(data.get("slug", "sproutling"), int(data.get("level", 5)),
                data.get("nickname", ""))
        b.xp = int(data.get("xp", 0))
        b.hp = max(0, min(int(data.get("hp", b.max_hp)), b.max_hp))
        item = data.get("item")
        b.item = item if item in ITEMS else None  # a renamed/removed item degrades to none
        return b


# ---------------------------------------------------------------- combat maths

def effectiveness(move_type: str, defender_type: str) -> float:
    return CHART.get(move_type, {}).get(defender_type, 1.0)


def active_synergy(a: Beast | None, b: Beast | None) -> dict | None:
    """2v2 only: the synergy bonus (if any) for a side's two active
    beasts. Both must be alive and present -- a fainted or empty slot
    breaks the pair, same as a real doubles team losing a partner."""
    if a is None or b is None or not a.alive or not b.alive:
        return None
    return TYPE_SYNERGY.get(frozenset({a.type, b.type}))


def effect_word(mult: float) -> str:
    if mult >= 2.0:
        return "It's super effective!"
    if mult <= 0.5:
        return "It barely scratches."
    return ""


CRIT_CHANCE = 1 / 16   # Gen-1-flavoured: rare enough to feel earned, not spammy
CRIT_MULT = 1.5


def damage(attacker: Beast, defender: Beast, move: str,
           weather: str | None = None, dmg_mult: float = 1.0,
           crit_bonus: float = 0.0) -> tuple[int, float, bool, bool]:
    """Returns (damage, type multiplier, hit?, crit?).

    `weather` is field-wide, not tied to either beast, so it's a plain
    parameter here rather than something read off attacker/defender --
    kept as a SEPARATE multiplier from `mult` (type effectiveness) since
    it drives no "It's super effective!"-style text of its own and
    shouldn't be folded into the number that does.

    `dmg_mult`/`crit_bonus` exist for 2v2 type synergy (see
    `active_synergy`) -- both default to a no-op so every existing 1v1
    call site is unaffected. Synergy needed a crit-chance hook, not just
    a flat damage multiplier, so it has to live inside `damage` itself
    rather than being applied to the return value the way weather/item
    multipliers are folded in below.
    """
    spec = MOVES[move]
    m_type, power, accuracy = spec["type"], spec["power"], spec["accuracy"]
    if random.randint(1, 100) > accuracy:
        return 0, 1.0, False, False
    mult = effectiveness(m_type, defender.type)
    if m_type == attacker.type:
        mult *= 1.25                      # it suits them
    crit = random.random() < CRIT_CHANCE + crit_bonus
    # The divisor is tuned against these stat sizes: a neutral hit between
    # equal levels should take about five exchanges, so a super-effective
    # choice (two or three) is a real decision rather than a rounding error.
    base = ((2 * attacker.level / 5 + 2) * power * attacker.eff_atk / max(1, defender.eff_def)) / 26
    dealt = (base + 2) * mult * (CRIT_MULT if crit else 1.0) * random.uniform(0.85, 1.0)
    dealt *= WEATHER_EFFECTS.get(weather, {}).get(m_type, 1.0)
    dealt *= ITEMS.get(attacker.item, {}).get("dmg_dealt", 1.0)
    dealt *= ITEMS.get(defender.item, {}).get("dmg_taken", 1.0)
    dealt *= dmg_mult
    if defender.ability == "Thick Hide" and mult >= 2.0:
        dealt *= 0.75
    return max(1, int(dealt)), mult, True, crit


STAGE_NAME = {"atk": "Atk", "def": "Def", "spd": "Spd"}


def status_immune(beast: Beast, status: str) -> bool:
    """Single source of truth for ability-granted status immunity -- used
    by both the move-effect path and the on-hit ability-proc path, so a
    future third burn source (or a new immunity) only needs to be taught
    here once."""
    return status == "burn" and beast.ability == "Riptide"


#: sleep/confused wear off after a random number of turns; burn/paralyze
#: don't use this at all (they last the whole battle, until cured).
STATUS_DURATION = {"sleep": (1, 3), "confused": (2, 4)}
STATUS_VERB = {
    "burn": "is burned!",
    "paralyze": "is paralyzed!",
    "sleep": "falls asleep!",
    "confused": "becomes confused!",
}


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
        if status_immune(defender, status):
            return [f"  {defender.name}'s Riptide keeps it from burning!"]
        defender.status = status
        if status in STATUS_DURATION:
            lo, hi = STATUS_DURATION[status]
            defender.status_turns = random.randint(lo, hi)
        return [f"  {defender.name} {STATUS_VERB[status]}"]
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
            and random.random() < TINDER_CHANCE):
        if status_immune(defender, "burn"):
            lines.append(f"  {defender.name}'s Riptide keeps it from burning!")
        else:
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


def check_mending_berry(beast: Beast) -> list[str]:
    """Once per battle, the instant a beast holding a Mending Berry drops
    to a quarter HP or less, it heals back up -- single-use insurance
    against being finished off, not a per-turn heal. Checked AFTER
    `check_vengeful` at every call site: Vengeful's trigger is meant to
    read as a reaction to actually being in danger, so it should see the
    low HP that put the beast there, not an HP total the same event
    already healed back up."""
    spec = ITEMS.get(beast.item)
    if (spec and "heal_threshold" in spec and not beast.item_used and beast.alive
            and beast.hp <= beast.max_hp * spec["heal_threshold"]):
        beast.item_used = True
        healed = int(beast.max_hp * spec["heal_amount"])
        beast.hp = min(beast.max_hp, beast.hp + healed)
        return [f"  {beast.name}'s Mending Berry heals it for {healed} HP!"]
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
            lines.extend(check_vengeful(beast))       # burn can cross the threshold too
            lines.extend(check_mending_berry(beast))
        return lines
    return []


CONFUSION_SELF_HIT_CHANCE = 0.33


def may_act(beast: Beast) -> tuple[bool, list[str]]:
    """Returns (can_act, log_lines). Three status ailments gate action,
    each differently: paralysis has a real chance to no-sell a turn
    entirely (unchanged from before); sleep guarantees no action for a
    random 1-3 turns, then wakes on its own (waking doesn't cost the
    turn -- a beast that wakes up this turn still acts); confusion is
    the odd one out -- it doesn't block the CHOSEN move, it sometimes
    replaces it with a typeless self-hit instead, wearing off after a
    random 2-4 turns regardless of whether it triggered that turn."""
    if beast.status == "sleep":
        beast.status_turns -= 1
        if beast.status_turns <= 0:
            beast.status = None
            return True, [f"  {beast.name} wakes up!"]
        return False, [f"{beast.name} is fast asleep."]
    if beast.status == "paralyze" and random.random() < 0.25:
        return False, [f"{beast.name} is fully paralyzed! It can't move!"]
    if beast.status == "confused":
        beast.status_turns -= 1
        if beast.status_turns <= 0:
            beast.status = None
            return True, [f"  {beast.name} snaps out of its confusion!"]
        if random.random() < CONFUSION_SELF_HIT_CHANCE:
            dot = max(1, beast.max_hp // 8)
            beast.hp = max(0, beast.hp - dot)
            lines = [f"{beast.name} is confused! It hurt itself. ({dot} HP)"]
            if not beast.alive:
                lines.append(f"{beast.name} is out of the fight!")
            return False, lines
    return True, []


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


STATUS_TAG = {
    "burn": ("BRN", "bright_red"),
    "paralyze": ("PAR", "bright_yellow"),
    "sleep": ("SLP", "bright_blue"),
    "confused": ("CNF", "bright_magenta"),
}


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
    # Ability shares the HP line, not its own line, and not the name/type
    # line either -- this has bounced between both once already. Giving it
    # a dedicated 3rd line (a prior fix, for a real clipping bug at narrow
    # widths) turned out to cost a ROW every battle, and a real PTY probe
    # at a stock 80x24 terminal -- not the oversized one this project kept
    # testing at -- showed the worst case (4 known moves, max stat stages,
    # a status, weather active) silently blanking the entire screen before
    # the player ever saw it: a row-budget regression, the same failure
    # class as the travel()/draft-screen bugs, just never checked at a
    # realistic terminal size. Appending to the HP line risks the narrow-
    # width clipping the 3-line version was built to avoid, in the rare
    # case of long ability name + full stages + status all at once -- but
    # clipped text degrades far more gracefully than the WHOLE SCREEN
    # vanishing, which is what the 3-line version did at normal height.
    return [
        f"{head}{lv.rjust(max(1, 44 - len(head)))}  {ts.color(b.type, 'cyan')}",
        f"   HP [{bar(b.hp, b.max_hp)}] {b.hp}/{b.max_hp}{status}"
        f"{ts.color(stages, 'grey')}  {ts.color(b.ability, 'grey')}",
    ]


#: 2v2 only. Doubling the active count to 4 doesn't leave room for
#: `beast_line`'s 2-lines-per-beast format (the 1v1 battle screen is
#: already down to a single row of margin at the declared minimum, see
#: the comment above `beast_line`) -- one line per beast, ability and
#: stat stages dropped (they're a tap away on the team screen before the
#: fight, not a live decision the way HP/status/type are), is the trade
#: that keeps the whole screen on the right side of the row budget.
#: Verified against the game's declared minimum by direct execution
#: (`_row_probe_2v2.py`), same discipline as every other screen here.
def compact_beast_line(b: Beast, wild: bool = False) -> str:
    # No `None`/"-- fainted --" case -- battle_2v2 has no bench, so a
    # downed active is still the same Beast object at 0 HP, never
    # replaced with nothing to show.
    tag = "Wild " if wild else ""
    status = ""
    if b.status and b.alive:
        # A fainted beast's status is irrelevant (and, worse, stale --
        # nothing clears it) -- showing e.g. "0/130 BRN" reads as a bug,
        # not as "it died while burned."
        word, colour = STATUS_TAG[b.status]
        status = "  " + ts.color(word, colour)
    # Pad the plain type text to a fixed width BEFORE colouring it --
    # colouring first and padding after would pad against the string's
    # raw length (escape bytes included), silently breaking alignment.
    return (f"  {tag}{b.name[:11]:<11} {ts.color(b.type.ljust(5), 'cyan')} "
            f"Lv{b.level:>3} [{bar(b.hp, b.max_hp, 8)}] {b.hp:>3}/{b.max_hp:<3}{status}")


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

        # Field-wide, not tied to either beast -- local to this one battle,
        # same as `log`, rather than living on `self` (nothing about it
        # should survive past this encounter) or on a Beast (it affects
        # both sides equally, not one creature).
        weather: str | None = None
        weather_turns = 0

        while True:
            me = self.lead()
            if me is None:
                return "lost"
            # Tracked per-turn so the end-of-turn expiry below can skip
            # decrementing on the exact turn weather was (re)set -- without
            # this, "Lasts 5 turns" would never actually show "5" on
            # screen: it was being set to 5 and decremented to 4 in the
            # same turn, before the player's next screen ever painted it.
            weather_set_this_turn = False
            # Checked every time through, not just when hit: a Vengeful
            # beast (or a Mending Berry holder) sent out (or swapped in)
            # already below a quarter HP -- this game keeps wounds across
            # un-healed fights -- deserves the same trigger a mid-battle
            # hit would give it. Idempotent and cheap thanks to
            # `vengeful_used`/`item_used`, so checking on every loop pass
            # rather than only at send-out is simplest and correct rather
            # than needing a hook at every swap-in site.
            #
            # A real bug lived here: Mending Berry was only wired to the
            # OTHER two call sites `check_vengeful` uses (after a direct
            # hit, and after burn's end-of-turn tick), missing this one --
            # so a beast equipped with the berry and sent into a new fight
            # already wounded (the exact "insurance" scenario the item
            # exists for) never got the heal until its NEXT hit, if any.
            log.extend(check_vengeful(me))
            log.extend(check_mending_berry(me))

            self.header(title)
            for line in beast_line(foe, wild=wild):
                ts.tv_print(line)
            for line in beast_line(me):
                ts.tv_print(line)
            # This one line does double duty: the weather status when
            # there's weather to show, the plain separator rule otherwise
            # -- not "rule, then weather" as a 3rd line, and no blank
            # separator between the two beasts either. Both were pure
            # cosmetic slack the row-budget regression above couldn't
            # actually afford; see the comment on `beast_line`.
            if weather:
                ts.tv_print(ts.color(f"   {weather} ({weather_turns} left) -- "
                                     f"{WEATHER_DESC[weather]}", "bright_yellow"))
            else:
                ts.tv_print(ts.rule("─"))
            show_log(log)
            ts.tv_print(ts.rule("─"))

            options = []
            for i, move in enumerate(me.moves, 1):
                spec = MOVES[move]
                quick = ts.color(" quick", "bright_yellow") if spec["priority"] > 0 else ""
                wx = ts.color(f" {spec['sets_weather']}", "bright_yellow") if spec["sets_weather"] else ""
                ts.tv_print(f"   {ts.color(str(i), 'bright_cyan')}  "
                            f"{move.ljust(13)} {spec['type'].ljust(6)} "
                            f"pow {spec['power']:>2}  acc {spec['accuracy']}{quick}{wx}")
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
                can_act, status_lines = may_act(attacker)
                log.extend(status_lines)
                if not can_act:
                    continue
                dealt, mult, hit, crit = damage(attacker, defender, move, weather)
                if not hit:
                    log.append(f"{attacker.name}'s {move} missed.")
                    continue
                defender.hp = max(0, defender.hp - dealt)
                note = effect_word(mult)
                if crit:
                    note = ("A critical hit! " + note).strip()
                log.append(f"{attacker.name} used {move}. {note}".strip())
                log.append(f"  {defender.name} lost {dealt} HP.")
                new_weather = MOVES[move]["sets_weather"]
                if new_weather:
                    fresh = new_weather != weather
                    weather, weather_turns = new_weather, WEATHER_DURATION
                    weather_set_this_turn = True
                    if fresh:
                        log.append(f"  {new_weather} rolls in!")
                    else:
                        log.append(f"  {new_weather} holds.")
                # The move's own intended effect resolves BEFORE ability
                # procs, not after -- a reviewed ordering hazard: both
                # `apply_move_effect`'s status branch and Tinder already
                # guard on `defender.status is None`, so whichever runs
                # first wins the status. With abilities running first, an
                # on-hit status ability could silently pre-empt and
                # overwrite the move's own, more specific, intended status.
                # Harmless today (Tinder and Ember's only status move both
                # inflict burn) but a live trap for the next status pass.
                if defender.alive:
                    log.extend(apply_move_effect(attacker, defender, move))
                log.extend(apply_ability_on_hit(attacker, defender))
                log.extend(check_vengeful(defender))
                log.extend(check_mending_berry(defender))
                if not defender.alive:
                    log.append(f"{defender.name} is out of the fight!")
                    break

            for b in (foe, me):
                if b.alive:
                    log.extend(resolve_status_upkeep(b))

            if weather and not weather_set_this_turn:
                weather_turns -= 1
                if weather_turns <= 0:
                    log.append(f"  {weather} fades.")
                    weather = None

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

    # --------------------------------------------------------------- 2v2
    def battle_2v2(self, foe_a: Beast, foe_b: Beast, wild: bool, title: str,
                   trainer: str = "") -> str:
        """Two actives per side, Temtem-style, with a type-synergy bonus
        when a side's pair is a listed match (see `active_synergy`).

        Deliberately scoped down from a full doubles system, the same
        "additive, not a rewrite of the shared path" shape every prior
        item took: your two actives are your first two healthy party
        members, fixed for the whole encounter -- no bench, no swapping
        in. If both of them faint, the encounter is a loss even if the
        rest of your party is healthy. There's no catching here either
        (Circuit's trainer battles never supported that anyway). `battle`
        itself is untouched -- Story's wild/trainer 1v1 and all of
        Circuit/Tournament keep using it exactly as before.

        Default targeting is slot-mirrored (your first active vs. their
        first, your second vs. their second) with no manual target
        picker -- a second `ask_int` per attacker is a second silent-wipe
        risk this project has spent the whole session chasing out of
        every other screen, not something to reintroduce here for a
        rarely-exercised choice. Once a side is down to one active,
        both of the opposing side's attackers converge on it instead of
        one hitting nothing; if the first of them kills it before the
        second one's turn comes up, that second action simply has
        nothing left to hit -- with only 2 actives per side there is
        never a THIRD beast to redirect to, so this is a fizzle, not a
        retarget (see the comment where it's checked).
        """
        healthy = self.healthy()
        if len(healthy) < 2:
            return "lost"          # call site is expected to gate entry
        ally_a, ally_b = healthy[0], healthy[1]
        self.seen.add(foe_a.slug)
        self.seen.add(foe_b.slug)
        for b in (foe_a, foe_b, ally_a, ally_b):
            b.reset_combat_state()
        log: list[str] = []
        if wild:
            log.append(f"Wild {foe_a.name} and {foe_b.name} appear!")
        else:
            log.append(f"{trainer} sends out {foe_a.name} and {foe_b.name}!")
        # Synergy is static for a pair's whole lifetime (it can only end
        # by one of them fainting, never turn-by-turn), so announcing it
        # once here -- instead of spending a row on it every draw -- is
        # correct, not just cheaper.
        for owner, pair in (("Your side's", (ally_a, ally_b)), ("The foe's", (foe_a, foe_b))):
            syn = active_synergy(*pair)
            if syn:
                log.append(f"{owner} {syn['name']} is active -- {syn['desc']}")

        weather: str | None = None
        weather_turns = 0

        def draw() -> None:
            self.header(title)
            ts.tv_print(compact_beast_line(foe_a, wild=wild))
            ts.tv_print(compact_beast_line(foe_b, wild=wild))
            ts.tv_print(ts.rule("─"))
            ts.tv_print(compact_beast_line(ally_a))
            ts.tv_print(compact_beast_line(ally_b))
            if weather:
                ts.tv_print(ts.color(f"   {weather} ({weather_turns} left) -- "
                                     f"{WEATHER_DESC[weather]}", "bright_yellow"))
            else:
                ts.tv_print(ts.rule("─"))
            # keep=2, not the 4 the 1v1 screen affords -- doubling the
            # active count already ate the row budget's slack; verified
            # against the declared minimum with `_row_probe_2v2.py`
            # before any of this loop was written, same order this
            # project has learned the hard way to do things in.
            for line in log[-2:]:
                ts.tv_print(f"  {line}")
            for _ in range(2 - len(log[-2:])):
                ts.tv_print()
            ts.tv_print(ts.rule("─"))

        def initial_target(slot: str, defending_side: tuple[Beast, Beast]) -> Beast | None:
            mirrored = defending_side[0] if slot == "a" else defending_side[1]
            if mirrored.alive:
                return mirrored
            other = defending_side[1] if slot == "a" else defending_side[0]
            return other if other.alive else None

        while True:
            weather_set_this_turn = False
            for beast in (ally_a, ally_b, foe_a, foe_b):
                if beast.alive:
                    log.extend(check_vengeful(beast))
                    log.extend(check_mending_berry(beast))

            # ---- player picks a move for each of their alive actives;
            # "run" (wild only) is offered on either prompt and, if
            # taken, ends move-selection immediately for the whole side.
            chosen: dict[str, str | None] = {"a": None, "b": None}
            fled = False
            for slot, beast in (("a", ally_a), ("b", ally_b)):
                if not beast.alive:
                    continue
                draw()
                for i, move in enumerate(beast.moves, 1):
                    spec = MOVES[move]
                    ts.tv_print(f"   {i}  {move.ljust(13)} {spec['type'].ljust(6)} "
                                f"pow {spec['power']:>2}  acc {spec['accuracy']}")
                n = len(beast.moves)
                if wild:
                    ts.tv_print(f"   {n + 1}  run")
                    choice = ts.ask_int(f"{beast.name}'s move", 1, n + 1)
                else:
                    choice = ts.ask_int(f"{beast.name}'s move", 1, n)
                if wild and choice == n + 1:
                    fled = True
                    break
                chosen[slot] = beast.moves[choice - 1]

            if fled:
                if random.random() < 0.7:
                    return "fled"
                log.append("You couldn't get away!")
                # Matches 1v1's failed-flee shape: the attempt spends
                # both actives' turns, but the foes still get to act --
                # `chosen` just stays empty rather than looping past them.

            # ---- build this round's action order
            order: list[tuple[Beast, Beast, str]] = []
            for slot, beast in (("a", ally_a), ("b", ally_b)):
                move = chosen[slot]
                if beast.alive and move is not None:
                    target = initial_target(slot, (foe_a, foe_b))
                    if target is not None:
                        order.append((beast, target, move))
            for slot, beast in (("a", foe_a), ("b", foe_b)):
                if beast.alive:
                    target = initial_target(slot, (ally_a, ally_b))
                    if target is not None:
                        order.append((beast, target, choose_ai_move(beast, target)))
            order.sort(key=lambda e: (-MOVES[e[2]]["priority"], -e[0].eff_spd))

            for attacker, target, move in order:
                if not attacker.alive:
                    continue
                defender = target
                if not defender.alive:
                    # With only 2 actives per side, mirrored targeting is
                    # exclusive whenever both defenders are alive at
                    # build time (ally_a always got foe_a, ally_b always
                    # got foe_b) -- the only way a queued target is
                    # already down here is that its side was ALREADY
                    # reduced to this one survivor before the round
                    # began, so both attackers on the other side were
                    # assigned it, and the first of them just killed it.
                    # There is, by construction, no third beast on that
                    # side left to redirect to -- this can only fizzle,
                    # never actually retarget. Written as a real lookup
                    # instead of an unconditional `continue` anyway, so
                    # it stays correct if 2v2 ever grows past 2 actives.
                    other_side = (foe_a, foe_b) if defender in (foe_a, foe_b) else (ally_a, ally_b)
                    survivor = next((b for b in other_side if b.alive), None)
                    if survivor is None:
                        continue
                    defender = survivor
                can_act, status_lines = may_act(attacker)
                log.extend(status_lines)
                if not can_act:
                    continue
                partner = (ally_b if attacker is ally_a else ally_a) if attacker in (ally_a, ally_b) \
                    else (foe_b if attacker is foe_a else foe_a)
                syn = active_synergy(attacker, partner)
                dmg_mult = syn.get("dmg_mult", 1.0) if syn else 1.0
                crit_bonus = syn.get("crit_bonus", 0.0) if syn else 0.0
                dealt, mult, hit, crit = damage(attacker, defender, move, weather,
                                                dmg_mult=dmg_mult, crit_bonus=crit_bonus)
                if not hit:
                    log.append(f"{attacker.name}'s {move} missed.")
                    continue
                defender.hp = max(0, defender.hp - dealt)
                note = effect_word(mult)
                if crit:
                    note = ("A critical hit! " + note).strip()
                log.append(f"{attacker.name} used {move}. {note}".strip())
                log.append(f"  {defender.name} lost {dealt} HP.")
                new_weather = MOVES[move]["sets_weather"]
                if new_weather:
                    fresh = new_weather != weather
                    weather, weather_turns = new_weather, WEATHER_DURATION
                    weather_set_this_turn = True
                    log.append(f"  {new_weather} " + ("rolls in!" if fresh else "holds."))
                if defender.alive:
                    log.extend(apply_move_effect(attacker, defender, move))
                log.extend(apply_ability_on_hit(attacker, defender))
                log.extend(check_vengeful(defender))
                log.extend(check_mending_berry(defender))
                if not defender.alive:
                    log.append(f"{defender.name} is out of the fight!")
                # No break on a faint here (unlike 1v1's 2-combatant
                # loop) -- with 4 combatants, one fainting must not
                # cancel the other two attackers' turns.

            for beast in (ally_a, ally_b, foe_a, foe_b):
                if beast.alive:
                    log.extend(resolve_status_upkeep(beast))
            # Rainforest Bond's heal-over-time -- the only synergy that
            # needs an end-of-turn hook rather than a per-hit one.
            for pair in ((ally_a, ally_b), (foe_a, foe_b)):
                syn = active_synergy(*pair)
                if syn and "heal_pct" in syn:
                    for b in pair:
                        if b.alive and b.hp < b.max_hp:
                            healed = max(1, int(b.max_hp * syn["heal_pct"]))
                            b.hp = min(b.max_hp, b.hp + healed)
                            log.append(f"  {b.name}'s {syn['name']} heals it for {healed} HP!")

            if weather and not weather_set_this_turn:
                weather_turns -= 1
                if weather_turns <= 0:
                    log.append(f"  {weather} fades.")
                    weather = None

            if not foe_a.alive and not foe_b.alive:
                gained = 0
                for f in (foe_a, foe_b):
                    gained += max(4, int(f.level * 3.2))
                    self.money += 8 + f.level * 2
                # Split, not doubled -- two allies sharing one pool of XP
                # from two foes lands close to 1v1's per-fight pacing
                # instead of running it up.
                each = max(1, gained // 2)
                for ally in (ally_a, ally_b):
                    if ally.alive:
                        for note in ally.gain_xp(each):
                            log.append(note)
                self.header(title)
                ts.tv_print()
                show_log(log, keep=10)
                ts.tv_print()
                ts.tv_pause()
                return "won"

            if not ally_a.alive and not ally_b.alive:
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
        # A real, adjacent bug surfaced by the weather-pass row-budget
        # review: this used to draw straight on top of whatever was
        # already on screen -- the full battle display, already close to
        # the row budget on its own -- with no clear first. A party of
        # even 2-3 beasts was enough to push it over the edge and blank
        # the screen the same way travel()/the draft screen once did.
        ts.tv_clear()
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
            # One line per beast, not two -- a real, pre-existing overflow
            # found while PTY-verifying the items pass: at a full 6-beast
            # party the old 2-line-per-beast listing (plus the header,
            # blanks, and the menu below) pushed this screen well past the
            # row budget at 66x24, silently wiping the roster right after
            # showing it. Move details are already one tap away via "Read
            # about one"; they don't need to duplicate onto this overview.
            self.header("Your team")
            if not self.party:
                ts.tv_print("  You have no beasts.")
            for i, b in enumerate(self.party, 1):
                state = "" if b.alive else ts.color(" (down)", "bright_red")
                ts.tv_print(f"  {i}. {b.name.ljust(13)} Lv{str(b.level).rjust(3)} "
                            f"{b.type.ljust(6)} [{bar(b.hp, b.max_hp, 10)}] "
                            f"{b.hp}/{b.max_hp}{state}")
            if self.box:
                ts.tv_print(f"  {len(self.box)} more in the box.")
            pick = ts.menu("Team", ["Reorder (choose a leader)", "Read about one",
                                    "Equip an item"], back="Back")
            if pick == -1:
                return
            if pick == 0:
                self.swap_menu()
            elif pick == 2:
                self.equip_menu()
            else:
                # Same bug class as swap_menu(), same fix: this used to
                # draw straight on top of the roster listing above it,
                # with no clear first -- found live via the items-pass PTY
                # test, not by inspection.
                ts.tv_clear()
                which = ts.menu("Read about", [b.name for b in self.party], back="Back")
                if which >= 0:
                    b = self.party[which]
                    self.header(b.name)
                    ts.tv_print()
                    # No blank separators between sections here -- a real
                    # row-budget overflow found live via the items-pass
                    # PTY test: adding the two Item lines to what used to
                    # fit was enough to push this panel past the danger
                    # threshold at 66x24. Name/type/desc are still each
                    # their own line (ts.box() truncates rather than
                    # wraps, per the earlier ability-line regression), but
                    # the vertical padding between them was pure cosmetic
                    # cost this panel could no longer afford.
                    ts.tv_print(ts.box([
                        f"  {b.name}   {b.type}   Lv {b.level}",
                        f"  {SPECIES[b.slug]['flavour']}",
                        f"  HP {b.max_hp}  ATK {b.atk}  DEF {b.dfn}  SPD {b.spd}  "
                        f"XP {b.xp}/{b.xp_needed()}",
                        f"  Ability: {b.ability}",
                        f"    {ABILITY_DESC[b.ability]}",
                        f"  Item: {b.item or '(none equipped)'}",
                        *([f"    {ITEMS[b.item]['desc']}"] if b.item else []),
                        f"  Moves: {', '.join(b.moves)}",
                    ]))
                    ts.tv_print()
                    ts.tv_pause()

    def equip_menu(self) -> None:
        """One item slot per beast, free to change any time -- no shop
        cost or inventory count. Adding a real item economy (buying/
        finding/losing items) would be a second, separate system; this
        pass is deliberately just the build-choice layer, same scope
        boundary as leaving AI move selection weather-unaware.

        Story-mode only, and deliberately not documented as an oversight:
        this is `Game`'s own menu, and Circuit/Tournament mode's drafted
        squads (`circuit.py`) never touch it or `Game.store()` -- a
        drafted Beast's `item` stays None for the whole run. Whether
        Ranked draft should eventually cost points for items too, same as
        it already does for species, is a real future design question,
        not something to guess at silently here.
        """
        if not self.party:
            return
        # tv_clear() first, not left implicit -- team_screen()'s own
        # roster listing already draws a fair amount; swap_menu() drawing
        # straight on top of an existing screen with no clear first was a
        # real bug found this session, and this is the same shape of call.
        ts.tv_clear()
        which = ts.menu("Equip which beast?",
                        [f"{b.name}  ({b.item or 'no item'})" for b in self.party],
                        back="Back")
        if which == -1:
            return
        beast = self.party[which]
        ts.tv_clear()
        item_names = list(ITEMS)
        options = [f"{name}  -- {ITEMS[name]['desc']}" for name in item_names]
        options.append("Remove item")
        pick = ts.menu(f"Equip on {beast.name}", options, back="Cancel")
        if pick == -1:
            return
        ts.tv_clear()
        if pick == len(item_names):
            beast.item = None
            ts.tv_print(f"  {beast.name}'s item removed.")
        else:
            beast.item = item_names[pick]
            ts.tv_print(f"  {beast.name} is now holding {beast.item}.")
        ts.tv_print()
        ts.tv_pause()
        self.store()

    #: A box menu with everything on one page hit the dangerous silent
    #: `_seat_cursor` wipe (not tv_print's safe pause-and-continue) at
    #: ordinary sizes -- 12-13 caught beasts, not just some extreme --
    #: verified headlessly against the real row count at the game's
    #: declared minimum. Paginating keeps every page's own row count
    #: well under that threshold regardless of how large the box grows.
    BOX_PAGE = 8

    def box_screen(self) -> None:
        if not self.box:
            self.header("The box")
            ts.tv_print()
            ts.tv_print("  The box is empty.")
            ts.tv_print()
            ts.tv_pause()
            return
        page = 0
        while True:
            pages = max(1, -(-len(self.box) // self.BOX_PAGE))
            page = max(0, min(page, pages - 1))
            start = page * self.BOX_PAGE
            chunk = self.box[start:start + self.BOX_PAGE]
            self.header("The box")
            ts.tv_print()
            if pages > 1:
                ts.tv_print(f"  Page {page + 1}/{pages}")
                ts.tv_print()
            names = [f"{b.name}  Lv {b.level}  {b.type}" for b in chunk]
            options = list(names)
            has_next = pages > 1 and page < pages - 1
            has_prev = pages > 1 and page > 0
            if has_next:
                options.append("Next page")
            if has_prev:
                options.append("Previous page")
            pick = ts.menu("Bring one into your team", options, back="Back")
            if pick == -1:
                return
            if pick < len(names):
                if len(self.party) >= PARTY_MAX:
                    ts.tv_print(ts.color("  Your team is full — send one back first.",
                                         "bright_red"))
                    ts.tv_pause()
                    continue
                self.party.append(self.box.pop(start + pick))
                self.store()
                continue
            pick -= len(names)
            if has_next and pick == 0:
                page += 1
                continue
            if has_next:
                pick -= 1
            if has_prev and pick == 0:
                page -= 1

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
            # One blank separator here, not two -- with the "Challenge"
            # option present this screen was down to a single row of
            # margin at the game's declared minimum (66x24), the same
            # thin margin the main menu had before it actually overflowed.
            # Not broken yet, but this is the screen every session opens
            # on; worth a little real headroom rather than waiting for it
            # to be the fourth thing found this way.
            self.header("Camp")
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
            # Only offered with 2+ healthy party members -- battle_2v2's
            # own entry gate returns an immediate loss below that count,
            # so hiding the option is the right failure mode here, not
            # showing it and then bouncing the player off a menu they
            # could never actually use (same shape as "Challenge" only
            # appearing once there's a badge left to challenge for).
            if len(self.healthy()) >= 2:
                options.append("Synergy Duel (2v2)")
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
            elif label.startswith("Synergy Duel"):
                self.synergy_duel()

    def synergy_duel(self) -> None:
        """A Story-mode-only way to try `battle_2v2` -- two wild foes at
        roughly the party's own level, not tied to a specific route
        (2v2 is an additional thing to try, not a systemic replacement
        for 1v1 exploration -- Travel still only ever starts a 1v1
        encounter). Needs 2 healthy party members; Camp only offers
        this option when that's already true, so the entry gate inside
        `battle_2v2` itself should never actually fire from here.
        """
        healthy = self.healthy()
        if len(healthy) < 2:
            return
        avg_level = max(1, (healthy[0].level + healthy[1].level) // 2)
        slug_a, slug_b = random.sample(list(SPECIES), 2)
        foe_a = Beast(slug_a, avg_level)
        foe_b = Beast(slug_b, avg_level)
        result = self.battle_2v2(foe_a, foe_b, wild=True, title="Synergy Duel")
        if result == "lost":
            self.blackout()
        self.store()

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
        # A real, freshly-found row-budget bug lived here, independent of
        # every other fix this session -- this screen was never checked
        # at the game's declared minimum before. `ts.title()` alone is 3
        # lines, the old 6-line description box added 2 more for its
        # border, and `ts.menu()` has its OWN undocumented leading blank
        # line before the heading -- together that landed EXACTLY on the
        # `_seat_cursor` silent-wipe threshold at 66x24 (traced directly:
        # row 18 of a height-20 screen, threshold height-2=18), so this
        # was the very first screen of the game and it was already
        # invisible at the declared minimum. Compact header, short
        # description -- same discipline as everywhere else this bug
        # class has been found and fixed.
        ts.tv_clear(page=PAGE)
        ts.tv_print(ts.color("  B E A S T L I N G", "bright_cyan", bold=True))
        ts.tv_print(ts.rule("─"))
        ts.tv_print()
        ts.tv_print("  Story Mode -- catch, raise and battle in the Hollow Vale.")
        ts.tv_print("  Tournament -- draft from every species. No catching needed.")
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
