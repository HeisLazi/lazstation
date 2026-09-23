"""Wildreach's matter: what the world is made of, and how it reacts.

The whole game runs on three rules, borrowed from Breath of the Wild's
chemistry engine:

  1. an element can change a material's state   (fire + grass -> burning)
  2. an element can change another element      (water + fire  -> steam)
  3. a material cannot change another material  (grass does nothing to wood)

Everything emergent in this game falls out of those three and the tables
below. Add a row here and it interacts with everything already present --
that is the point, and it is why there is no table of special cases.
"""

# ---------------------------------------------------------------- materials
# key: glyph, colour, walkable, blocks sight, cover bonus, notes
MATERIALS = {
    "grass":  dict(glyph='"', rgb=(90, 150, 70),  walk=True,  opaque=False, cover=0),
    "brush":  dict(glyph='%', rgb=(70, 130, 60),  walk=True,  opaque=False, cover=2),
    "tree":   dict(glyph='♣', rgb=(50, 110, 55),  walk=False, opaque=True,  cover=4),
    "dirt":   dict(glyph='.', rgb=(120, 100, 75), walk=True,  opaque=False, cover=0),
    "road":   dict(glyph='=', rgb=(150, 135, 105),walk=True,  opaque=False, cover=0),
    "sand":   dict(glyph='.', rgb=(200, 180, 120),walk=True,  opaque=False, cover=0),
    "stone":  dict(glyph='▒', rgb=(130, 130, 140),walk=True,  opaque=False, cover=1),
    "rock":   dict(glyph='▓', rgb=(105, 105, 115),walk=False, opaque=True,  cover=6),
    "wall":   dict(glyph='█', rgb=(90, 88, 95),   walk=False, opaque=True,  cover=8),
    "water":  dict(glyph='≈', rgb=(60, 120, 200), walk=False, opaque=False, cover=0),
    "shallow":dict(glyph='~', rgb=(80, 150, 210), walk=True,  opaque=False, cover=0),
    "ice":    dict(glyph='=', rgb=(170, 220, 240),walk=True,  opaque=False, cover=0),
    "snow":   dict(glyph='.', rgb=(225, 235, 245),walk=True,  opaque=False, cover=0),
    "oil":    dict(glyph='~', rgb=(70, 60, 80),   walk=True,  opaque=False, cover=0),
    "ash":    dict(glyph='·', rgb=(95, 90, 88),   walk=True,  opaque=False, cover=0),
    "ruin":   dict(glyph='▪', rgb=(140, 130, 115),walk=True,  opaque=False, cover=2),
    "door":   dict(glyph='+', rgb=(170, 130, 80), walk=True,  opaque=True,  cover=3),
    "floor":  dict(glyph='.', rgb=(140, 130, 120),walk=True,  opaque=False, cover=0),
}

# ---------------------------------------------------------------- elements
# An element sits *on* a tile. Only one at a time; reactions decide which.
ELEMENTS = {
    "fire":   dict(glyph='^', rgb=(255, 150, 40),  light=6.0, damage=4),
    "ember":  dict(glyph='·', rgb=(200, 90, 30),   light=2.0, damage=1),
    "wet":    dict(glyph='~', rgb=(90, 150, 220),  light=0.0, damage=0),
    "ice":    dict(glyph='*', rgb=(190, 230, 250), light=0.0, damage=0),
    "spark":  dict(glyph='≡', rgb=(255, 245, 130), light=3.0, damage=6),
    "steam":  dict(glyph='°', rgb=(190, 200, 210), light=0.0, damage=0),
    "smoke":  dict(glyph='▒', rgb=(110, 108, 105), light=0.0, damage=0),
}

#: Rule 1 -- fire takes hold of these, and for how many turns.
BURNS = {"grass": 3, "brush": 5, "tree": 8, "oil": 2, "door": 6, "ruin": 0}

#: What is left behind once it has burnt out.
ASHES = {"grass": "ash", "brush": "ash", "tree": "ash", "oil": "ash", "door": "floor"}

#: Rule 1 -- these carry a charge to their neighbours.
CONDUCTS = {"water", "shallow", "ice", "ruin"}

#: Materials that soak, and what they become.
SOAKS = {"ash": "dirt"}

#: Rule 2 -- element meeting element. (existing, arriving) -> what remains.
#: None means both are consumed.
REACTIONS = {
    ("fire", "wet"): "steam",
    ("wet", "fire"): "steam",
    ("fire", "ice"): "wet",
    ("ice", "fire"): "wet",
    ("wet", "ice"): "ice",
    ("ice", "wet"): "ice",
    ("spark", "wet"): "spark",      # a charge runs through standing water
    ("wet", "spark"): "spark",
    ("steam", "fire"): "steam",
    ("smoke", "fire"): "fire",
}

#: How long an element lasts, in world turns, before it fades.
LIFETIME = {"fire": 4, "ember": 3, "wet": 14, "ice": 20, "spark": 1,
            "steam": 3, "smoke": 4}

# ---------------------------------------------------------------- weather
WEATHER = {
    "clear":   dict(label="clear",        light=1.00, douses=False, charge=0.0),
    "cloud":   dict(label="overcast",     light=0.86, douses=False, charge=0.0),
    "rain":    dict(label="rain",         light=0.72, douses=True,  charge=0.0),
    "storm":   dict(label="thunderstorm", light=0.62, douses=True,  charge=0.05),
    "snow":    dict(label="snowfall",     light=0.80, douses=True,  charge=0.0),
    "fog":     dict(label="fog",          light=0.70, douses=False, charge=0.0),
}

#: Which weather each biome tends toward.
BIOME_WEATHER = {
    "meadow": ["clear", "clear", "cloud", "rain", "fog"],
    "forest": ["clear", "cloud", "rain", "fog", "storm"],
    "marsh":  ["fog", "rain", "cloud", "storm", "rain"],
    "waste":  ["clear", "clear", "clear", "storm", "cloud"],
    "peaks":  ["snow", "snow", "cloud", "storm", "clear"],
}

#: Light through the day, by hour. The world runs on a 24-hour clock.
DAYLIGHT = [0.18, 0.16, 0.16, 0.18, 0.26, 0.42, 0.62, 0.80, 0.92, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 0.96, 0.88, 0.74, 0.56, 0.38, 0.26, 0.20, 0.18, 0.18]
