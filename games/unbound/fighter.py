"""A fighter's body, not just a health bar.

The owner's correction, made concrete: injury is not "what happens when you
lose." It is a running ledger of every shot that landed, how hard, and where
-- built up over a fight regardless of who wins it. A dominant win usually
means a light ledger because a dominant fighter isn't getting hit much; that
is a consequence of the fight, never a rule about the result.

LOCATIONS: leg, ribs, arm, head. Each takes its own damage and its own
condition penalty -- a hurt leg costs you range, not power; a hurt head costs
you reads, not reach.
"""

LOCATIONS = ("leg", "ribs", "arm", "head")

#: total power absorbed at a location before it crosses into the next state.
#: (light bound, moderate bound) -- past moderate is severe.
THRESHOLDS = {"leg": (10, 22), "ribs": (12, 26), "arm": (10, 20), "head": (8, 16)}


def condition(total, loc):
    lo, hi = THRESHOLDS[loc]
    if total >= hi:
        return "severe"
    if total >= lo:
        return "moderate"
    if total > 0:
        return "light"
    return "clean"


class Fighter:
    def __init__(self, name, hp=40, stamina=10, power=6, read=0.62, block=0):
        self.name = name
        self.hp = self.max_hp = hp
        self.stamina = self.max_stamina = stamina
        self.base_power = power
        self.base_read = read          # chance to correctly read a telegraph
        self.block_skill = block       # chance a matched block stops it clean

        self.ledger = {loc: 0 for loc in LOCATIONS}   # power absorbed, ever
        self.pending = None             # {"loc", "power", "turns"} -- a committed strike
        self.pos = 0
        self.landed = 0                 # total power you dealt, this fight
        self.strikes = 0                # count of strikes that connected --
                                         # this is what a decision scores, not
                                         # power, because power dealt and power
                                         # absorbed are the same number seen
                                         # from opposite sides of one exchange
        self.taken = 0                  # total power you absorbed, this fight

        self.down = False

    # ------------------------------------------------------------ ledger
    def hurt(self, loc, power):
        self.ledger[loc] += power
        self.taken += power
        self.hp -= power
        if self.hp <= 0:
            self.hp = 0
            self.down = True

    def cond(self, loc):
        return condition(self.ledger[loc], loc)

    # -------------------------------------------------- what injury costs
    def move_range(self):
        """A hurt leg is the one location that changes tactics, not just power."""
        c = self.cond("leg")
        return {"clean": 2, "light": 2, "moderate": 1, "severe": 0}[c]

    def read_chance(self):
        """A hurt head costs you the fight's whole skill: seeing it coming."""
        c = self.cond("head")
        penalty = {"clean": 0.0, "light": 0.08, "moderate": 0.22, "severe": 0.40}[c]
        return max(0.05, self.base_read - penalty)

    def strike_power(self, base):
        """A hurt arm costs you output, whichever arm is throwing."""
        c = self.cond("arm")
        mult = {"clean": 1.0, "light": 0.92, "moderate": 0.78, "severe": 0.55}[c]
        return base * mult

    def guard_value(self):
        """Hurt ribs cost you your guard -- blocks stop less of what lands."""
        c = self.cond("ribs")
        return {"clean": 1.0, "light": 0.9, "moderate": 0.72, "severe": 0.5}[c]

    def stamina_cost(self, base):
        c = self.cond("ribs")
        mult = {"clean": 1.0, "light": 1.1, "moderate": 1.3, "severe": 1.6}[c]
        return base * mult

    def worst_location(self):
        return max(LOCATIONS, key=lambda l: self.ledger[l])

    # ------------------------------------------------------ between fights
    def reset_for_bout(self):
        """A new fight. Your stamina and footing reset -- your body doesn't.

        HP represents what you can absorb in THIS bout before going down; it
        is not a running life total, so it resets. The ledger is the actual
        injury and is the one thing this does NOT touch -- that persistence
        is the entire point of the system.
        """
        self.hp = self.max_hp
        self.stamina = self.max_stamina
        self.pending = None
        self.landed = 0
        self.taken = 0
        self.strikes = 0
        self.down = False

    def rest(self, days=1):
        """Time off heals, slowly, and unevenly -- a bad break lingers."""
        for loc in LOCATIONS:
            heal_rate = 3 if condition(self.ledger[loc], loc) == "light" else 2
            self.ledger[loc] = max(0, self.ledger[loc] - heal_rate * days)

    def fight_hurt_wear(self):
        """Fighting hurt doesn't heal you -- old wounds take fresh damage
        worse than clean tissue does, which is handled naturally by hurt()
        already stacking onto whatever total is already there. This exists
        only as a documented hook for the ladder stage: sitting out heals,
        fighting doesn't, and that asymmetry is the whole decision."""
        return None

    def hurt_summary(self):
        bad = [(l, condition(self.ledger[l], l)) for l in LOCATIONS
               if self.ledger[l] > 0]
        return bad
