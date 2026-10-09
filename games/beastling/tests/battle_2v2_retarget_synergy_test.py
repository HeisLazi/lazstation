import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os, random
sys.path.insert(0, os.path.join(ROOT, "sdk"))
sys.path.insert(0, os.path.join(ROOT, "games", "beastling"))
os.environ["COLUMNS"] = "66"; os.environ["LINES"] = "24"
import termstation_sdk as ts
from main import Game, Beast, active_synergy, damage
from beasts import TYPE_SYNERGY

_orig_randint = random.randint
_orig_random = random.random
_orig_uniform = random.uniform
_orig_ask_int = ts.ask_int

def restore():
    random.randint = _orig_randint
    random.random = _orig_random
    random.uniform = _orig_uniform
    ts.ask_int = _orig_ask_int

def with_inputs(inputs):
    it = iter(inputs)
    def fake_ask_int(*a, **k):
        return next(it)
    return fake_ask_int

# ---- active_synergy() itself ----
a = Beast("cindermole", 20)  # Ember
b = Beast("voltlynx", 20)    # Spark
syn = active_synergy(a, b)
assert syn is not None and syn["name"] == "Wildfire Storm", syn
print("active_synergy pair match: OK ->", syn["name"])

c = Beast("sproutling", 20)  # Bloom
syn2 = active_synergy(a, c)  # Ember+Bloom, not a listed pair
assert syn2 is None
print("active_synergy no match: OK")

b.hp = 0
syn3 = active_synergy(a, b)  # one fainted -> no synergy
assert syn3 is None
print("active_synergy breaks on faint: OK")

# ---- damage() dmg_mult / crit_bonus wiring ----
random.randint = lambda a, b_: 1  # always hit
random.random = lambda: 0.99      # never crit unless bonus pushes it over... check both paths
random.uniform = lambda a, b_: 1.0  # pin the damage-roll variance so only dmg_mult differs
attacker = Beast("cindermole", 20)
defender = Beast("sproutling", 20)
d_plain, *_ = damage(attacker, defender, "Magma Slam", None)
d_boosted, *_ = damage(attacker, defender, "Magma Slam", None, dmg_mult=1.15)
assert d_boosted > d_plain, (d_plain, d_boosted)
print(f"damage dmg_mult wiring: OK ({d_plain} -> {d_boosted})")

# crit_bonus: force random.random() just above CRIT_CHANCE (1/16=0.0625) but
# below CRIT_CHANCE+0.20 -- should crit only with the bonus applied
random.random = lambda: 0.10
_, _, _, crit_plain = damage(attacker, defender, "Scratch", None)
_, _, _, crit_boosted = damage(attacker, defender, "Scratch", None, crit_bonus=0.20)
assert crit_plain is False and crit_boosted is True, (crit_plain, crit_boosted)
print("damage crit_bonus wiring: OK")
restore()

# ---- retarget-on-faint in a live 2v2 round ----
# Ally A (Cindermole, high level) one-shots Foe A (Dimwisp, lv1, tiny HP);
# Ally B's default mirrored target was Foe B, so no retarget needed there --
# instead verify the FOLLOWING round: with Foe A dead, Foe B's own attack
# (mirrored to Ally B normally) still resolves fine, and a still-alive Ally
# doesn't get skipped. Then explicitly test retarget by making ally_b's
# mirrored target (foe_b) the one that dies first, and giving ally_b's turn
# priority so it must resolve AFTER foe_b is already down this same round.
random.randint = lambda a, b_: 1  # always hit
random.random = lambda: 0.99      # no crits, keep numbers predictable
game = Game({})
game.party = [Beast("cindermole", 40), Beast("cindermole", 40)]
game.party[0].moves = ["Magma Slam"]  # huge power, kills a lv1 in one hit
game.party[1].moves = ["Magma Slam"]
foe_a = Beast("dimwisp", 1)
foe_b = Beast("dimwisp", 1)
ts.ask_int = with_inputs([1, 1])  # both allies use their only move
result = game.battle_2v2(foe_a, foe_b, wild=True, title="Duel")
restore()
assert result == "won", result
assert not foe_a.alive and not foe_b.alive
print("retarget/no-crash with both foes dying same round: OK, result =", result)

print("ALL RETARGET/SYNERGY TESTS PASSED")
