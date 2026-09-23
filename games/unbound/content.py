"""Everything you'd want to change without touching the rules.

Opponents, names, and the words the game says. main.py and bout.py hold the
rules; this file is the debut card and its flavour.
"""

#: your first bout. Gladiator-first, per the plan: you are property before
#: you are anyone the crowd knows.
DEBUT = dict(
    name="Corin the Culled",
    hp=38, stamina=9, power=6, read=0.55, block=0.35,
    intro=[
        "They don't tell you his name until you're already in the pit.",
        "Corin. Three fights, three wins. The house likes him.",
        "Nobody tells you your own name. You haven't earned one yet.",
    ],
)

PLAYER_NAME = "you (unnamed)"

LOC_LABEL = {"leg": "LEG", "ribs": "RIBS", "arm": "ARM", "head": "HEAD"}

BARKS_WIN = [
    "Corin doesn't get up. The crowd decides that's enough.",
    "Someone throws coin into the sand. Not for you. For the fight.",
]
BARKS_LOSE = [
    "The sand comes up fast. It smells like everyone who's been here before you.",
    "You hear the crowd before you feel the ground.",
]
