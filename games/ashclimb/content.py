"""Ashclimb's content: cards, enemies, relics and the shape of a run.

Edit this file to change the game. `main.py` holds the rules and never needs
to know what any particular card does -- an effect is a list of small steps.

Effect steps
  ("damage", n)          hit the target for n (scaled by strength/weak/vulnerable)
  ("damage_all", n)      hit every enemy
  ("block", n)           gain n block
  ("draw", n)            draw n cards
  ("energy", n)          gain n energy this turn
  ("weak", n)            target deals less damage for n turns
  ("vuln", n)            target takes more damage for n turns
  ("strength", n)        permanent +n damage per attack, this fight
  ("heal", n)            heal n
  ("exhaust_self",)      the card leaves the deck for the rest of the fight
"""

# ---------------------------------------------------------------- cards
# name: dict(cost, type, rarity, text, effect, target)
CARDS = {
    # --- starting deck
    "Strike":     dict(cost=1, type="attack", rarity="basic", target="one",
                       text="Deal 6.", effect=[("damage", 6)]),
    "Guard":      dict(cost=1, type="skill", rarity="basic", target="self",
                       text="Gain 5 block.", effect=[("block", 5)]),

    # --- common
    "Cleave":     dict(cost=1, type="attack", rarity="common", target="all",
                       text="Deal 5 to everything.", effect=[("damage_all", 5)]),
    "Heavy Blow": dict(cost=2, type="attack", rarity="common", target="one",
                       text="Deal 14.", effect=[("damage", 14)]),
    "Jab":        dict(cost=0, type="attack", rarity="common", target="one",
                       text="Deal 3. Draw 1.", effect=[("damage", 3), ("draw", 1)]),
    "Brace":      dict(cost=1, type="skill", rarity="common", target="self",
                       text="Gain 8 block.", effect=[("block", 8)]),
    "Sidestep":   dict(cost=1, type="skill", rarity="common", target="self",
                       text="Gain 4 block. Draw 1.", effect=[("block", 4), ("draw", 1)]),
    "Hamstring":  dict(cost=1, type="attack", rarity="common", target="one",
                       text="Deal 5. Weaken 2.", effect=[("damage", 5), ("weak", 2)]),
    "Expose":     dict(cost=1, type="skill", rarity="common", target="one",
                       text="Vulnerable 2.", effect=[("vuln", 2)]),
    "Second Wind":dict(cost=1, type="skill", rarity="common", target="self",
                       text="Draw 2.", effect=[("draw", 2)]),

    # --- uncommon
    "Whirl":      dict(cost=2, type="attack", rarity="uncommon", target="all",
                       text="Deal 10 to everything.", effect=[("damage_all", 10)]),
    "Riposte":    dict(cost=1, type="attack", rarity="uncommon", target="one",
                       text="Deal 8. Gain 5 block.",
                       effect=[("damage", 8), ("block", 5)]),
    "Focus":      dict(cost=1, type="power", rarity="uncommon", target="self",
                       text="Gain 2 strength.", effect=[("strength", 2)]),
    "Adrenaline": dict(cost=0, type="skill", rarity="uncommon", target="self",
                       text="Gain 2 energy. Draw 1. Exhaust.",
                       effect=[("energy", 2), ("draw", 1), ("exhaust_self",)]),
    "Bandage":    dict(cost=1, type="skill", rarity="uncommon", target="self",
                       text="Heal 6. Exhaust.",
                       effect=[("heal", 6), ("exhaust_self",)]),
    "Pin Down":   dict(cost=2, type="attack", rarity="uncommon", target="one",
                       text="Deal 9. Vulnerable 2. Weaken 2.",
                       effect=[("damage", 9), ("vuln", 2), ("weak", 2)]),
    "Bulwark":    dict(cost=2, type="skill", rarity="uncommon", target="self",
                       text="Gain 16 block.", effect=[("block", 16)]),

    # --- rare
    "Execute":    dict(cost=2, type="attack", rarity="rare", target="one",
                       text="Deal 22.", effect=[("damage", 22)]),
    "Onslaught":  dict(cost=3, type="attack", rarity="rare", target="all",
                       text="Deal 18 to everything.", effect=[("damage_all", 18)]),
    "Iron Will":  dict(cost=2, type="power", rarity="rare", target="self",
                       text="Gain 4 strength.", effect=[("strength", 4)]),
    "Reservoir":  dict(cost=1, type="skill", rarity="rare", target="self",
                       text="Gain 2 energy. Draw 2.",
                       effect=[("energy", 2), ("draw", 2)]),
}

STARTING_DECK = ["Strike"] * 5 + ["Guard"] * 4 + ["Hamstring"]

# ---------------------------------------------------------------- enemies
# An intent is one of the enemy's moves, chosen each turn and shown to you
# before you commit -- that telegraph is what makes the decisions real.
ENEMIES = {
    "Ash Rat":    dict(hp=(12, 16), glyph="r", tier="easy", moves=[
        ("attack", 5, "bares its teeth"), ("attack", 7, "bares its teeth")]),
    "Cinder Moth":dict(hp=(14, 18), glyph="m", tier="easy", moves=[
        ("attack", 4, "circles closer"), ("weak", 2, "scatters choking dust")]),
    "Slagling":   dict(hp=(20, 25), glyph="s", tier="easy", moves=[
        ("attack", 8, "swings a molten arm"), ("block", 6, "hardens its crust")]),
    "Kiln Hound": dict(hp=(26, 32), glyph="h", tier="mid", moves=[
        ("attack", 11, "lowers its head"), ("attack", 6, "snaps twice"),
        ("strength", 2, "draws breath")]),
    "Ember Priest":dict(hp=(30, 36), glyph="p", tier="mid", moves=[
        ("attack", 9, "raises a hand"), ("vuln", 2, "marks you"),
        ("block", 10, "wreathes itself")]),
    "Slag Golem": dict(hp=(44, 52), glyph="G", tier="elite", moves=[
        ("attack", 15, "raises both fists"), ("block", 12, "sets itself"),
        ("strength", 3, "glows hotter")]),
    "The Twins":  dict(hp=(34, 40), glyph="T", tier="elite", moves=[
        ("attack", 10, "steps in"), ("attack", 7, "flanks you"),
        ("weak", 2, "blinds you with ash")]),
    "The Cinder King": dict(hp=(120, 120), glyph="K", tier="boss", moves=[
        ("attack", 18, "lifts the great cleaver"),
        ("attack", 9, "sweeps low"),
        ("strength", 3, "roars, and burns brighter"),
        ("block", 15, "folds its arms")]),
}

#: Which enemies show up, and how many, as the climb goes on.
ENCOUNTERS = [
    (1, [("Ash Rat", 1)]),
    (1, [("Cinder Moth", 1)]),
    (2, [("Ash Rat", 2)]),
    (2, [("Slagling", 1)]),
    (3, [("Cinder Moth", 2)]),
    (4, [("Kiln Hound", 1)]),
    (5, [("Slagling", 1), ("Ash Rat", 1)]),
    (6, [("Ember Priest", 1)]),
    (7, [("Kiln Hound", 1), ("Cinder Moth", 1)]),
    (8, [("Ember Priest", 1), ("Slagling", 1)]),
]

ELITES = ["Slag Golem", "The Twins"]
BOSS = "The Cinder King"

# ---------------------------------------------------------------- relics
RELICS = {
    "Cracked Whetstone": "Your first attack each fight deals 3 more.",
    "Iron Ration":       "Heal 3 at the start of every fight.",
    "Ash Lens":          "Draw one extra card each turn.",
    "Ballast Stone":     "Start every fight with 5 block.",
    "Coal Heart":        "Maximum health +12.",
    "Tinderbox":         "Gain 1 extra energy on the first turn of a fight.",
}

# ---------------------------------------------------------------- the run
FLOORS = 12          # how tall the spire is
HAND_SIZE = 5
MAX_ENERGY = 3
START_HP = 70

INTRO = [
    "Twelve floors of a burning tower, and a deck of ten cards.",
    "",
    "Every card you take makes the deck stronger and slower.",
    "Choose what you carry as carefully as how you play it.",
]
