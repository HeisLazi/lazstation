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

def with_inputs(inputs):
    it = iter(inputs)
    def fake_ask_int(*a, **k):
        return next(it)
    return fake_ask_int

random.randint = lambda a, b: 1   # always hit
random.random = lambda: 0.99      # no crits

game = Game({})
game.party = [Beast("cindermole", 40), Beast("cindermole", 40)]
game.party[0].moves = ["Magma Slam"]
game.party[1].moves = ["Magma Slam"]
foe_a = Beast("dimwisp", 1)
foe_b = Beast("dimwisp", 1)
foe_b.hp = 0   # foe_b starts the encounter already down -- both allies
               # must converge on foe_a this very first round
assert not foe_b.alive

ts.ask_int = with_inputs([1, 1])
try:
    result = game.battle_2v2(foe_a, foe_b, wild=True, title="Duel")
except Exception as e:
    print("CRASHED:", repr(e))
    raise
finally:
    ts.ask_int = _orig_ask_int
    random.randint = _orig_randint
    random.random = _orig_random

assert result == "won", result
assert not foe_a.alive
print("convergence-then-fizzle: OK, result =", result, "-- no crash on the second ally's now-empty target")
