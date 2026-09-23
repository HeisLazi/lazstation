"""Everything you can change without touching the rules.

Rooms, enemies, barks and the words the game says are all here. main.py holds
the rules and reads this; if you want the Hollow to feel different, this is
the file to edit.

ROOM LEGEND
    #  wall          .  flagstone      ~  standing water (slows you)
    ^  brazier       o  rubble         @  where you start
    1  Sallow Duelist    2  Censer-Bearer    R  the Rival's mark
"""

# --------------------------------------------------------------- the room
# Every line must be the same length. The slice is one handmade room; the
# generator comes after we know the room is fun.
ROOM = [
    "##############################################",
    "#.....#......~~~~......................#.....#",
    "#.....#......~~~~..........o...........#.....#",
    "#.....o......~~~~.....^.........^......o.....#",
    "#............~~~~.....................o......#",
    "#.....#..............#.....#..........#.....R#",
    "@............................................#",
    "#.....#..............#.....#..........#......#",
    "#............~~~~..........1....2.....o......#",
    "#.....o......~~~~.....^.........^......o.....#",
    "#.....#......~~~~..........o...........#.....#",
    "#.....#......~~~~......................#.....#",
    "##############################################",
]

#: What each glyph is made of. `walk` and `blocks` are the only rules here;
#: everything else is how it looks.
TILES = {
    "#": dict(glyph="█", name="wall",       walk=False, blocks=True,  rgb=(74, 70, 84)),
    "o": dict(glyph="▓", name="rubble",     walk=False, blocks=True,  rgb=(104, 96, 90)),
    ".": dict(glyph="·", name="flagstone",  walk=True,  blocks=False, rgb=(84, 82, 92)),
    "~": dict(glyph="≈", name="black water",walk=True,  blocks=False, rgb=(52, 92, 140)),
    "^": dict(glyph="♦", name="brazier",    walk=False, blocks=False, rgb=(224, 132, 48)),
}

# ------------------------------------------------------------- the echoes
# `shape` is the only thing that really matters about an enemy. It is what
# the player learns, and it is what makes two enemies together a problem.
ENEMIES = {
    "duelist": dict(
        name="Sallow Duelist", glyph="†", rgb=(206, 198, 170),
        hp=4, shape="line", reach=4, windup=1, damage=2,
        tell="lowers the point of his blade",
    ),
    "censer": dict(
        name="Censer-Bearer", glyph="§", rgb=(198, 130, 208),
        hp=5, shape="burst", reach=1, windup=2, damage=2,
        tell="begins to swing the censer",
    ),
}

# ------------------------------------------------------------------ barks
# One line, tied to one moment. The cheapest aliveness in game design: say
# something at the right time and a stat block becomes a person.
BARKS = {
    "windup": [
        "{name} {tell}.",
        "{name} commits.",
    ],
    "staggered": [
        "You break the shape of it. {name} folds inward.",
        "The ritual snaps. {name} cannot finish.",
        "{name} had been doing that for a very long time.",
    ],
    "hit_weak": [
        "You cut {name}, but it is already moving.",
        "A shallow one. {name} does not care.",
    ],
    "struck": [
        "It lands. You feel that one in your teeth.",
        "The blow arrives exactly where it was always going to.",
    ],
    "stepthrough": [
        "You walk through the place where the blow will be.",
        "You are not there when it happens.",
    ],
    "kill": [
        "{name} comes apart, and the loop with it.",
        "Whatever {name} was rehearsing, it is finished now.",
    ],
    "knock_brazier": [
        "{name} goes into the coals. The Hollow smells like a kitchen.",
    ],
    "idle": [
        "Water moves somewhere below.",
        "Something is breathing behind the wall.",
        "The candles have been burning a long time.",
        "Far off, a censer swings, and swings, and swings.",
    ],
}

#: The Rival. One other named person is the difference between a world and a
#: test harness, so she is in the first playable build, not in polish.
RIVAL = dict(
    name="Ines Cabral",
    mark="R",
    note=[
        "Cut into the stone, recently, by someone in a hurry:",
        "",
        "   THEY REPEAT. THAT IS THE WHOLE OF IT.",
        "   DO NOT TRADE WITH THEM. WAIT FOR THE TURN.",
        "                                    - I.C.",
    ],
)

# ------------------------------------------------------------ the ending
DEATH_TITLE = "THE HOLLOW KEEPS YOU"
VICTORY_TITLE = "THE TRANSEPT IS QUIET"
