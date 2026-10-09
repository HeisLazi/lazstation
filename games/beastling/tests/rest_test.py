import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os
os.environ["COLUMNS"] = "66"; os.environ["LINES"] = "24"
sys.path.insert(0, os.path.join(ROOT, "sdk")); sys.path.insert(0, os.path.join(ROOT, "games", "beastling"))
import termstation_sdk as ts
from main import Game, Beast
ts.tv("x")

def team(n=6, lvl=10):
    g = Game({}); g.party = [Beast("cindermole", lvl) for _ in range(n)]; return g

g = team(); assert g.rest_cost() == 0 and g.rest() == (0, 1.0)
print("rest is free when nobody is hurt: OK")

for badges in (0, 2, 5):
    g = team(); g.badges = badges
    for b in g.party: b.hp = 0                      # worst case: everyone down
    print(f"  badges {badges}: full-team wipe costs {g.rest_cost()}c "
          f"(team max HP {sum(b.max_hp for b in g.party)})")
g = team(1); g.party[0].hp = g.party[0].max_hp - 8
c0 = g.rest_cost(); print(f"  one scratch (8 HP) at 0 badges costs {c0}c")
assert 5 < c0 < 15

g = team(); g.badges = 1; g.money = 10_000
for b in g.party: b.hp = 5
cost = g.rest_cost(); paid, frac = g.rest()
assert paid == cost and frac == 1.0 and g.money == 10_000 - cost
assert all(b.hp == b.max_hp for b in g.party)
print("full rest pays exactly the quoted cost and heals everyone: OK")

g = team(); g.money = 20
for b in g.party: b.hp = 0
cost = g.rest_cost(); paid, frac = g.rest()
assert paid == 20 and g.money == 0 and 0 < frac < 1
assert all(0 < b.hp < b.max_hp for b in g.party), [b.hp for b in g.party]
print(f"partial rest when broke ({int(frac*100)}% for 20 of {cost}c), fainted beasts revived to a sliver: OK")

g = team(); g.money = 0
for b in g.party: b.hp = 0
assert g.rest() == (0, 0.0) and all(b.hp == 0 for b in g.party)
print("zero coins heals nothing (blackout is the free fallback): OK")
print("ALL REST TESTS PASSED")
