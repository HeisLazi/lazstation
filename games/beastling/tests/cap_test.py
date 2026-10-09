import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os, random, io, contextlib
sys.path.insert(0, os.path.join(ROOT, "sdk")); sys.path.insert(0, os.path.join(ROOT, "games", "beastling"))
os.environ["COLUMNS"] = "66"; os.environ["LINES"] = "24"
import termstation_sdk as ts
from main import Game, Beast, MAX_COPIES
from beasts import SPECIES, ROUTES

ts.tv("x")
g = Game({})
g.party = [Beast("cindermole", 20), Beast("cindermole", 3)]
g.box = [Beast("cindermole", 2)]
assert g.copies("cindermole") == 3
g.lures = 5
foe = Beast("cindermole", 3)
orig = ts.ask_int
n = len(g.party[0].moves)
seq = iter([n + 1, n + 1, n + 3])        # lure, lure, run
ts.ask_int = lambda *a, **k: next(seq)
random.random = lambda: 0.0
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    r = g.battle(foe, wild=True, title="t")
ts.ask_int = orig
text = buf.getvalue()
assert g.lures == 5, "lure must not be spent at the cap"
assert "no room for more" in text and "(full)" in text, text[-500:]
assert len(g.box) == 1 and len(g.party) == 2
print("cap blocks catching, no lure spent: OK")

# a different species is still catchable
g2 = Game({}); g2.party = [Beast("cindermole", 20)]; g2.lures = 5
random.random = lambda: 0.0
seq = iter([len(g2.party[0].moves) + 1])
ts.ask_int = lambda *a, **k: next(seq)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    r = g2.battle(Beast("dimwisp", 2), wild=True, title="t")
ts.ask_int = orig
assert r == "caught" and g2.copies("dimwisp") == 1, r
print("other species still catchable: OK")

# variety: every species appears on some route (or is a starter/champion-only)
on_route = {w for r in ROUTES for w in r["wild"]}
missing = sorted(set(SPECIES) - on_route)
print("not on any route:", missing)
for r in ROUTES:
    print(f"{r['name']:18} {len(r['wild'])} species, {len(set(SPECIES[w]['type'] for w in r['wild']))} types")

# family counting: a base form and its evolution share one cap
g3 = Game({}); g3.party = [Beast("pebbleton", 5), Beast("pebbleton", 4)]; g3.box = [Beast("cragjaw", 20)]
assert g3.copies("pebbleton") == 3 and g3.copies("cragjaw") == 3 and g3.copies("cindermole") == 0
print("family cap counts evolved forms: OK")
