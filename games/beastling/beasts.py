"""All of Beastling's content. Edit here to redirect the game -- the rules
live in main.py, the world lives here.

Original creatures and world; the systems are genre-faithful, the content is
not borrowed from anyone.
"""

# ---------------------------------------------------------------- types
TYPES = ["Ember", "Tide", "Bloom", "Stone", "Spark", "Gloom"]

#: attacker -> {defender: multiplier}. Anything unlisted is 1.0.
CHART = {
    "Ember": {"Bloom": 2.0, "Tide": 0.5, "Stone": 0.5, "Ember": 0.5},
    "Tide":  {"Ember": 2.0, "Stone": 2.0, "Bloom": 0.5, "Tide": 0.5},
    "Bloom": {"Tide": 2.0, "Stone": 2.0, "Ember": 0.5, "Spark": 0.5, "Bloom": 0.5},
    "Stone": {"Spark": 2.0, "Ember": 2.0, "Tide": 0.5, "Bloom": 0.5},
    "Spark": {"Tide": 2.0, "Bloom": 0.5, "Stone": 0.5, "Spark": 0.5},
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
    "Power Band": {"desc": "Deals 20% more damage.", "dmg_dealt": 1.20},
    "Guard Charm": {"desc": "Takes 20% less damage.", "dmg_taken": 0.80},
    "Quick Charm": {"desc": "20% faster.", "speed": 1.20},
    # Kept short -- a reviewed regression, twice over: the original wording
    # (83 chars) overflowed the read-about panel's ts.box() at the game's
    # declared minimum terminal size, and a since-shortened 54-char version
    # still overflowed equip_menu()'s OWN listing (a separate tv_print/_clip
    # render path with a tighter budget than the box -- "   [N] <name>  -- "
    # eats space too). Verified headlessly against the real stage width (62
    # cols at 66x24) in both render paths before landing on this wording.
    "Mending Berry": {"desc": "Heals 20% once, at 25% HP or less.",
                       "heal_threshold": 0.25, "heal_amount": 0.20},
}

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
    "Seed Volley": _move("Bloom", 60, 90, "a spray of hard seeds"),
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
    "Duskwave":    _move("Gloom", 66, 88, "a rolling wave of shade"),
    "Night Terror":_move("Gloom", 92, 70, "the dark itself lunges",
                         effect=("stage", "atk", -1, "foe", 0.30)),
}

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
        learn=[(1, "Cinder Spit"), (11, "Flare Rush")], evolve=(18, "pyrelisk"),
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
}

STARTERS = ["cindermole", "tadpearl", "sproutling"]

# ---------------------------------------------------------------- the world
# Routes unlock in order. `need` is how many champions you must have beaten.
ROUTES = [
    dict(name="Meadow Path", need=0, levels=(2, 5), tall="long grass",
         wild=["sproutling", "pebbleton", "zapkit", "tadpearl", "cindermole"],
         blurb="Warm, ordinary, full of small things that have never seen a trainer."),
    dict(name="Ember Gully", need=1, levels=(6, 10), tall="hot scree",
         wild=["wickling", "cindermole", "pebbleton", "magmaburrow"],
         blurb="The stones tick as they cool. Something down there is not cooling."),
    dict(name="Tidal Flats", need=1, levels=(7, 12), tall="shallows",
         wild=["mistfin", "tadpearl", "pollenpuff", "brinemaw"],
         blurb="Twice a day the sea leaves, and twice a day it remembers."),
    dict(name="Stonewatch Ridge", need=2, levels=(11, 16), tall="scrub",
         wild=["pebbleton", "cragjaw", "zapkit", "thornwood"],
         blurb="Cairns all along the path. Nobody will say who built them."),
    dict(name="Storm Mesa", need=3, levels=(15, 21), tall="wind-flattened grass",
         wild=["zapkit", "voltlynx", "haarscale", "pyrelisk"],
         blurb="The air tastes of metal. Your hair will not lie flat up here."),
    dict(name="Gloomwood", need=4, levels=(19, 26), tall="black fern",
         wild=["dimwisp", "shadecub", "nightveil", "umbrafang", "thornwood"],
         blurb="The trees are close together and the light gives up early."),
]

#: Beat these in order. Each is a small team, hardest last.
CHAMPIONS = [
    dict(name="Wren the Gardener", type="Bloom", blurb="Keeps the meadow. Fights like it.",
         team=[("sproutling", 7), ("pollenpuff", 8)],
         win="\"You listened to them,\" she says. \"Most people talk.\""),
    dict(name="Ash of the Gully", type="Ember", blurb="Smells of woodsmoke and does not blink.",
         team=[("wickling", 11), ("cindermole", 11), ("magmaburrow", 13)],
         win="\"Good. Bank the fire and move on.\""),
    dict(name="Maren Tidewatch", type="Tide", blurb="Counts the tides out loud while she battles.",
         team=[("mistfin", 15), ("tadpearl", 15), ("brinemaw", 17)],
         win="\"Six hours out, six hours back. You were quicker.\""),
    dict(name="Bhodi Stonewatch", type="Stone", blurb="Built like the cairns he guards.",
         team=[("pebbleton", 19), ("thornwood", 19), ("cragjaw", 22)],
         win="He nods once, which from him is a parade."),
    dict(name="Sable", type="Gloom", blurb="You are fairly sure she was not there a moment ago.",
         team=[("dimwisp", 24), ("nightveil", 25), ("shadecub", 25), ("umbrafang", 28)],
         win="\"The wood lets you leave,\" she says. \"That's rarer than winning.\""),
]
