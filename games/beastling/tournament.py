"""Tournament mode: pick a squad, fight a generated bracket, no healing
between rounds. Separate from the story champions (beasts.py CHAMPIONS,
fixed, tied to badge progress) -- this is meant to be replayed, so the
opposition is generated fresh each run and scaled to whatever level the
player's own squad actually is, not to story progress.
"""
from __future__ import annotations

import random

from beasts import SPECIES, TYPES

ROUNDS = 6
#: team size per round, ramping up so the bracket gets harder to just
#: out-stall as well as out-damage
TEAM_SIZE = [2, 3, 3, 4, 5, 6]

#: two or three name/blurb pairs per type, so a given type doesn't always
#: introduce itself the same way on replay
RIVALS = {
    "Ember": [
        ("Coal", "Never stands still. You can smell her coming."),
        ("Sear", "Talks in a low burn the whole match."),
    ],
    "Tide": [
        ("Undra", "Counts the exchanges out loud, like the tide."),
        ("Brack", "Damp-sleeved and unbothered by anything you do."),
    ],
    "Bloom": [
        ("Fenn", "Smiles like the match is already a formality."),
        ("Yarrow", "Chews a grass stem and watches you longer than is comfortable."),
    ],
    "Stone": [
        ("Karn", "Built like the thing he's guarding."),
        ("Old Flint", "Has fought here longer than the arena has stood."),
    ],
    "Spark": [
        ("Vess", "Fidgets. Everything about her is faster than you expect."),
        ("Jolt", "Introduces himself between exchanges, never before."),
    ],
    "Gloom": [
        ("Rue", "You keep losing track of exactly where she's standing."),
        ("Nocturne", "Doesn't blink. You start to notice you do."),
    ],
}

#: the final round is always a two-type rival -- the bracket's real test
FINALISTS = [
    ("The Warden", ("Stone", "Spark"), "Runs the whole circuit. Rarely loses here."),
    ("Halloway", ("Gloom", "Tide"), "Nobody's seen them enter or leave the arena."),
    ("Ember & Bloom's Keeper", ("Ember", "Bloom"), "Two disciplines, one very calm trainer."),
]


def _species_of(*types: str) -> list[str]:
    return [slug for slug, d in SPECIES.items() if d["type"] in types]


def generate_bracket(avg_level: int, rng: random.Random | None = None) -> list[dict]:
    """Returns ROUNDS dicts: name, type(s), blurb, team=[(slug, level), ...].

    Levels are centred on the player's own squad average, escalating
    gently round to round, so this is worth playing (and replaying) at
    any point in the game, not just once your team is maxed out.
    """
    rng = rng or random.Random()
    order = list(TYPES)
    rng.shuffle(order)

    rounds = []
    for i in range(ROUNDS - 1):
        m_type = order[i % len(order)]
        name, blurb = rng.choice(RIVALS[m_type])
        size = TEAM_SIZE[i]
        pool = _species_of(m_type) or list(SPECIES)
        lo = max(2, avg_level - 2 + i)
        hi = avg_level + 1 + i
        team = [(rng.choice(pool), rng.randint(lo, hi)) for _ in range(size)]
        rounds.append(dict(name=name, types=[m_type], blurb=blurb, team=team))

    name, types, blurb = rng.choice(FINALISTS)
    size = TEAM_SIZE[-1]
    pool = _species_of(*types)
    lo = avg_level + 2
    hi = avg_level + 5
    team = [(rng.choice(pool), rng.randint(lo, hi)) for _ in range(size)]
    rounds.append(dict(name=name, types=list(types), blurb=blurb, team=team))
    return rounds
