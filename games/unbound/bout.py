"""One fight. Telegraphed strikes, a location on every one of them.

Reuses the one idea that already worked today (Hollow): a fighter committed
to a strike is a fighter who is open -- close in and hit them first and their
strike never lands. Applied here to a fighter's whole body instead of a
single HP bar, with the outcome (KO) and the injury ledger (Fighter.taken,
Fighter.ledger) tracked completely separately, per the owner's correction.
"""
import random

from fighter import LOCATIONS

#: (target location, range as (min,max) gap tiles, base power, punish bonus)
ATTACKS = {
    "kick": dict(loc="leg",  rng=(1, 3), power=6, punish=1.3),
    "body": dict(loc="ribs", rng=(1, 2), power=7, punish=1.3),
    "arm":  dict(loc="arm",  rng=(1, 2), power=5, punish=1.2),
    "head": dict(loc="head", rng=(1, 1), power=9, punish=1.5),
}
BLOCKS = {"block_leg": "leg", "block_ribs": "ribs", "block_arm": "arm", "block_head": "head"}
RING_W = 9


class Bout:
    def __init__(self, a, b, rng=None, round_cap=None):
        self.a, self.b = a, b
        a.pos, b.pos = 1, RING_W - 2
        self.rng = rng or random.Random()
        self.round = 0
        self.round_cap = round_cap    # None = fight to a stoppage only
        self.log = []
        self.over = None          # None | fighter who WON | "draw"
        self.by_decision = False

    def gap(self):
        return abs(self.a.pos - self.b.pos) - 1

    def _say(self, text):
        self.log.append(text)
        del self.log[:-30]

    # ---------------------------------------------------------------- turn
    def step(self, action_a, action_b):
        """One round. Both fighters act; both may be mid-strike already.

        A real bug lived here: the pass that resolves a fighter's IN-FLIGHT
        strike was handed that same fighter's own action for this round,
        instead of the opponent's -- which is the one thing that actually
        determines whether a block or dodge lands. It went uncaught by the
        Stage 0 proof because the punish path happened to clear `pending`
        before the buggy branch ran in every test that exercised it. Fixed
        by resolving each fighter's pending strike against the OPPONENT's
        action explicitly, never its own.
        """
        self.round += 1
        self._move(self.a, action_a, self.b)
        self._move(self.b, action_b, self.a)

        punished = set()
        if self._maybe_punish(self.a, action_a, self.b):
            punished.add(self.a)
        if self._maybe_punish(self.b, action_b, self.a):
            punished.add(self.b)

        if self.a not in punished:
            self._advance(self.a, self.b, action_a, action_b)
        if self.b not in punished:
            self._advance(self.b, self.a, action_b, action_a)
        if self.a.down or self.b.down:
            if self.a.down and self.b.down:
                self.over = "draw"
            else:
                self.over = self.b if self.a.down else self.a
        elif self.round_cap and self.round >= self.round_cap:
            # No stoppage -- a fight can also be won on points. This is the
            # UFC case in full: the "winner" is whoever landed more, which is
            # offense, not defense. It says nothing about who absorbed more.
            self.by_decision = True
            # Scored on activity -- strikes that connected -- not on raw
            # power exchanged. Power dealt and power absorbed are the same
            # number from opposite sides of one trade; scoring on power would
            # make "won" and "took less" mathematically the same claim. A
            # judges' scorecard rewards output, which is a different axis.
            if self.a.strikes > self.b.strikes:
                self.over = self.a
            elif self.b.strikes > self.a.strikes:
                self.over = self.b
            else:
                self.over = "draw"
        return self.log[-4:]

    def _move(self, f, act, foe):
        if act not in ("advance", "retreat"):
            return
        rng = max(1, f.move_range())
        away = -1 if f.pos < foe.pos else 1     # direction that increases gap
        step = -away if act == "advance" else away
        f.pos = max(0, min(RING_W - 1, f.pos + step * rng))

    def _maybe_punish(self, f, act, foe):
        """The whole idea: hit someone mid-windup and their strike dies."""
        if act not in ATTACKS or foe.pending is None:
            return False
        spec = ATTACKS[act]
        if self.gap() > spec["rng"][1]:
            return False                         # out of range even for a punish
        power = f.strike_power(spec["power"]) * spec["punish"]
        foe.hurt(spec["loc"], power)
        f.landed += power
        f.strikes += 1
        self._say(f"{f.name} catches {foe.name} mid-motion -- the {foe.pending['loc']} never lands.")
        foe.pending = None
        return True

    def _advance(self, f, foe, f_act, foe_act):
        """f may commit a new strike (reads f_act) or have one resolve now
        (reads foe_act -- the DEFENDER's choice, which is what a block or a
        dodge actually is)."""
        if f.pending is not None:
            f.pending["turns"] -= 1
            if f.pending["turns"] <= 0:
                self._resolve_strike(f, foe, foe_act)
            return
        if f_act in ATTACKS and foe.pending is None:
            spec = ATTACKS[f_act]
            lo, hi = spec["rng"]
            if lo <= self.gap() <= hi:
                f.pending = dict(loc=spec["loc"], power=spec["power"], turns=1, kind=f_act)

    def _resolve_strike(self, f, foe, foe_act):
        spec = ATTACKS[f.pending["kind"]]
        loc, power = spec["loc"], f.strike_power(spec["power"])
        f.pending = None
        lo, hi = spec["rng"]
        if not (lo <= self.gap() <= hi):
            self._say(f"{f.name}'s strike finds only air. {foe.name} isn't there anymore.")
            return
        if foe_act == "dodge":
            chance = foe.read_chance() - 0.10 * (1 if loc == "head" else 0)
            if self.rng.random() < chance:
                self._say(f"{foe.name} reads it and isn't there.")
                return
            foe.hurt(loc, power)
            f.landed += power
            f.strikes += 1
            self._say(f"{foe.name} guesses wrong -- it lands clean on the {loc}.")
            return
        if BLOCKS.get(foe_act) == loc:
            mit = foe.guard_value() * (0.55 + 0.35 * foe.block_skill)
            chip = power * (1 - mit)
            foe.hurt(loc, chip)
            f.landed += chip
            f.strikes += 1
            self._say(f"{foe.name} takes it on the guard -- {loc} absorbs the rest.")
            return
        foe.hurt(loc, power)
        f.landed += power
        f.strikes += 1
        self._say(f"{foe.name} eats it clean on the {loc}.")
