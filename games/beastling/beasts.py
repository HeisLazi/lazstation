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

# ---------------------------------------------------------------- moves
# name: (type, power, accuracy, description)
MOVES = {
    "Tackle":      ("Stone", 35, 95, "a plain running hit"),
    "Scratch":     ("Stone", 30, 100, "quick claws"),
    "Cinder Spit": ("Ember", 40, 95, "a gob of hot ash"),
    "Flare Rush":  ("Ember", 65, 85, "charges wreathed in flame"),
    "Magma Slam":  ("Ember", 85, 75, "brings down molten weight"),
    "Bubble":      ("Tide", 38, 100, "a stream of stinging bubbles"),
    "Tide Pull":   ("Tide", 62, 90, "drags the foe off balance"),
    "Deluge":      ("Tide", 88, 75, "a wall of black water"),
    "Vine Whip":   ("Bloom", 40, 95, "a quick lash"),
    "Seed Volley": ("Bloom", 60, 90, "a spray of hard seeds"),
    "Bramblewall": ("Bloom", 85, 75, "thorns burst from the ground"),
    "Rock Toss":   ("Stone", 45, 90, "hurls a loose stone"),
    "Cragfall":    ("Stone", 70, 80, "drops a slab"),
    "Spark Nip":   ("Spark", 42, 100, "a stinging jolt"),
    "Arc Bolt":    ("Spark", 68, 85, "a leaping arc of current"),
    "Thunderhead": ("Spark", 90, 70, "calls down the storm"),
    "Shadow Nip":  ("Gloom", 40, 100, "a bite out of the dark"),
    "Duskwave":    ("Gloom", 66, 88, "a rolling wave of shade"),
    "Night Terror":("Gloom", 92, 70, "the dark itself lunges"),
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
