import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os
sys.path.insert(0, os.path.join(ROOT, "sdk"))
sys.path.insert(0, os.path.join(ROOT, "games", "beastling"))
os.environ['COLUMNS'] = '66'; os.environ['LINES'] = '24'
import termstation_sdk as ts
from main import Game, Beast

def run(N, inputs):
    ts._tv_state['active'] = False
    ts.tv('Beastling')
    game = Game({})
    game.box = [Beast('cindermole', 5 + i) for i in range(N)]
    it = iter(inputs)
    orig_ask_int = ts.ask_int
    def fake_ask_int(*a, **k):
        return next(it)
    ts.ask_int = fake_ask_int
    try:
        game.box_screen()
    finally:
        ts.ask_int = orig_ask_int
    return game

# N=13 (2 pages of 8/5): page1 has 8 beasts + Next(9) + Back(10)
# go to page2 (pick 9=Next), pick item 1 on page2 (box[8], level 13),
# loop redraws page2 (now 4 items: [1..4]+Prev(5)+Back(6)) -- back out.
g = run(13, [9, 1, 6])
assert len(g.party) == 1, f"expected 1 in party, got {len(g.party)}"
assert g.party[0].level == 13, f"expected level 13 beast (box[8]), got {g.party[0].level}"
assert len(g.box) == 12
print("nav-to-page2-and-pick: OK, picked level", g.party[0].level)

# from page2 (5 items: idx8..12 -> options [names(5), Prev(6), Back(7)]), go prev,
# back on page1 (8 items + Next(9) + Back(10))
g2 = run(13, [9, 6, 10])  # go next(page2), prev(page1), back
assert len(g2.party) == 0 and len(g2.box) == 13
print("prev-then-back: OK, box untouched")

# single-page case (N=5) still works with plain back
g3 = run(5, [6])  # 5 items + Back = option 6
assert len(g3.party) == 0
print("single-page-back: OK")

# single-page pick works, then back out (4 remain + Back = option 5)
g4 = run(5, [3, 5])
assert len(g4.party) == 1 and g4.party[0].level == 7  # 5+2
print("single-page-pick: OK, picked level", g4.party[0].level)

print("ALL BOX PAGINATION TESTS PASSED")
