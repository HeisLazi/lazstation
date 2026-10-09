"""Draft regression: an off-page number flips the page instead of drafting
blind; picks and drops are announced; the squad line spans both pages."""
import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os, io, contextlib
os.environ["COLUMNS"] = "66"; os.environ["LINES"] = "24"
sys.path.insert(0, ROOT + "/sdk"); sys.path.insert(0, ROOT + "/games/beastling")
import termstation_sdk as ts
import circuit
from beasts import SPECIES

ts.tv("x")
ts.tv_pause = lambda *a, **k: None
order = sorted(SPECIES, key=lambda s: (SPECIES[s]["type"], circuit.point_cost(s)))
n = len(order)
num = {SPECIES[s]["name"]: i + 1 for i, s in enumerate(order)}
p1, p2 = "Fizzwing", "Cairnhorn"
assert num[p1] <= circuit.DRAFT_PAGE < num[p2], (num[p1], num[p2])
keys = iter([num[p1],            # page 1: draft Fizzwing
             num[p2],            # off-page: drafts Cairnhorn AND turns to its page, says so
             n + 1,              # other page (back to 1)
             num[p1],            # drop Fizzwing
             n + 2])             # confirm
ts.ask_int = lambda *a, **k: next(keys)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    squad = circuit.draft_squad(ranked=True)
text = out.getvalue()
assert [b.name for b in squad] == [p2], [b.name for b in squad]
assert f"Drafted {p2} (Stone, {circuit.point_cost('cairnhorn')}pt) -- it's on page 2" in text, "one keystroke, shown"
assert f"Drafted {p1} (Spark, {circuit.point_cost('fizzwing')}pt)." in text
assert f"Dropped {p1}." in text and f"Squad: {p2}" in text
print("off-page number drafts in one keystroke, turns to its page and names it; drafted/dropped announced OK")

# six long names still fit the squad line at the 62-column picture
longest = sorted(SPECIES, key=lambda s: -len(SPECIES[s]["name"]))[:6]
keys = iter([order.index(s) + 1 if order.index(s) < circuit.DRAFT_PAGE else None for s in longest])
picks = [order.index(s) + 1 for s in longest]
seq = []
page = 0
for k in picks:                   # flip to the right page first when needed
    on_page2 = k > circuit.DRAFT_PAGE
    if on_page2 != (page == 1):
        seq.append(n + 1); page = 1 - page
    seq.append(k)
seq.append(n + 2)
it = iter(seq)
ts.ask_int = lambda *a, **k: next(it)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    squad = circuit.draft_squad(ranked=False)
assert len(squad) == 6
lines = [l for l in out.getvalue().splitlines() if "Squad:" in l]
last = lines[-1]
import re
plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", last).strip()
assert len(plain) <= 60, (len(plain), plain)
print("six-beast squad line fits:", plain)
print("ALL DRAFT TESTS PASSED")
