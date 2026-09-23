"""The opponent's side of the ring.

A simple, honest fighter: reads your telegraph and defends it more often
than not, presses when you give it nothing to react to, and throws when it's
close enough to land. Not tuned for difficulty yet -- that's balance work
for later stages. This exists to make the debut card playable, not perfect.
"""
import random

from bout import ATTACKS

BLOCK_FOR = {"leg": "block_leg", "ribs": "block_ribs", "arm": "block_arm", "head": "block_head"}


def choose(bout, me, foe, rng):
    # something already coming at us -- defend it, mostly correctly
    if foe.pending is not None:
        if rng.random() < 0.15:
            return "dodge"
        if rng.random() < me.base_read:
            return BLOCK_FOR[foe.pending["loc"]]
        return rng.choice(list(BLOCK_FOR.values()))

    # a strike of ours is already in flight -- keep pressing or hold ground
    if me.pending is not None:
        return "wait"

    gap = bout.gap()
    if gap > 2:
        return "advance"

    # in range: throw something we can actually land
    throwable = [k for k, spec in ATTACKS.items() if spec["rng"][0] <= gap <= spec["rng"][1]]
    if throwable and rng.random() < 0.75:
        return rng.choice(throwable)
    if gap < 1:
        return "retreat"
    return "wait"
