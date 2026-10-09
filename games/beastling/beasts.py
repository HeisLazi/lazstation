"""All of Beastling's content. Edit here to redirect the game -- the rules
live in main.py, the world lives here.

Original creatures and world; the systems are genre-faithful, the content is
not borrowed from anyone.
"""

# ---------------------------------------------------------------- types
TYPES = ["Ember", "Tide", "Bloom", "Stone", "Spark", "Gloom"]

#: attacker -> {defender: multiplier}. Anything unlisted is 1.0.
#: Ember/Spark used to resist-and-be-resisted their way to the bottom of a
#: 1v1 round-robin (41-46% vs Stone 55-62%); Ember now also beats Gloom,
#: and Spark has fewer resisted matchups. Per-type win rates are now 45-53%.
CHART = {
    "Ember": {"Bloom": 2.0, "Gloom": 2.0, "Tide": 0.5, "Ember": 0.5},
    "Tide":  {"Ember": 2.0, "Stone": 2.0, "Bloom": 0.5, "Tide": 0.5},
    "Bloom": {"Tide": 2.0, "Stone": 2.0, "Ember": 0.5, "Spark": 0.5, "Bloom": 0.5},
    "Stone": {"Spark": 2.0, "Ember": 2.0, "Tide": 0.5, "Bloom": 0.5},
    "Spark": {"Tide": 2.0, "Spark": 0.5},
    "Gloom": {"Bloom": 2.0, "Spark": 2.0, "Ember": 0.5, "Stone": 0.5},
}

# ------------------------------------------------------------- abilities
# One passive per type (not per species) -- keeps the system honest about
# its own scope: six real hooks into combat, not twenty bespoke ones.
# Each is always-on and known (no hidden-ability bluffing here -- that
# needs per-species, not per-type, abilities to mean anything, which is
# real added scope, not this pass).
TYPE_ABILITY = {
    "Ember": "Tinder",
    "Tide": "Riptide",
    "Bloom": "Thick Hide",
    "Stone": "Unshaken",
    "Spark": "Static Charge",
    "Gloom": "Vengeful",
}

ABILITY_DESC = {
    "Tinder": "On a landed hit, a small chance to also burn the target.",
    "Riptide": "Never burns.",
    "Thick Hide": "Takes less damage from a super-effective hit.",
    "Unshaken": "Its own stats can't be lowered by a foe's move.",
    "Static Charge": "A small chance to paralyze whatever hits it.",
    "Vengeful": "Once per battle, at a quarter HP or less, its Atk rises.",
}

# --------------------------------------------------------------- synergy
# 2v2 only: a bonus for fielding a specific PAIR of types on the same
# side at once. Same restraint as abilities -- 3 named pairs out of the
# 15 possible, not exhaustive coverage. Keyed by a frozenset so side
# order doesn't matter; a pair not listed here gets no bonus, a real
# design choice (not every combo needs to be "build-around good") not
# an oversight.
#
# `desc` is kept to the short, in-battle-announcement phrasing on
# purpose, not a fuller sentence -- a reviewed regression, the exact
# same "verify the ACTUAL render path, not just that a string exists"
# bug class Mending Berry hit twice earlier this session: the first
# draft's fuller wording rendered fine in isolation but overflowed the
# battle log line once the "<Side>'s <Name> is active -- " prefix was
# counted, and only a live PTY run caught it. Checked against the real
# stage width (62 cols at 66x24) with that exact prefix, both sides,
# before landing on this wording.
TYPE_SYNERGY = {
    frozenset({"Ember", "Spark"}): {
        "name": "Wildfire Storm",
        "desc": "+15% damage.",
        "dmg_mult": 1.15,
    },
    frozenset({"Tide", "Bloom"}): {
        "name": "Rainforest Bond",
        "desc": "Heals 4% HP/turn.",
        "heal_pct": 0.04,
    },
    frozenset({"Stone", "Gloom"}): {
        "name": "Bedrock Ambush",
        "desc": "Much higher crits.",
        "crit_bonus": 0.20,
    },
}

# ---------------------------------------------------------------- moves
# name: dict(type, power, accuracy, desc, priority, effect, sets_weather)
#
# `priority`: +1 moves resolve before normal-priority moves regardless of
# speed -- a real answer to "the enemy is faster and about to finish me."
#
# `effect`: optional secondary effect, rolled independently of the accuracy
# check and only if the move actually hits. One of:
#   ("status", "burn"|"paralyze", chance)
#   ("stage", "atk"|"def"|"spd", delta, "self"|"foe", chance)
# Exactly one flagship move per type carries a stat-stage effect and Ember/
# Spark each get a dedicated status-inflicting move, so every type has a
# distinct non-damage identity without touching every move in the list.
#
# `sets_weather`: a field-wide effect, not a per-beast one -- unlike
# `effect`, this always triggers on a hit (no separate roll; missing the
# move already means no weather, same as a real Pokemon weather move).
# Deliberately only two moves carry this, on flagship-adjacent picks that
# otherwise had no secondary effect at all, rather than retrofitting it
# onto every move of the two types.
def _move(m_type, power, accuracy, desc, priority=0, effect=None, sets_weather=None):
    return dict(type=m_type, power=power, accuracy=accuracy, desc=desc,
                priority=priority, effect=effect, sets_weather=sets_weather)


#: field-wide, multi-turn, affects EVERY hit of the given move type on
#: either side -- not a per-beast effect. Exactly two states (not one per
#: type): real depth without a 6-way combinatorial mess to balance.
WEATHER_EFFECTS = {
    "Blaze": {"Ember": 1.2, "Tide": 0.8},
    "Downpour": {"Tide": 1.2, "Ember": 0.8},
}
WEATHER_DURATION = 5  # turns
WEATHER_DESC = {
    "Blaze": "Ember hits harder, Tide hits softer.",
    "Downpour": "Tide hits harder, Ember hits softer.",
}

# ------------------------------------------------------------------ items
# One optional item slot per beast -- unlike abilities (fixed by type),
# any beast can hold any item, so the choice is a real build decision:
# a single slot forces picking ONE of offense/defense/speed/insurance,
# not stacking all four. Four items, not more -- each a clearly distinct
# archetype rather than minor variations on the same idea.
ITEMS = {
    # `price` 0 = never sold, only found (rare drops / champion rewards).
    # `need` = badges before the shop stocks it. `desc` is kept to 30
    # chars or less: it has to fit the shop line ("name  price  desc"),
    # the equip menu AND the read-about panel at 66 columns.
    "Power Band": {"desc": "Deals 20% more damage.", "dmg_dealt": 1.20, "price": 300, "need": 0},
    "Guard Charm": {"desc": "Takes 20% less damage.", "dmg_taken": 0.80, "price": 300, "need": 0},
    "Quick Charm": {"desc": "30% faster.", "speed": 1.30, "price": 300, "need": 0},
    "Mending Berry": {"desc": "Heals 35% once at 25% HP.",
                      "heal_threshold": 0.25, "heal_amount": 0.35, "price": 250, "need": 0},
    "Focus Lens": {"desc": "6x critical-hit chance.", "crit_bonus": 0.32, "price": 450, "need": 1},
    "Vigor Seed": {"desc": "15% more max HP.", "hp_mult": 1.15, "price": 500, "need": 1},
    "Ember Sash": {"desc": "Ember moves hit 30% harder.", "type_boost": ("Ember", 1.30),
                  "price": 600, "need": 2},
    "Tide Sash": {"desc": "Tide moves hit 30% harder.", "type_boost": ("Tide", 1.30),
                  "price": 600, "need": 2},
    "Bloom Sash": {"desc": "Bloom moves hit 30% harder.", "type_boost": ("Bloom", 1.30),
                  "price": 600, "need": 2},
    "Stone Sash": {"desc": "Stone moves hit 30% harder.", "type_boost": ("Stone", 1.30),
                  "price": 600, "need": 2},
    "Spark Sash": {"desc": "Spark moves hit 18% harder.", "type_boost": ("Spark", 1.18),
                  "price": 600, "need": 2},
    "Gloom Sash": {"desc": "Gloom moves hit 15% harder.", "type_boost": ("Gloom", 1.15),
                  "price": 600, "need": 2},
    "Lifeleaf": {"desc": "Heals 10% HP each turn.", "regen": 0.10, "price": 0, "need": 0},
    "Thorn Wrap": {"desc": "Attackers lose 8% max HP.", "recoil": 0.08, "price": 0, "need": 0},
    "Last Stand": {"desc": "Survives a KO above 25% HP.", "survive": True, "price": 0, "need": 0},
    "Status Ward": {"desc": "Status-proof; takes 15% less.", "status_ward": True, "dmg_taken": 0.85, "price": 0, "need": 0},
}

#: Stackable, used from the bag (in battle: costs the turn; at camp: free).
SUPPLIES = {
    "Potion": {"desc": "Heals 40 HP.", "heal": 40, "price": 40, "need": 0},
    "Full Heal": {"desc": "Cures a status ailment.", "cure": True, "price": 80, "need": 0},
    "Super Potion": {"desc": "Heals 120 HP.", "heal": 120, "price": 120, "need": 1},
    "Revive": {"desc": "Revives a beast at half HP.", "revive": 0.5, "price": 300, "need": 1},
    "Growth Candy": {"desc": "Raises one beast a level.", "level": 1, "price": 1000, "need": 2},
    "Rare Scent": {"desc": "Rare beasts 5x likelier.", "scent": 15, "price": 500, "need": 2},
}

#: Training Hall: permanent stat points bought with coins, the game's big
#: coin sink. Per-point step, per-stat cap, and an escalating price.
TRAIN_STEP = {"hp": 4.0, "atk": 1.5, "dfn": 1.5, "spd": 1.5}
TRAIN_LABEL = {"hp": "HP", "atk": "Atk", "dfn": "Def", "spd": "Spd"}
TRAIN_CAP = 12     # points 9-12 are the 'mastery' tier, priced much higher


def train_price(points_in_stat: int, total_points: int) -> int:
    base = 150 + 60 * points_in_stat + 20 * total_points
    if points_in_stat >= 8:
        base += 400 + 200 * (points_in_stat - 8)       # mastery tier
    return base

#: Shop sections: (menu label, item names). Lures are handled separately.
SHOP_SECTIONS = [
    ("Medicine", ["Potion", "Full Heal", "Super Potion", "Revive", "Growth Candy", "Rare Scent"]),
    ("Battle gear", ["Power Band", "Guard Charm", "Quick Charm", "Mending Berry",
                     "Focus Lens", "Vigor Seed"]),
    ("Type sashes", [f"{t} Sash" for t in TYPES]),
]

#: Chance a won wild fight drops something, and what (weights). Rare
#: beasts always drop one of RARE_DROPS instead -- the only way to get
#: those besides a champion's reward, so a rare spawn is worth KOing, not
#: just catching.
DROP_CHANCE = 0.12
COMMON_DROPS = {"Potion": 30, "Full Heal": 18, "Super Potion": 14, "Revive": 6, "Growth Candy": 1,
                "Mending Berry": 3, "Power Band": 2, "Guard Charm": 2, "Quick Charm": 2,
                "Focus Lens": 2, "Vigor Seed": 2, **{f"{t} Sash": 1 for t in TYPES}}
RARE_DROPS = ["Lifeleaf", "Thorn Wrap", "Last Stand", "Status Ward"]

MOVES = {
    "Tackle":      _move("Stone", 35, 95, "a plain running hit"),
    "Scratch":     _move("Stone", 30, 100, "quick claws", priority=1),
    "Cinder Spit": _move("Ember", 40, 95, "a gob of hot ash",
                         effect=("status", "burn", 0.20)),
    "Flare Rush":  _move("Ember", 65, 85, "charges wreathed in flame",
                         sets_weather="Blaze"),
    "Magma Slam":  _move("Ember", 85, 75, "brings down molten weight",
                         effect=("stage", "def", -1, "foe", 0.30)),
    "Bubble":      _move("Tide", 38, 100, "a stream of stinging bubbles"),
    "Tide Pull":   _move("Tide", 62, 90, "drags the foe off balance",
                         sets_weather="Downpour"),
    "Deluge":      _move("Tide", 88, 75, "a wall of black water",
                         effect=("stage", "spd", -1, "foe", 0.30)),
    "Vine Whip":   _move("Bloom", 40, 95, "a quick lash"),
    "Seed Volley": _move("Bloom", 60, 90, "a spray of hard seeds",
                         effect=("status", "sleep", 0.12)),
    "Bramblewall": _move("Bloom", 85, 75, "thorns burst from the ground",
                         effect=("stage", "def", 1, "self", 0.30)),
    "Rock Toss":   _move("Stone", 45, 90, "hurls a loose stone"),
    "Cragfall":    _move("Stone", 70, 80, "drops a slab",
                         effect=("stage", "def", 1, "self", 0.30)),
    "Spark Nip":   _move("Spark", 42, 100, "a stinging jolt", priority=1),
    "Arc Bolt":    _move("Spark", 68, 85, "a leaping arc of current"),
    "Thunderhead": _move("Spark", 90, 70, "calls down the storm",
                         effect=("status", "paralyze", 0.30)),
    "Shadow Nip":  _move("Gloom", 40, 100, "a bite out of the dark", priority=1),
    "Duskwave":    _move("Gloom", 66, 88, "a rolling wave of shade",
                         effect=("status", "confused", 0.25)),
    "Night Terror":_move("Gloom", 92, 70, "the dark itself lunges",
                         effect=("stage", "atk", -1, "foe", 0.30)),
    "Flame Dash":  _move("Ember", 40, 100, "a streak of heat", priority=1),
    "Undertow":    _move("Tide", 55, 95, "drags the footing away",
                         effect=("stage", "atk", -1, "foe", 0.30)),
    "Spore Cloud": _move("Bloom", 42, 100, "a drifting numbness",
                         effect=("status", "paralyze", 0.30)),
    "Grit Storm":  _move("Stone", 62, 90, "a scouring wall of sand",
                         effect=("stage", "atk", -1, "foe", 0.25)),
    "Overcharge":  _move("Spark", 78, 80, "more than it can hold",
                         effect=("stage", "atk", 1, "self", 0.40)),
    "Hexing Gaze": _move("Gloom", 50, 95, "a look that finds the gap",
                         effect=("stage", "def", -1, "foe", 0.35)),
    # ---- Arena-only moves (Tournament). Power 0 = a support move: no damage,
    # the effect always lands if the move does. Story learnsets never include
    # these, so Story's battle() never meets a power-0 move.
    "Kindle":      _move("Ember", 0, 100, "builds heat, strikes faster",
                         effect=("multi", [("atk", 2, "self"), ("spd", 1, "self")], 1.0)),
    "Ebb":         _move("Tide", 0, 100, "pulls back and recovers",
                         effect=("heal", 0.40, 1.0)),
    "Soothe":      _move("Bloom", 0, 100, "mends, and clears the mind",
                         effect=("heal_cure", 0.35, 1.0)),
    "Brace":       _move("Stone", 0, 100, "digs in; nothing gets through",
                         priority=4, effect=("protect", 1.0)),
    "Jolt Web":    _move("Spark", 0, 90, "a net of static",
                         effect=("status", "paralyze", 1.0)),
    "Sap":         _move("Gloom", 0, 95, "drains the will to fight",
                         effect=("multi", [("atk", -1, "foe"), ("def", -1, "foe")], 1.0)),
    "Struggle":    _move("Stone", 40, 100, "a desperate lunge",
                         effect=("recoil", 0.25, 1.0)),
}

#: Arena (Tournament) kits are built from these, see arena.build_kit:
#: one off-type attack per type, so move choice is about the matchup, and
#: one support move per type, so there is something to do besides attack.
ARENA_COVERAGE = {"Ember": "Seed Volley", "Tide": "Flare Rush", "Bloom": "Cragfall",
                  "Stone": "Arc Bolt", "Spark": "Duskwave", "Gloom": "Tide Pull"}
ARENA_SUPPORT = {"Ember": "Kindle", "Tide": "Ebb", "Bloom": "Soothe",
                 "Stone": "Brace", "Spark": "Jolt Web", "Gloom": "Sap"}

# ---------------------------------------------------------------- species
# slug: dict(name, type, base stats, learnset [(level, move), ...],
#            evolves_at/into, glyph, flavour)
# The learnset is a LIST of pairs, not a dict: two moves can share a level,
# and a dict would silently keep only the last of them.
SPECIES = {
    "cindermole": dict(
        name="Cindermole", type="Ember", hp=42, atk=13, dfn=10, spd=11, glyph="▄●▄",
        learn=[(1, "Scratch"), (1, "Cinder Spit"), (9, "Flare Rush"), (18, "Magma Slam")],
        evolve=(16, "magmaburrow"),
        flavour="Digs through warm ash. Its claws are always faintly glowing."),
    "magmaburrow": dict(
        name="Magmaburrow", type="Ember", hp=68, atk=21, dfn=17, spd=14, glyph="▟█▙",
        learn=[(1, "Flare Rush"), (20, "Magma Slam")], evolve=None,
        flavour="Tunnels collapse behind it, sealed by the heat of its passing."),
    "wickling": dict(
        name="Wickling", type="Ember", hp=38, atk=15, dfn=8, spd=14, glyph="╹◉╹",
        learn=[(1, "Cinder Spit"), (9, "Flare Rush")], evolve=(18, "pyrelisk"),
        flavour="A small flame that learned to walk. It never sleeps in the rain."),
    "pyrelisk": dict(
        name="Pyrelisk", type="Ember", hp=62, atk=24, dfn=13, spd=20, glyph="◤◉◢",
        learn=[(1, "Flare Rush"), (24, "Magma Slam")], evolve=None,
        flavour="Its stare dries the air. Grass browns where it has been sitting."),
    "tadpearl": dict(
        name="Tadpearl", type="Tide", hp=45, atk=11, dfn=12, spd=10, glyph="◖◉◗",
        learn=[(1, "Tackle"), (1, "Bubble"), (10, "Tide Pull"), (19, "Deluge")],
        evolve=(16, "brinemaw"),
        flavour="Carries a single pale bead in its belly. Nobody knows what for."),
    "brinemaw": dict(
        name="Brinemaw", type="Tide", hp=72, atk=19, dfn=19, spd=12, glyph="╣◉╠",
        learn=[(1, "Tide Pull"), (22, "Deluge")], evolve=None,
        flavour="Swallows the tide and gives it back harder."),
    "mistfin": dict(
        name="Mistfin", type="Tide", hp=40, atk=14, dfn=10, spd=16, glyph="≈◉≈",
        learn=[(1, "Bubble"), (12, "Tide Pull")], evolve=(19, "haarscale"),
        flavour="Seen only in fog. Fishermen say it leads boats home, or doesn't."),
    "haarscale": dict(
        name="Haarscale", type="Tide", hp=66, atk=22, dfn=16, spd=21, glyph="≋◉≋",
        learn=[(1, "Tide Pull"), (26, "Deluge")], evolve=None,
        flavour="Moves through sea fog as if the fog were water."),
    "sproutling": dict(
        name="Sproutling", type="Bloom", hp=44, atk=12, dfn=13, spd=9, glyph="⋎◉⋎",
        learn=[(1, "Tackle"), (1, "Vine Whip"), (10, "Seed Volley"), (19, "Bramblewall")],
        evolve=(16, "thornwood"),
        flavour="Roots itself when it sleeps. Uproot one gently or not at all."),
    "thornwood": dict(
        name="Thornwood", type="Bloom", hp=74, atk=20, dfn=20, spd=10, glyph="╫◉╫",
        learn=[(1, "Seed Volley"), (22, "Bramblewall")], evolve=None,
        flavour="Older ones are mistaken for dead trees until they move."),
    "pollenpuff": dict(
        name="Pollenpuff", type="Bloom", hp=41, atk=13, dfn=11, spd=15, glyph="✿◉✿",
        learn=[(1, "Vine Whip"), (13, "Seed Volley")], evolve=(20, "bloomcrest"),
        flavour="Drifts on its own cloud of spores. Sneezing is contagious near it."),
    "bloomcrest": dict(
        name="Bloomcrest", type="Bloom", hp=64, atk=21, dfn=17, spd=19, glyph="❀◉❀",
        learn=[(1, "Seed Volley"), (27, "Bramblewall")], evolve=None,
        flavour="Opens fully once a year. People travel a long way to see it."),
    "pebbleton": dict(
        name="Pebbleton", type="Stone", hp=48, atk=13, dfn=17, spd=7, glyph="▖◉▗",
        learn=[(1, "Tackle"), (1, "Rock Toss"), (12, "Cragfall")], evolve=(17, "cragjaw"),
        flavour="Sits still so long that moss claims it. It does not seem to mind."),
    "cragjaw": dict(
        name="Cragjaw", type="Stone", hp=78, atk=22, dfn=26, spd=8, glyph="▙█▟",
        learn=[(1, "Cragfall")], evolve=None,
        flavour="Bites through rock to get at the wet moss beneath."),
    "zapkit": dict(
        name="Zapkit", type="Spark", hp=39, atk=14, dfn=9, spd=18, glyph="⌁◉⌁",
        learn=[(1, "Scratch"), (1, "Spark Nip"), (11, "Arc Bolt"), (21, "Thunderhead")],
        evolve=(18, "voltlynx"),
        flavour="Its fur stands up before a storm, which is how the valley forecasts."),
    "voltlynx": dict(
        name="Voltlynx", type="Spark", hp=61, atk=23, dfn=14, spd=26, glyph="⟨◉⟩",
        learn=[(1, "Arc Bolt"), (25, "Thunderhead")], evolve=None,
        flavour="Runs the ridgeline during storms, racing the lightning and winning."),
    "dimwisp": dict(
        name="Dimwisp", type="Gloom", hp=40, atk=14, dfn=10, spd=15, glyph="◌◉◌",
        learn=[(1, "Shadow Nip"), (12, "Duskwave")], evolve=(19, "nightveil"),
        flavour="Puts out candles to be polite. It thinks it is being polite."),
    "nightveil": dict(
        name="Nightveil", type="Gloom", hp=65, atk=23, dfn=16, spd=20, glyph="◍◉◍",
        learn=[(1, "Duskwave"), (28, "Night Terror")], evolve=None,
        flavour="Where it passes, the evening arrives an hour early."),
    "shadecub": dict(
        name="Shadecub", type="Gloom", hp=46, atk=15, dfn=12, spd=13, glyph="◣◉◢",
        learn=[(1, "Scratch"), (1, "Shadow Nip"), (14, "Duskwave")], evolve=(22, "umbrafang"),
        flavour="Plays in the dark like any cub. It is still a cub."),
    "umbrafang": dict(
        name="Umbrafang", type="Gloom", hp=80, atk=26, dfn=19, spd=18, glyph="◤▓◥",
        learn=[(1, "Duskwave"), (30, "Night Terror")], evolve=None,
        flavour="The old stories give it three shadows and no reflection."),
    "ashfinch": dict(
        name="Ashfinch", type="Ember", hp=36, atk=14, dfn=8, spd=18, glyph="^◉^",
        learn=[(1, 'Flame Dash'), (1, 'Cinder Spit'), (10, 'Flare Rush')], evolve=(17, 'emberhawk'),
        flavour="Nests in cooling hearths. It darts out before the smoke clears."),
    "emberhawk": dict(
        name="Emberhawk", type="Ember", hp=58, atk=24, dfn=12, spd=25, glyph="◣▲◢",
        learn=[(1, 'Flame Dash'), (1, 'Flare Rush'), (26, 'Magma Slam')], evolve=None,
        flavour="Rides the heat above a gully and drops on whatever moves."),
    "pearlclam": dict(
        name="Pearlclam", type="Tide", hp=48, atk=11, dfn=17, spd=7, glyph="(◉)",
        learn=[(1, 'Bubble'), (1, 'Undertow'), (14, 'Tide Pull')], evolve=(18, 'moatshell'),
        flavour="Shuts like a vault. What it keeps inside is its own business."),
    "moatshell": dict(
        name="Moatshell", type="Tide", hp=80, atk=17, dfn=28, spd=8, glyph="[▓▓]",
        learn=[(1, 'Undertow'), (1, 'Tide Pull'), (27, 'Deluge')], evolve=None,
        flavour="Old ones carry a whole tidepool on their backs, fish included."),
    "spindlebud": dict(
        name="Spindlebud", type="Bloom", hp=38, atk=11, dfn=11, spd=16, glyph="⋎◦⋎",
        learn=[(1, 'Vine Whip'), (1, 'Spore Cloud'), (12, 'Seed Volley')], evolve=(17, 'orchidreign'),
        flavour="Thin as a stem and just as quiet. Its pollen makes limbs forget."),
    "orchidreign": dict(
        name="Orchidreign", type="Bloom", hp=60, atk=19, dfn=15, spd=25, glyph="❀◉❀",
        learn=[(1, 'Spore Cloud'), (1, 'Seed Volley'), (25, 'Bramblewall')], evolve=None,
        flavour="A court of petals around one very patient face."),
    "gritmouse": dict(
        name="Gritmouse", type="Stone", hp=44, atk=13, dfn=14, spd=12, glyph="◖▪◗",
        learn=[(1, 'Rock Toss'), (8, 'Grit Storm'), (13, 'Cragfall')], evolve=(18, 'quarrywyrm'),
        flavour="Eats gravel and sneezes dust. Hard to hit, easy to underestimate."),
    "quarrywyrm": dict(
        name="Quarrywyrm", type="Stone", hp=76, atk=24, dfn=24, spd=12, glyph="▟▓▓▙",
        learn=[(1, 'Grit Storm'), (1, 'Cragfall'), (28, 'Rock Toss')], evolve=None,
        flavour="Bores through a cliff and leaves a road behind it."),
    "fizzwing": dict(
        name="Fizzwing", type="Spark", hp=36, atk=13, dfn=8, spd=20, glyph="⌁◉⌁",
        learn=[(1, 'Spark Nip'), (10, 'Arc Bolt'), (15, 'Overcharge')], evolve=(17, 'thunderwing'),
        flavour="Flickers between lamps at dusk. Lights go out where it lands."),
    "thunderwing": dict(
        name="Thunderwing", type="Spark", hp=58, atk=22, dfn=12, spd=28, glyph="⟪▲⟫",
        learn=[(1, 'Arc Bolt'), (1, 'Overcharge'), (28, 'Thunderhead')], evolve=None,
        flavour="Its wingbeat is a low crack of thunder. Storm fronts follow it."),
    "murkling": dict(
        name="Murkling", type="Gloom", hp=42, atk=13, dfn=11, spd=13, glyph="◌▾◌",
        learn=[(1, 'Shadow Nip'), (1, 'Hexing Gaze'), (14, 'Duskwave')], evolve=(20, 'hollowmaw'),
        flavour="Pools in the corners of rooms. It is always slightly closer."),
    "hollowmaw": dict(
        name="Hollowmaw", type="Gloom", hp=70, atk=24, dfn=18, spd=17, glyph="◥◉◤",
        learn=[(1, 'Hexing Gaze'), (1, 'Duskwave'), (29, 'Night Terror')], evolve=None,
        flavour="Mostly mouth. What it swallows is not seen again, or heard."),
    "flintnose": dict(
        name="Flintnose", type="Stone", hp=46, atk=14, dfn=15, spd=10, glyph="◖◆◗",
        learn=[(1, 'Tackle'), (1, 'Rock Toss'), (13, 'Grit Storm')], evolve=(19, 'cairnhorn'),
        flavour="Strikes sparks off every rock it sniffs. Camps hate it."),
    "cairnhorn": dict(
        name="Cairnhorn", type="Stone", hp=74, atk=23, dfn=22, spd=11, glyph="▲▓▲",
        learn=[(1, 'Grit Storm'), (1, 'Cragfall'), (30, 'Rock Toss')], evolve=None,
        flavour="Stacks stones on its own back. The cairns on the ridge may be its doing."),
    "sparkmoth": dict(
        name="Sparkmoth", type="Spark", hp=34, atk=12, dfn=8, spd=22, glyph="∗◉∗",
        learn=[(1, 'Spark Nip'), (1, 'Scratch'), (12, 'Arc Bolt')], evolve=(18, 'lumenmoth'),
        flavour="Drawn to anything bright, including the thing that will hit it."),
    "lumenmoth": dict(
        name="Lumenmoth", type="Spark", hp=56, atk=22, dfn=12, spd=30, glyph="∗▲∗",
        learn=[(1, 'Arc Bolt'), (1, 'Overcharge'), (27, 'Thunderhead')], evolve=None,
        flavour="Glows brighter the angrier it gets. Do not make it angry."),
}

STARTERS = ["cindermole", "tadpearl", "sproutling"]

# ---------------------------------------------------------------- the world
# Routes unlock in order. `need` is how many champions you must have beaten.
#: Per-route spawn weights. A slug missing from `weights` counts as 10
#: ("common"); 3-8 are uncommon; 1 is RARE (one per route, about 2%) and gets announced.
RARE_WEIGHT = 1
ROUTES = [
    dict(name="Meadow Path", need=0, levels=(2, 5), tall="long grass",
         wild=["sproutling", "pebbleton", "zapkit", "tadpearl", "cindermole",
               "spindlebud", "ashfinch", "gritmouse", "sparkmoth"],
         weights={"spindlebud": 6, "ashfinch": 6, "gritmouse": 4, "sparkmoth": 1},
         blurb="Warm, ordinary, full of small things that have never seen a trainer."),
    dict(name="Ember Gully", need=1, levels=(6, 10), tall="hot scree",
         wild=["wickling", "cindermole", "pebbleton", "magmaburrow",
               "ashfinch", "flintnose", "emberhawk"],
         weights={"magmaburrow": 4, "ashfinch": 8, "flintnose": 6, "pebbleton": 8, "emberhawk": 1},
         blurb="The stones tick as they cool. Something down there is not cooling."),
    dict(name="Tidal Flats", need=1, levels=(7, 12), tall="shallows",
         wild=["mistfin", "tadpearl", "pollenpuff", "brinemaw",
               "pearlclam", "moatshell", "spindlebud", "bloomcrest"],
         weights={"pollenpuff": 8, "brinemaw": 4, "pearlclam": 8, "moatshell": 3, "spindlebud": 6, "bloomcrest": 1},
         blurb="Twice a day the sea leaves, and twice a day it remembers."),
    dict(name="Stonewatch Ridge", need=2, levels=(11, 16), tall="scrub",
         wild=["pebbleton", "cragjaw", "zapkit", "thornwood",
               "gritmouse", "flintnose", "quarrywyrm", "cairnhorn"],
         weights={"pebbleton": 8, "cragjaw": 4, "zapkit": 8, "thornwood": 4, "gritmouse": 8, "flintnose": 8, "quarrywyrm": 3, "cairnhorn": 1},
         blurb="Cairns all along the path. Nobody will say who built them."),
    dict(name="Storm Mesa", need=3, levels=(15, 21), tall="wind-flattened grass",
         wild=["zapkit", "voltlynx", "haarscale", "pyrelisk",
               "fizzwing", "sparkmoth", "thunderwing", "lumenmoth", "emberhawk"],
         weights={"zapkit": 8, "voltlynx": 4, "haarscale": 4, "pyrelisk": 4, "fizzwing": 10, "sparkmoth": 8, "thunderwing": 3, "lumenmoth": 1, "emberhawk": 3},
         blurb="The air tastes of metal. Your hair will not lie flat up here."),
    dict(name="Gloomwood", need=4, levels=(19, 26), tall="black fern",
         wild=["dimwisp", "shadecub", "nightveil", "umbrafang", "thornwood",
               "murkling", "hollowmaw", "orchidreign", "spindlebud"],
         weights={"dimwisp": 8, "shadecub": 8, "nightveil": 4, "umbrafang": 3, "thornwood": 4, "murkling": 8, "hollowmaw": 3, "orchidreign": 1, "spindlebud": 5},
         blurb="The trees are close together and the light gives up early."),
]

#: Beat these in order. Each is a small team, hardest last.
CHAMPIONS = [
    dict(name="Wren the Gardener", type="Bloom", blurb="Keeps the meadow. Fights like it.",
         team=[("spindlebud", 8), ("pollenpuff", 9)],
         win="\"You listened to them,\" she says. \"Most people talk.\""),
    dict(name="Ash of the Gully", type="Ember", blurb="Smells of woodsmoke and does not blink.",
         team=[("ashfinch", 12), ("wickling", 13), ("magmaburrow", 15)],
         win="\"Good. Bank the fire and move on.\""),
    dict(name="Maren Tidewatch", type="Tide", blurb="Counts the tides out loud while she battles.",
         team=[("mistfin", 17), ("pearlclam", 18), ("brinemaw", 19)],
         win="\"Six hours out, six hours back. You were quicker.\""),
    dict(name="Bhodi Stonewatch", type="Stone", blurb="Built like the cairns he guards.",
         team=[("flintnose", 21), ("gritmouse", 21), ("quarrywyrm", 24)],
         win="He nods once, which from him is a parade."),
    dict(name="Sable", type="Gloom", blurb="You are fairly sure she was not there a moment ago.",
         team=[("murkling", 27), ("nightveil", 28), ("shadecub", 28), ("hollowmaw", 31)],
         win="\"The wood lets you leave,\" she says. \"That's rarer than winning.\""),
]

#: Held gear per champion beast (same order as `team`): the aces carry
#: shop-grade items, so beating them is no longer a pure level check.
CHAMPION_GEAR = [
    [None, "Mending Berry"],
    ["Quick Charm", None, "Power Band"],
    [None, "Mending Berry", "Guard Charm"],
    [None, "Mending Berry", "Guard Charm"],
    [None, "Focus Lens", None, "Power Band"],
]
for _champ, _gear in zip(CHAMPIONS, CHAMPION_GEAR):
    _champ["gear"] = _gear
for _champ, _reward in zip(CHAMPIONS, [("Lifeleaf", 1), ("Thorn Wrap", 1), ("Status Ward", 1),
                                        ("Last Stand", 1), ("Growth Candy", 3)]):
    _champ["reward"] = _reward


# ------------------------------------------------------------ post-game
#: Rematch teams: the champion returns with a full, geared team. Entries
#: are (species, held item). Levels are not stored here -- they scale with
#: your own best six (see Game.rematch_level), so a rematch stays a fight.
REMATCH = {
    "Wren the Gardener": [("orchidreign", "Lifeleaf"), ("thornwood", "Guard Charm"),
                          ("bloomcrest", "Power Band"), ("pyrelisk", "Quick Charm"),
                          ("moatshell", None)],
    "Ash of the Gully": [("emberhawk", "Quick Charm"), ("magmaburrow", "Power Band"),
                         ("pyrelisk", "Ember Sash"), ("cragjaw", "Thorn Wrap"),
                         ("nightveil", None)],
    "Maren Tidewatch": [("moatshell", "Guard Charm"), ("brinemaw", "Vigor Seed"),
                        ("haarscale", "Tide Sash"), ("voltlynx", "Focus Lens"),
                        ("thornwood", None)],
    "Bhodi Stonewatch": [("quarrywyrm", "Last Stand"), ("cragjaw", "Guard Charm"),
                         ("cairnhorn", "Thorn Wrap"), ("brinemaw", "Power Band"),
                         ("pyrelisk", None)],
    "Sable": [("hollowmaw", "Last Stand"), ("umbrafang", "Power Band"),
              ("nightveil", "Gloom Sash"), ("pyrelisk", "Status Ward"),
              ("voltlynx", "Focus Lens"), ("cragjaw", "Lifeleaf")],
}
REMATCH_COINS = 500          # + 150 per previous win over that champion
SPIRE_START_LEVEL = 40       # floor 1 is level 42; +2 per floor
