import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os, random, io, contextlib
sys.path.insert(0, os.path.join(ROOT, "sdk")); sys.path.insert(0, os.path.join(ROOT, "games", "beastling"))
os.environ["COLUMNS"] = "66"; os.environ["LINES"] = "24"
import termstation_sdk as ts
from main import Game, Beast
ts.tv("x")
g = Game({}); g.party = [Beast("cindermole", 20)]
n = len(g.party[0].moves)
orig = ts.ask_int
seq = iter([n + 3]); ts.ask_int = lambda *a, **k: next(seq)
random.random = lambda: 0.0
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    g.battle(Beast("lumenmoth", 5), wild=True, title="Storm Mesa", rare=True)
ts.ask_int = orig
assert "A rare Lumenmoth appears!" in buf.getvalue()
buf = io.StringIO(); seq = iter([n + 3]); ts.ask_int = lambda *a, **k: next(seq)
with contextlib.redirect_stdout(buf):
    g.battle(Beast("lumenmoth", 5), wild=True, title="Storm Mesa")
ts.ask_int = orig
assert "A wild Lumenmoth appears!" in buf.getvalue() and "rare" not in buf.getvalue()
print("rare announcement OK")
