#!/usr/bin/env python3
"""Poke and Mon -- catch, raise and battle creatures in the Hollow Vale.

Line-based: everything is printed into the TV picture and read with prompts,
which keeps the systems (types, growth, evolution, catching) the interesting
part rather than the rendering.

All content lives in beasts.py. The rules live here.
"""
from __future__ import annotations

import random
import sys

import termstation_sdk as ts
from beasts import (ABILITY_DESC, CHAMPIONS, CHART, COMMON_DROPS, DROP_CHANCE, ITEMS,
                    MOVES, RARE_DROPS, ROUTES, SHOP_SECTIONS, SPECIES, SUPPLIES,
                    REMATCH, REMATCH_COINS, SPIRE_START_LEVEL, TRAIN_CAP, TRAIN_LABEL, TRAIN_STEP, train_price,
                    RARE_WEIGHT, STARTERS, TYPE_ABILITY, TYPE_SYNERGY, WEATHER_DESC,
                    WEATHER_DURATION, WEATHER_EFFECTS)

_sdk_ask_int = ts.ask_int


def _safe_ask_int(message: str, lo: int | None = None, hi: int | None = None,
                  default: int | None = None) -> int:
    """The SDK's ask_int, minus one trap found by an LLM playtester: every
    invalid entry stacked an error line and a fresh prompt under the screen, so
    three typos on any menu pushed the row counter past the edge and the cursor
    seat silently wiped the whole menu, leaving a blank screen. Here a bad
    entry re-prompts on the same row, with the complaint in the prompt text."""
    st = ts._tv_state
    if not (st.get("active") and ts._tty()):
        return _sdk_ask_int(message, lo, hi, default)
    row0, note = st["row"], ""
    while True:
        st["row"] = row0
        screen = st["screen"]
        col = screen.x + st["indent"] + 1
        sys.stdout.write(f"\x1b[{screen.y + row0 + 1};{col}H" + " " * st["stage"])
        raw = ts.prompt(message + note, "" if default is None else str(default))
        try:
            value = int(raw)
        except ValueError:
            note = " (numbers only)"
            continue
        if lo is not None and value < lo:
            note = f" (minimum is {lo})"
            continue
        if hi is not None and value > hi:
            note = f" (maximum is {hi})"
            continue
        return value


ts.ask_int = _safe_ask_int

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
#: Most beasts from one evolution family a player can hold (party + box).
#: The box used to fill with a dozen of whatever the route spawns most.
#: Counted per family, not per slug: otherwise 3 Pebbletons + 3 Cragjaws
#: (or two forms evolving into the same thing) slips past the cap.
MAX_COPIES = 3
_PARENT = {d["evolve"][1]: s for s, d in SPECIES.items() if d["evolve"]}


def family_root(slug: str) -> str:
    while slug in _PARENT:
        slug = _PARENT[slug]
    return slug
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
        self.train: dict[str, int] = {}      # Training Hall points per stat, persisted
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
        return int(self.base[key] + self.level * scale
                   + getattr(self, "train", {}).get(key, 0) * TRAIN_STEP[key])

    @property
    def max_hp(self) -> int:
        return int(self._stat("hp", 2.2) * ITEMS.get(getattr(self, "item", None), {}).get("hp_mult", 1.0))

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
                "hp": self.hp, "nickname": self.nickname, "item": self.item,
                "train": {k: v for k, v in self.train.items() if v}}

    @classmethod
    def from_dict(cls, data: dict) -> "Beast":
        b = cls(data.get("slug", "sproutling"), int(data.get("level", 5)),
                data.get("nickname", ""))
        b.xp = int(data.get("xp", 0))
        item = data.get("item")
        b.item = item if item in ITEMS else None  # a renamed/removed item degrades to none
        b.train = {k: max(0, min(TRAIN_CAP, int(v))) for k, v in data.get("train", {}).items()
                   if k in TRAIN_STEP}
        # hp is clamped AFTER item and training are set: both raise max_hp,
        # and clamping first silently shaved a saved beast's HP on load.
        b.hp = max(0, min(int(data.get("hp", b.max_hp)), b.max_hp))
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
    crit = random.random() < (CRIT_CHANCE + crit_bonus
                              + ITEMS.get(attacker.item, {}).get("crit_bonus", 0.0))
    # The divisor is tuned against these stat sizes: a neutral hit between
    # equal levels should take about five exchanges, so a super-effective
    # choice (two or three) is a real decision rather than a rounding error.
    base = ((2 * attacker.level / 5 + 2) * power * attacker.eff_atk / max(1, defender.eff_def)) / 26
    dealt = (base + 2) * mult * (CRIT_MULT if crit else 1.0) * random.uniform(0.85, 1.0)
    dealt *= WEATHER_EFFECTS.get(weather, {}).get(m_type, 1.0)
    dealt *= ITEMS.get(attacker.item, {}).get("dmg_dealt", 1.0)
    dealt *= ITEMS.get(defender.item, {}).get("dmg_taken", 1.0)
    boost = ITEMS.get(attacker.item, {}).get("type_boost")
    if boost and boost[0] == m_type:
        dealt *= boost[1]
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
    if ITEMS.get(beast.item, {}).get("status_ward"):
        return True
    return status == "burn" and beast.ability == "Riptide"


def immunity_line(beast: Beast, status: str) -> str | None:
    if status == "burn" and beast.ability == "Riptide":
        return f"  {beast.name}'s Riptide keeps it from burning!"
    if ITEMS.get(beast.item, {}).get("status_ward"):
        return f"  {beast.name}'s Status Ward blocks it!"
    return None


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
            return [immunity_line(defender, status)]
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
            lines.append(immunity_line(defender, "burn"))
        else:
            defender.status = "burn"
            lines.append(f"  {attacker.name}'s Tinder catches {defender.name} alight!")
    if (defender.ability == "Static Charge" and defender.alive and attacker.status is None
            and not status_immune(attacker, "paralyze")
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


def deal_damage(attacker: Beast, defender: Beast, dealt: int) -> list[str]:
    """Applies a landed hit, with the two held items that change what a hit
    does: Last Stand (survive a would-be KO from above a quarter HP, once) and Thorn Wrap
    (the attacker pays a slice of its own max HP). Shared by 1v1 and 2v2."""
    lines: list[str] = []
    held = ITEMS.get(defender.item, {})
    if (held.get("survive") and not defender.item_used and dealt >= defender.hp
            and defender.hp * 4 > defender.max_hp and defender.max_hp > 1):
        defender.hp = 1
        defender.item_used = True
        lines.append(f"  {defender.name} hangs on with Last Stand!")
    else:
        defender.hp = max(0, defender.hp - dealt)
    recoil = held.get("recoil")
    if recoil and attacker.alive:
        cost = max(1, int(attacker.max_hp * recoil))
        attacker.hp = max(0, attacker.hp - cost)
        line = f"  {attacker.name} is pricked by Thorn Wrap. ({cost} HP)"
        if not attacker.alive:
            line += f" {attacker.name} is out of the fight!"
        lines.append(line)
    return lines


def resolve_status_upkeep(beast: Beast) -> list[str]:
    """End-of-turn effects: burn damage (paralysis is checked at action
    time instead, via `may_act`) and Lifeleaf's regeneration."""
    lines: list[str] = []
    if beast.status == "burn" and beast.alive:
        dot = max(1, beast.max_hp // 16)
        beast.hp = max(0, beast.hp - dot)
        line = f"  {beast.name} is hurt by its burn. ({dot} HP)"
        if not beast.alive:
            line += f" {beast.name} is out of the fight!"
        lines.append(line)
        if beast.alive:
            lines.extend(check_vengeful(beast))       # burn can cross the threshold too
            lines.extend(check_mending_berry(beast))
    regen = ITEMS.get(beast.item, {}).get("regen")
    if regen and beast.alive and beast.hp < beast.max_hp:
        healed = max(1, int(beast.max_hp * regen))
        beast.hp = min(beast.max_hp, beast.hp + healed)
        lines.append(f"  {beast.name}'s Lifeleaf restores {healed} HP.")
    return lines


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
        self.rematches: dict[str, int] = {k: int(v) for k, v in save.get("rematches", {}).items()
                                           if k in REMATCH}
        self.spire_best = int(save.get("spire_best", 0))
        raw_bag = save.get("inventory", {"Potion": 3})
        self.inventory: dict[str, int] = {
            k: int(v) for k, v in raw_bag.items()
            if (k in ITEMS or k in SUPPLIES) and int(v) > 0}
        self.money = int(save.get("money", 300))

    # --- persistence
    def store(self) -> None:
        self.save.update(
            party=[b.to_dict() for b in self.party],
            box=[b.to_dict() for b in self.box],
            badges=self.badges, seen=sorted(self.seen), caught=sorted(self.caught),
            lures=self.lures, money=self.money, inventory=dict(self.inventory),
            rematches=dict(self.rematches), spire_best=self.spire_best)
        self.save["_summary"] = (f"{self.badges} badges · {len(self.caught)} caught")
        ts.save(self.save)

    # --- helpers
    def healthy(self) -> list[Beast]:
        return [b for b in self.party if b.alive]

    def lead(self) -> Beast | None:
        healthy = self.healthy()
        return healthy[0] if healthy else None

    def copies(self, slug: str) -> int:
        root = family_root(slug)
        return sum(1 for b in self.party + self.box if family_root(b.slug) == root)

    scent = 0     # walks left with Rare Scent active (transient, not saved)

    #: Circuit sets both False: its squads are fixed-level and bag-less.
    xp_share = True
    items_enabled = True

    def has_supplies(self) -> bool:
        return any(self.inventory.get(n, 0) > 0 for n in SUPPLIES)

    def add_item(self, name: str, count: int = 1) -> None:
        self.inventory[name] = min(99, self.inventory.get(name, 0) + count)

    def roll_drops(self, foe: Beast, rare: bool) -> list[str]:
        """Rare beasts always drop one treasure (win the fight to get it --
        catching it instead is the other way to take that spawn); anything
        else has a small chance at something from the common table."""
        if not self.items_enabled:
            return []
        if rare:
            name = random.choice(RARE_DROPS)
            self.add_item(name)
            return [f"  The rare {foe.name} dropped {name}!"]
        if random.random() < DROP_CHANCE:
            name = random.choices(list(COMMON_DROPS), weights=list(COMMON_DROPS.values()))[0]
            self.add_item(name)
            return [f"  You found {name}."]
        return []

    def use_item_menu(self, log: list[str] | None = None) -> bool:
        """Pick a supply, then a beast. Returns True if one was used. In a
        fight the result goes to `log`; at camp it's shown and paused."""
        def say(msg: str) -> None:
            if log is not None:
                log.append(msg)
            else:
                ts.tv_print(msg)
                ts.tv_pause()

        stock = [n for n in SUPPLIES if self.inventory.get(n, 0) > 0]
        if not stock:
            say("You have nothing to use.")
            return False
        ts.tv_clear()
        pick = ts.menu("Use which item?",
                       [f"{n} x{self.inventory[n]}  -- {SUPPLIES[n]['desc']}" for n in stock],
                       back="Cancel")
        if pick == -1:
            return False
        name = stock[pick]
        spec = SUPPLIES[name]
        if "scent" in spec:
            if log is not None:
                say("Use it while exploring, not mid-fight.")
                return False
            self.scent = spec["scent"]
            self.inventory[name] -= 1
            if self.inventory[name] <= 0:
                del self.inventory[name]
            ts.tv_clear()
            ts.tv_print(f"  A strange scent clings to you. Rare beasts will find you for")
            ts.tv_print(f"  the next {self.scent} walks.")
            ts.tv_print()
            ts.tv_pause()
            self.store()
            return True
        ts.tv_clear()
        who = ts.menu(f"{name} on which beast?",
                      [f"{b.name}  Lv {b.level}  {b.hp}/{b.max_hp} HP"
                       + (f"  {b.status}" if b.status else "")
                       + ("  (down)" if not b.alive else "") for b in self.party],
                      back="Cancel")
        if who == -1:
            return False
        b = self.party[who]
        lines: list[str] = []
        if "revive" in spec:
            if b.alive:
                say(f"{b.name} isn't down.")
                return False
            b.hp = max(1, int(b.max_hp * spec["revive"]))
            b.reset_combat_state()
            lines.append(f"{b.name} is back on its feet! ({b.hp} HP)")
        elif not b.alive:
            say(f"{b.name} is down -- it needs a Revive.")
            return False
        elif "heal" in spec:
            if b.hp >= b.max_hp:
                say(f"{b.name} is already at full health.")
                return False
            got = min(spec["heal"], b.max_hp - b.hp)
            b.hp += got
            lines.append(f"{b.name} recovered {got} HP.")
        elif spec.get("cure"):
            if not b.status:
                say(f"{b.name} has nothing to cure.")
                return False
            b.status, b.status_turns = None, 0
            lines.append(f"{b.name} shakes it off.")
        elif "level" in spec:
            if b.level >= 60:
                say(f"{b.name} can't grow any more.")
                return False
            lines.extend(n for n in b.gain_xp(b.xp_needed() - b.xp))
        self.inventory[name] -= 1
        if self.inventory[name] <= 0:
            del self.inventory[name]
        for line in lines:
            if log is not None:
                log.append(line)
        if log is None:
            ts.tv_clear()
            for line in lines:
                ts.tv_print(f"  {line}")
            ts.tv_pause()
            self.store()
        return True

    def paged_menu(self, heading: str, options: list[str], back: str,
                   draw=None, per_page: int = 7) -> int:
        """ts.menu() with pages: long lists must not run past the row
        budget (the silent `_seat_cursor` wipe). Returns the option index
        or -1. `draw` repaints whatever should sit above the menu."""
        pages = max(1, -(-len(options) // per_page))
        page = 0
        while True:
            if draw:
                draw()
            else:
                ts.tv_clear()
            chunk = options[page * per_page:(page + 1) * per_page]
            shown = list(chunk)
            if pages > 1:
                shown.append(f"More... (page {page + 1}/{pages})")
            pick = ts.menu(heading, shown, back=back)
            if pick == -1:
                return -1
            if pages > 1 and pick == len(chunk):
                page = (page + 1) % pages
                continue
            return page * per_page + pick

    def share_xp(self, active: Beast, gained: int, also: Beast | None = None) -> list[str]:
        """Healthy party members who didn't fight get a third of the XP, so
        catching things is worth more than a box of level-2 beasts. Only
        level-ups are reported, to keep the win log short."""
        if not self.xp_share:
            return []
        notes: list[str] = []
        for b in self.healthy():
            if b is active or b is also:
                continue
            for note in b.gain_xp(max(1, gained // 3)):
                if "gained" not in note:
                    notes.append(note)
        return notes

    def rest_cost(self) -> int:
        """Camp's rest is no longer free: it scales with how hurt the team is
        and with your badges (a deeper roster costs more to feed). Items and
        potions only mattered when resting cost nothing -- now they're the
        way to stretch a long run between camps."""
        missing = sum(b.max_hp - b.hp for b in self.party)
        if missing <= 0:
            return 0
        return int((5 + missing / 4) * (1 + 0.5 * self.badges))

    def rest(self) -> tuple[int, float]:
        """Pays what it can; heals everyone by the fraction actually paid
        for, so being broke is a partial rest, never a dead end."""
        cost = self.rest_cost()
        if cost == 0:
            return 0, 1.0
        paid = min(cost, self.money)
        frac = paid / cost
        self.money -= paid
        for b in self.party:
            gap = b.max_hp - b.hp
            if gap > 0 and frac > 0:
                b.hp = min(b.max_hp, b.hp + max(1, int(gap * frac)))
        return paid, frac

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
               trainer: str = "", rare: bool = False) -> str:
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
            log.append(f"A rare {foe.name} appears!" if rare else f"A wild {foe.name} appears!")
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
            lure_col = "bright_cyan" if self.lures > 0 else "grey"
            tail = f"   {ts.color(str(extra + 1), lure_col)}  lure"
            if self.lures <= 0:
                tail += " (0)"
            elif self.copies(foe.slug) >= MAX_COPIES:
                tail += " (full)"
            if not wild:
                tail = f"   {ts.color(str(extra + 1), 'grey')}  (no lures in a duel)"
            tail += f"    {ts.color(str(extra + 2), 'bright_cyan')}  swap"
            tail += f"    {ts.color(str(extra + 3), 'bright_cyan')}  run"
            top = extra + 3
            if self.items_enabled and self.has_supplies():
                tail += f"    {ts.color(str(extra + 4), 'bright_cyan')}  item"
                top = extra + 4
            ts.tv_print(tail)
            choice = ts.ask_int("your move", 1, top)

            # ---- player's turn
            player_action = None
            if choice <= extra:
                player_action = me.moves[choice - 1]
            elif choice == extra + 1:
                if not wild:
                    log.append("You can't lure another trainer's beast.")
                    continue
                if self.lures <= 0:
                    # Said once, not stacked: repeating this filled the whole
                    # log, and it didn't cost a turn, so it read as a hang.
                    msg = "No lures left -- buy more at camp (Supplies)."
                    if not log or log[-1] != msg:
                        log.append(msg)
                    continue
                if self.copies(foe.slug) >= MAX_COPIES:
                    msg = f"You already have {MAX_COPIES} of this family -- no room for more."
                    if not log or log[-1] != msg:
                        log.append(msg)
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
            elif choice == extra + 4:
                # Using a supply costs the turn, same as a swap or a lure;
                # backing out of the menu does not.
                if not self.use_item_menu(log):
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
                note = effect_word(mult)
                if crit:
                    note = ("A critical hit! " + note).strip()
                log.append(f"{attacker.name} used {move}. {note}".strip())
                log.append(f"  {defender.name} lost {min(dealt, defender.hp)} HP.")
                log.extend(deal_damage(attacker, defender, dealt))
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
                if not attacker.alive:      # Thorn Wrap recoil
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
                log.extend(self.share_xp(me, gained))
                if wild:
                    log.extend(self.roll_drops(foe, rare))
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
                note = effect_word(mult)
                if crit:
                    note = ("A critical hit! " + note).strip()
                log.append(f"{attacker.name} used {move}. {note}".strip())
                log.append(f"  {defender.name} lost {min(dealt, defender.hp)} HP.")
                log.extend(deal_damage(attacker, defender, dealt))
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
                log.extend(self.share_xp(ally_a, each, also=ally_b))
                for f in (foe_a, foe_b):
                    log.extend(self.roll_drops(f, False))
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

    def swap_label(self, b: Beast) -> str:
        return (f"{b.name}  Lv {b.level}  {b.hp}/{b.max_hp} HP"
                + ("  (down)" if not b.alive else ""))

    def swap_menu(self, forced: bool = False, lines: list[str] | None = None,
                  heading: str = "Send out which beast?") -> bool:
        """Put a chosen beast out front. `forced` is the replacement after the
        lead goes down: no Cancel (there is nothing to go back to -- LLM
        playtesters read a Cancel there as a way out and lost a beat to it),
        and a downed pick asks again. `lines` go above the list, so the
        screen can say what just happened before it asks."""
        options = [self.swap_label(b) for b in self.party]
        if len(options) < 2:
            return False
        lead = self.lead()
        note = ""
        while True:
            # A real, adjacent bug surfaced by the weather-pass row-budget
            # review: this used to draw straight on top of whatever was
            # already on screen -- the full battle display, already close to
            # the row budget on its own -- with no clear first. A party of
            # even 2-3 beasts was enough to push it over the edge and blank
            # the screen the same way travel()/the draft screen once did.
            ts.tv_clear()
            for line in lines or ():
                ts.tv_print(line)
            if note:
                ts.tv_print(ts.color(f"  {note}", "bright_red"))
            pick = ts.menu(heading, options, back=None if forced else "Cancel")
            if pick == -1:
                return False
            chosen = self.party[pick]
            if not chosen.alive:
                note = f"{chosen.name} is down -- pick one still standing."
                continue
            if chosen is lead and not forced:
                # Already the active lead -- a no-op, not a real swap, and it
                # must not cost a turn now that voluntary swaps do (see
                # battle()). Compared by identity, not index 0: a beast that
                # fainted earlier can sit at the front of the party while the
                # lead is further down.
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
            ts.tv_print(f"  Steps taken: {steps}"
                        + (ts.color(f"   Rare Scent: {self.scent} left", "bright_yellow")
                           if self.scent > 0 else ""))
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
            if self.scent > 0:
                self.scent -= 1
            if random.random() < 0.72:
                lo, hi = route["levels"]
                weights = route.get("weights", {})
                boost = 5 if self.scent > 0 else 1
                slug = random.choices(
                    route["wild"],
                    weights=[weights.get(w, 10) * (boost if weights.get(w, 10) <= RARE_WEIGHT else 1)
                             for w in route["wild"]])[0]
                foe = Beast(slug, random.randint(lo, hi))
                result = self.battle(foe, wild=True, title=route["name"],
                                     rare=weights.get(slug, 10) <= RARE_WEIGHT)
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
            f"  Team of {len(champ['team'])}, top level {max(l for _, l in champ['team'])}, "
            f"and their aces carry gear.",
            f"  Your best six average level {self.top_level()}.",
        ]))
        ts.tv_print()
        if not ts.confirm("  Challenge them?", default=True):
            return

        for (slug, level), gear in zip(champ["team"], champ["gear"]):
            foe = Beast(slug, level)
            foe.item = gear
            foe.hp = foe.max_hp
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
        rname, rcount = champ["reward"]
        self.add_item(rname, rcount)
        self.heal_all()
        self.header(champ["name"])
        ts.tv_print()
        ts.tv_print(ts.box([
            f"  You beat {champ['name']}.",
            "",
            f"  {champ['win']}",
            "",
            f"  Badges: {self.badges}/{len(CHAMPIONS)}   +5 lures, and a purse.",
            f"  Reward: {rname}" + (f" x{rcount}" if rcount > 1 else ""),
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
                                    "Equip an item", "Use an item"], back="Back")
            if pick == -1:
                return
            if pick == 0:
                self.swap_menu()
            elif pick == 2:
                self.equip_menu()
            elif pick == 3:
                self.use_item_menu()
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
        gear = [n for n in ITEMS if self.inventory.get(n, 0) > 0]
        options = [f"{n} x{self.inventory[n]}  -- {ITEMS[n]['desc']}" for n in gear]
        if beast.item:
            options.append(f"Take {beast.item} back")
        if not options:
            ts.tv_clear()
            ts.tv_print("  Your bag has no gear. Buy some under Supplies,")
            ts.tv_print("  or find it: rare beasts and champions drop the best.")
            ts.tv_print()
            ts.tv_pause()
            return
        pick = self.paged_menu(f"Equip on {beast.name}", options, "Cancel")
        if pick == -1:
            return
        hp_cap_before = beast.max_hp
        ts.tv_clear()
        if pick == len(gear):
            self.add_item(beast.item)
            ts.tv_print(f"  {beast.name} gives back {beast.item}.")
            beast.item = None
        else:
            new = gear[pick]
            self.inventory[new] -= 1
            if self.inventory[new] <= 0:
                del self.inventory[new]
            if beast.item:
                self.add_item(beast.item)
            beast.item = new
            ts.tv_print(f"  {beast.name} is now holding {new}.")
        # Like a level-up: gaining max HP (Vigor Seed) also raises current HP
        # by the gain; losing it just clamps.
        beast.hp = min(beast.max_hp, beast.hp + max(0, beast.max_hp - hp_cap_before))
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
        msg = ""
        while True:
            self.header("Camp supplies")
            ts.tv_print()
            ts.tv_print(f"  You have {ts.color(str(self.money), 'bright_yellow')} coins"
                        f" and {self.lures} lures.")
            ts.tv_print(ts.color(f"  {msg}", "bright_green") if msg else "")
            labels = ["Lures"] + [label for label, _ in SHOP_SECTIONS] + ["Training hall"]
            pick = ts.menu("Shop", labels, back="Back")
            msg = ""
            if pick == -1:
                return
            if pick == 0:
                msg = self.shop_lures()
            elif pick == len(labels) - 1:
                self.training_hall()
            else:
                self.shop_section(*SHOP_SECTIONS[pick - 1])

    def training_hall(self) -> None:
        """The big coin sink: permanent stat points per beast, escalating
        price, capped per stat. Story mode only (Circuit squads are fixed)."""
        msg = ""
        while True:
            self.header("Training hall")
            ts.tv_print()
            ts.tv_print(f"  You have {ts.color(str(self.money), 'bright_yellow')} coins.")
            ts.tv_print(ts.color(f"  {msg}", "bright_green") if msg else "")
            pick = ts.menu("Train which beast?",
                           [f"{b.name}  Lv {b.level}  trained {sum(b.train.values())}/{len(TRAIN_STEP) * TRAIN_CAP}"
                            for b in self.party], back="Back")
            if pick == -1:
                return
            msg = self.train_beast(self.party[pick])

    def train_beast(self, b: Beast) -> str:
        msg = ""
        while True:
            self.header(f"Train {b.name}")
            ts.tv_print()
            ts.tv_print(f"  You have {ts.color(str(self.money), 'bright_yellow')} coins.")
            ts.tv_print(ts.color(f"  {msg}", "bright_green") if msg else "")
            total = sum(b.train.values())
            options = []
            for key in TRAIN_STEP:
                pts = b.train.get(key, 0)
                cur = {"hp": b.max_hp, "atk": b.atk, "dfn": b.dfn, "spd": b.spd}[key]
                if pts >= TRAIN_CAP:
                    options.append(f"{TRAIN_LABEL[key]:<4} {cur:>3}  maxed ({pts}/{TRAIN_CAP})")
                else:
                    gain = int(TRAIN_STEP[key] * (pts + 1)) - int(TRAIN_STEP[key] * pts)
                    options.append(f"{TRAIN_LABEL[key]:<4} {cur:>3} -> +{max(1, gain)}   "
                                   f"{train_price(pts, total)}c  ({pts}/{TRAIN_CAP})")
            pick = ts.menu(f"Train {b.name}", options, back="Back")
            if pick == -1:
                return f"Trained {b.name} ({total} points)."
            key = list(TRAIN_STEP)[pick]
            pts = b.train.get(key, 0)
            price = train_price(pts, total)
            if pts >= TRAIN_CAP:
                msg = f"{TRAIN_LABEL[key]} is already maxed."
            elif self.money < price:
                msg = "Not enough coins."
            else:
                self.money -= price
                b.train[key] = pts + 1
                self.store()
                msg = f"{b.name}'s {TRAIN_LABEL[key]} went up."

    def shop_lures(self) -> str:
        self.header("Lures")
        ts.tv_print()
        ts.tv_print(f"  You have {ts.color(str(self.money), 'bright_yellow')} coins"
                    f" and {self.lures} lures.")
        pick = ts.menu("Buy", ["Lure  — 25 coins", "Five lures — 110 coins"], back="Back")
        if pick == -1:
            return ""
        cost, amount = (25, 1) if pick == 0 else (110, 5)
        if self.money < cost:
            return "Not enough coins."
        self.money -= cost
        self.lures += amount
        self.store()
        return f"Bought {amount} lure{'s' if amount > 1 else ''}."

    def shop_section(self, label: str, names: list[str]) -> None:
        """One shelf of the shop. Stock unlocks with badges; anything with
        `price` 0 (the rare treasures) is never sold, only found."""
        state = {"msg": ""}

        def draw() -> None:
            self.header(label)
            ts.tv_print()
            ts.tv_print(f"  You have {ts.color(str(self.money), 'bright_yellow')} coins."
                        f"   Badges: {self.badges}")
            m = state["msg"]
            ts.tv_print(ts.color(f"  {m}", "bright_green") if m else "")

        while True:
            options = []
            for n in names:
                spec = ITEMS.get(n) or SUPPLIES[n]
                if spec["need"] > self.badges:
                    plural = "s" if spec["need"] > 1 else ""
                    options.append(ts.color(f"{n:<13} (needs {spec['need']} badge{plural})", "grey"))
                else:
                    options.append(f"{n:<13} {spec['price']:>4}c  {spec['desc']}")
            pick = self.paged_menu(label, options, "Back", draw=draw)
            if pick == -1:
                return
            n = names[pick]
            spec = ITEMS.get(n) or SUPPLIES[n]
            if spec["need"] > self.badges:
                state["msg"] = f"{n} unlocks after {spec['need']} badges."
            elif self.money < spec["price"]:
                state["msg"] = "Not enough coins."
            elif self.inventory.get(n, 0) >= 9:
                state["msg"] = "You can't carry more of those."
            else:
                self.money -= spec["price"]
                self.add_item(n)
                self.store()
                state["msg"] = f"Bought {n}. (you have {self.inventory[n]})"

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
        for i in range(0, len(rows), 4):
            ts.tv_print("  " + "".join(rows[i:i + 4]))
        ts.tv_print()
        ts.tv_pause()

    # ------------------------------------------------------------- start
    def choose_starter(self) -> None:
        ts.tv_clear(page=PAGE)
        ts.tv_print(ts.title("P O K E   A N D   M O N"))
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

            rest_cost = self.rest_cost()
            rest_label = "Rest (heal the team)" + (f" -- {rest_cost}c" if rest_cost else "")
            options = ["Travel", rest_label, "Your team",
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
            if self.badges >= len(CHAMPIONS):
                options.append("Champion's Hall")
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
                paid, frac = self.rest()
                self.store()
                self.header("Camp")  # same reasoning as travel()'s fix above
                ts.tv_print()
                if not paid and frac >= 1:
                    ts.tv_print(ts.color("  Everyone is already fine.", "bright_green"))
                elif frac >= 1:
                    ts.tv_print(ts.color(f"  Everyone is patched up. ({paid} coins)", "bright_green"))
                else:
                    ts.tv_print(ts.color(f"  You could only afford {int(frac * 100)}% of a rest.", "yellow"))
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
            elif label.startswith("Champion's Hall"):
                self.champions_hall()

    # ------------------------------------------------------------ post-game
    def top_level(self) -> int:
        levels = sorted((b.level for b in self.party), reverse=True)[:6]
        return sum(levels) // max(1, len(levels))

    def champions_hall(self) -> None:
        """Opens once all five champions are beaten: scaling rematches and
        the Battle Spire, the two things to do after the story."""
        while True:
            self.header("Champion's Hall")
            ts.tv_print()
            ts.tv_print("  The champions want a rematch -- and they've been training.")
            ts.tv_print()
            options = [f"Rematch {c['name']}  (won {self.rematches.get(c['name'], 0)}x)"
                       for c in CHAMPIONS]
            options.append(f"Battle Spire  (best floor {self.spire_best})")
            pick = ts.menu("Champion's Hall", options, back="Back")
            if pick == -1:
                return
            if pick == len(CHAMPIONS):
                self.spire()
            else:
                self.rematch(CHAMPIONS[pick])

    def rematch(self, champ: dict) -> None:
        name = champ["name"]
        wins = self.rematches.get(name, 0)
        level = max(40, min(80, self.top_level() + 2 + 2 * wins))
        team = REMATCH[name]
        self.header(name)
        ts.tv_print()
        ts.tv_print(ts.box([
            f"  {name}  --  rematch #{wins + 1}",
            "",
            f"  {len(team)} beasts, all about level {level}, all geared.",
            f"  Purse: {REMATCH_COINS + 150 * wins} coins"
            + ("  +  a Growth Candy (first win)" if wins == 0 else "  +  maybe a treasure"),
        ]))
        ts.tv_print()
        if not ts.confirm("  Take them on?", default=True):
            return
        for slug, item in team:
            foe = Beast(slug, level)
            foe.item = item
            foe.hp = foe.max_hp
            result = self.battle(foe, wild=False, title=name, trainer=name)
            if result == "lost":
                self.blackout()
                return
            if result == "fled":
                return
        self.rematches[name] = wins + 1
        coins = REMATCH_COINS + 150 * wins
        self.money += coins
        lines = [f"  You beat {name} again.", "", f"  +{coins} coins"]
        if wins == 0:
            self.add_item("Growth Candy")
            lines.append("  +1 Growth Candy")
        elif random.random() < 0.4:
            prize = random.choice(RARE_DROPS)
            self.add_item(prize)
            lines.append(f"  +{prize}")
        self.header(name)
        ts.tv_print()
        ts.tv_print(ts.box(lines, fg="yellow"))
        ts.tv_print()
        ts.tv_pause()
        self.store()

    def spire_team(self, floor: int) -> list[tuple[str, int, str | None]]:
        """Floor n: level 40 + 2n, 3 beasts (+1 per 8 floors, max 5). Every
        5th floor is a boss: one more beast and EVERYTHING is geared. From
        floor 6 regular foes sometimes carry gear; from 12 that includes
        treasures."""
        evolved = [s for s, d in SPECIES.items() if any(
            v["evolve"] and v["evolve"][1] == s for v in SPECIES.values())]
        boss = floor % 5 == 0
        size = min(5, 3 + floor // 8) + (1 if boss else 0)
        pool = [n for n, d in ITEMS.items() if d["price"] > 0]
        if floor >= 12:
            pool += RARE_DROPS
        level = SPIRE_START_LEVEL + 2 * floor
        team = []
        for _ in range(size):
            item = None
            if pool and (boss or (floor >= 6 and random.random() < 0.35)):
                item = random.choice(pool)
            team.append((random.choice(evolved), level, item))
        return team

    def spire_rewards(self, floor: int) -> list[str]:
        coins = 100 + 40 * floor
        self.money += coins
        lines = [f"+{coins} coins"]
        if floor % 5 == 0:
            prize = random.choice(RARE_DROPS)
            self.add_item(prize)
            lines.append(f"+{prize} (boss reward)")
            # A rest stop after each boss: everyone heals halfway, the
            # fallen come back at a quarter -- long climbs need a breather
            # that isn't a free full reset.
            for b in self.party:
                if b.alive:
                    b.hp = min(b.max_hp, b.hp + (b.max_hp - b.hp) // 2)
                else:
                    b.hp = max(1, b.max_hp // 4)
            lines.append("Rest stop: the team heals halfway.")
        if floor % 10 == 0:
            self.add_item("Growth Candy", 2)
            self.add_item("Rare Scent")
            lines.append("+2 Growth Candy, +1 Rare Scent")
        elif random.random() < 0.15:
            lines.extend(l.strip() for l in self.roll_drops(Beast("pebbleton", 5), False))
        return lines

    def spire(self) -> None:
        """Endless climb. No resting between floors (items work), each
        cleared floor pays out immediately and you can retreat with it;
        losing ends the run with a free heal -- the Spire isn't a fine."""
        self.header("Battle Spire")
        ts.tv_print()
        ts.tv_print(ts.box([
            "  Floor after floor, each tougher than the last.",
            "  No resting between floors -- bring potions.",
            "  Every floor pays; every 5th is a geared boss.",
            "  Retreat after any clear, or fall and be healed free.",
        ]))
        ts.tv_print()
        if not ts.confirm("  Climb?", default=True):
            return
        floor = 1
        while True:
            team = self.spire_team(floor)
            boss = floor % 5 == 0
            self.header(f"Spire floor {floor}")
            ts.tv_print()
            ts.tv_print(ts.box([
                f"  Floor {floor}" + ("  --  BOSS" if boss else ""),
                "",
                f"  {len(team)} beasts, level {team[0][1]}"
                + (", all geared." if boss else "."),
                f"  Your best: floor {self.spire_best}.",
            ], fg="yellow" if boss else "amber"))
            ts.tv_print()
            ts.tv_pause("press enter to fight")
            beaten = True
            for slug, level, item in team:
                foe = Beast(slug, level)
                foe.item = item
                foe.hp = foe.max_hp
                result = self.battle(foe, wild=False, title=f"Spire {floor}", trainer="The Spire")
                if result != "won":
                    beaten = False
                    break
            if not beaten:
                self.heal_all()
                self.header("Battle Spire")
                ts.tv_print()
                ts.tv_print(ts.color(f"  The Spire spits you out on floor {floor}.", "bright_red"))
                ts.tv_print(f"  Best floor: {self.spire_best}.  Your team is patched up, free.")
                ts.tv_print()
                ts.tv_pause()
                self.store()
                return
            self.spire_best = max(self.spire_best, floor)
            rewards = self.spire_rewards(floor)
            self.store()
            while True:
                standing = len(self.healthy())
                self.header(f"Spire floor {floor} cleared")
                ts.tv_print()
                for r in rewards:
                    ts.tv_print(ts.color(f"  {r}", "bright_green"))
                ts.tv_print(f"  {standing}/{len(self.party)} standing.   Best floor: {self.spire_best}.")
                pick = ts.menu("What now?", [f"Climb to floor {floor + 1}", "Use an item",
                                             "Retreat"], back=None)
                if pick == 1:
                    self.use_item_menu()
                    continue
                break
            if pick == 2:
                return
            floor += 1

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
        ts.tv_print(ts.title("P O K E   A N D   M O N"))
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
    ts.tv_print(ts.title("P O K E   A N D   M O N"))
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
    ts.tv("Poke and Mon")
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
        ts.tv_print(ts.color("  P O K E   A N D   M O N", "bright_cyan", bold=True))
        ts.tv_print(ts.rule("─"))
        ts.tv_print()
        ts.tv_print("  Story Mode -- catch, raise and battle in the Hollow Vale.")
        ts.tv_print("  Tournament -- draft from every species. No catching needed.")
        ts.tv_print()
        pick = ts.menu("Poke and Mon", ["Story Mode", "Tournament"], back="Quit")
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
