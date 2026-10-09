import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os, random
sys.path.insert(0, os.path.join(ROOT, "sdk"))
sys.path.insert(0, os.path.join(ROOT, "games", "beastling"))
os.environ["COLUMNS"] = "66"; os.environ["LINES"] = "24"
import termstation_sdk as ts
from main import Game, Beast

_orig_randint = random.randint
_orig_random = random.random
_orig_ask_int = ts.ask_int

def force_always_hit():
    random.randint = lambda a, b: 1

def restore_random():
    random.randint = _orig_randint
    random.random = _orig_random

def make_game(levels=(30, 30)):
    ts._tv_state["active"] = False
    ts.tv("Beastling")
    game = Game({})
    game.party = [Beast("cindermole", levels[0]), Beast("sproutling", levels[1])]
    return game

def with_inputs(inputs):
    it = iter(inputs)
    def fake_ask_int(*a, **k):
        return next(it)
    return fake_ask_int

# ---- 1. basic win: strong allies, weak foes, always hit ----
force_always_hit()
game = make_game((30, 30))
foe_a = Beast("dimwisp", 3)
foe_b = Beast("dimwisp", 3)
ts.ask_int = with_inputs([1] * 40)
try:
    result = game.battle_2v2(foe_a, foe_b, wild=True, title="Duel")
finally:
    ts.ask_int = _orig_ask_int
    restore_random()
assert result == "won", result
assert not foe_a.alive and not foe_b.alive
assert game.party[0].alive or game.party[1].alive
print("basic-win: OK, result =", result)

# ---- 2. loss: weak allies, overwhelming foes ----
force_always_hit()
game2 = make_game((3, 3))
foe_a2 = Beast("magmaburrow", 40)
foe_b2 = Beast("magmaburrow", 40)
ts.ask_int = with_inputs([1] * 60)
try:
    result2 = game2.battle_2v2(foe_a2, foe_b2, wild=True, title="Duel")
finally:
    ts.ask_int = _orig_ask_int
    restore_random()
assert result2 == "lost", result2
assert not game2.party[0].alive and not game2.party[1].alive
print("basic-loss: OK, result =", result2)

# ---- 3. fewer than 2 healthy party members -> immediate loss ----
game3 = make_game((30, 30))
game3.party[1].hp = 0
result3 = game3.battle_2v2(Beast("dimwisp", 3), Beast("dimwisp", 3), wild=True, title="Duel")
assert result3 == "lost", result3
print("entry-gate (<2 healthy): OK")

# ---- 4. flee ----
game4 = make_game((30, 30))
foe_a4 = Beast("magmaburrow", 40)
foe_b4 = Beast("magmaburrow", 40)
random.random = lambda: 0.0  # force the 70% flee roll to succeed
ts.ask_int = with_inputs([5])  # Cindermole Lv30 knows 4 moves -> option 5 is "run"
try:
    result4 = game4.battle_2v2(foe_a4, foe_b4, wild=True, title="Duel")
finally:
    ts.ask_int = _orig_ask_int
    restore_random()
assert result4 == "fled", result4
print("flee: OK, result =", result4)

print("ALL 2V2 BASIC TESTS PASSED")
