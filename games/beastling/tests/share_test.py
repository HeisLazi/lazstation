import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os, random
sys.path.insert(0, os.path.join(ROOT, "sdk")); sys.path.insert(0, os.path.join(ROOT, "games", "beastling"))
os.environ["COLUMNS"] = "66"; os.environ["LINES"] = "24"
import termstation_sdk as ts
from main import Game, Beast
import circuit
ts.tv("x")
g = Game({})
g.party = [Beast("cindermole", 10), Beast("sproutling", 2), Beast("tadpearl", 2)]
before = [b.xp + b.level * 1000 for b in g.party]
notes = g.share_xp(g.party[0], 30)
after = [b.xp + b.level * 1000 for b in g.party]
assert after[0] == before[0] and after[1] > before[1] and after[2] > before[2], (before, after)
print("share_xp OK", notes)
g.party[2].hp = 0
b2 = g.party[2].xp
g.share_xp(g.party[0], 30)
assert g.party[2].xp == b2, "fainted beasts must not gain"
cg = circuit.CircuitGame("t", "Bronze"); cg.party = [Beast("cindermole", 30), Beast("sproutling", 30)]
assert cg.share_xp(cg.party[0], 99) == [] and cg.party[1].xp == 0
print("circuit no-share OK")
# out-of-lures message dedupe + grey tail
random.randint = lambda a, b: 1
g2 = Game({}); g2.party = [Beast("cindermole", 20)]; g2.lures = 0
inputs = iter([3, 3, 3, 5])  # lure x3 (moves=2? tail numbers vary) then run
foe = Beast("dimwisp", 3)
orig = ts.ask_int
n = len(g2.party[0].moves)
seq = iter([n + 1, n + 1, n + 1, n + 3])
ts.ask_int = lambda *a, **k: next(seq)
random.random = lambda: 0.0
out = []
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    r = g2.battle(foe, wild=True, title="t")
ts.ask_int = orig
text = buf.getvalue()
assert r == "fled", r
print("lure-spam count in output:", text.count("No lures left"), "(screens redraw log, one message in log)")
