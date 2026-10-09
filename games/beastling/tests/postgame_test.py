import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os, random, io, contextlib
os.environ["COLUMNS"] = "66"; os.environ["LINES"] = "24"
sys.path.insert(0, os.path.join(ROOT, "sdk")); sys.path.insert(0, os.path.join(ROOT, "games", "beastling"))
import termstation_sdk as ts
import main as M
from main import Game, Beast
from beasts import REMATCH, CHAMPIONS, ITEMS, SPECIES, RARE_DROPS

ts.tv("x")
real_menu, real_pause, real_confirm = ts.menu, ts.tv_pause, ts.confirm
def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)
def script(menu=(), confirm=True):
    it = iter(menu)
    ts.menu = lambda *a, **k: next(it)
    ts.tv_pause = lambda *a, **k: None
    ts.confirm = lambda *a, **k: confirm

def game():
    g = Game({}); g.party = [Beast("cindermole", 40 + i) for i in range(6)]
    g.money = 0; g.inventory = {}; g.badges = 5; return g

# data sanity
for c in CHAMPIONS:
    assert c["name"] in REMATCH and len(REMATCH[c["name"]]) >= 5
    for slug, item in REMATCH[c["name"]]:
        assert slug in SPECIES and (item is None or item in ITEMS), (slug, item)
print("rematch teams valid (species + items exist)")

# camp offers the hall only after 5 badges (check the option list via the real camp loop)
g = game(); g.badges = 4
opts_seen = []
ts.menu = lambda h, options, back="Back": (opts_seen.append(list(options)), -1)[1]
ts.tv_pause = lambda *a, **k: None
quiet(g.camp)
assert not any("Champion" in o for o in opts_seen[0])
g.badges = 5; opts_seen.clear(); quiet(g.camp)
assert any("Champion's Hall" in o for o in opts_seen[0]) and len(opts_seen[0]) <= 9, opts_seen[0]
print("Champion's Hall appears at 5 badges only; camp stays at", len(opts_seen[0]), "entries")

# rematch: level scaling, foes geared, rewards, counters
seen_foes = []
def fake_battle(self, foe, wild, title, trainer="", rare=False):
    seen_foes.append((foe.slug, foe.level, foe.item, foe.hp == foe.max_hp)); return "won"
real_battle = Game.battle
Game.battle = fake_battle
g = game(); script(); seen_foes.clear()
quiet(g.rematch, CHAMPIONS[0])
lvl = g.top_level() + 2
assert [f[1] for f in seen_foes] == [max(40, lvl)] * 5, seen_foes
assert seen_foes[0][2] == "Lifeleaf" and all(f[3] for f in seen_foes)
assert g.rematches == {CHAMPIONS[0]["name"]: 1} and g.money == 500 and g.inventory == {"Growth Candy": 1}
quiet(g.rematch, CHAMPIONS[0])
assert g.rematches[CHAMPIONS[0]["name"]] == 2 and g.money == 500 + 650
assert seen_foes[-1][1] == max(40, lvl + 2), "level scales with wins"
print(f"rematch scales (L{seen_foes[0][1]} -> L{seen_foes[-1][1]}), foes geared at full HP, coins + candy on first win OK")
Game.battle = real_battle

# a lost rematch costs the blackout, no credit
def lose(self, foe, wild, title, trainer="", rare=False): return "lost"
Game.battle = lose; g = game(); g.money = 300; script(); quiet(g.rematch, CHAMPIONS[1])
assert g.rematches == {} and g.money == 200
Game.battle = real_battle
print("lost rematch: blackout fee, no credit OK")

# declining does nothing
g = game(); script(confirm=False); Game.battle = fake_battle; seen_foes.clear()
quiet(g.rematch, CHAMPIONS[2]); assert not seen_foes and g.rematches == {}
Game.battle = real_battle

# spire team scaling and gear
random.seed(2)
g = game()
t1 = g.spire_team(1); t5 = g.spire_team(5); t20 = g.spire_team(20)
assert len(t1) == 3 and all(l == 42 for _, l, _ in t1)
assert len(t5) == 4 and all(i is not None for _, _, i in t5), "boss: +1 beast, all geared"
assert len(t20) == 5 + 1 and t20[0][1] == 80
assert all(i is None for _, _, i in g.spire_team(3)), "no gear before floor 6"
assert any(i in RARE_DROPS for _ in range(40) for _, _, i in g.spire_team(15)), "treasures appear from floor 12"
print("spire teams: sizes 3/4(boss)/6(floor 20 boss), levels 42/../80, gear rules OK")

# spire flow: climb floors 1-5 then retreat; check rewards and best floor
Game.battle = fake_battle; g = game(); g.money = 0
menus = iter([0, 0, 0, 0, 2])        # climb x4 (after floors 1-4), retreat after floor 5
ts.menu = lambda *a, **k: next(menus); ts.tv_pause = lambda *a, **k: None; ts.confirm = lambda *a, **k: True
random.random = lambda: 0.99
quiet(g.spire)
assert g.spire_best == 5 and g.money == sum(100 + 40 * f for f in range(1, 6)), (g.spire_best, g.money)
assert sum(g.inventory.get(r, 0) for r in RARE_DROPS) == 1, g.inventory   # floor-5 boss prize
print("spire: 5 floors, per-floor coins and the boss treasure OK")

# floor 10 pays candy + scent
g = game(); g.spire_best = 0
menus = iter([0] * 9 + [2])
quiet(g.spire)
assert g.spire_best == 10 and g.inventory.get("Growth Candy") == 2 and g.inventory.get("Rare Scent") == 1
print("floor 10 milestone (2 Growth Candy + Rare Scent) OK")

# defeat on floor 3: free heal, best floor = 2, keeps winnings
results = iter(["won", "won", "won", "won", "won", "won", "lost"])
def seq_battle(self, foe, wild, title, trainer="", rare=False): return next(results)
Game.battle = seq_battle
g = game(); g.money = 0
for b in g.party: b.hp = 1
menus = iter([0])                      # climb after floor 1... floor 1 = 3 wins, floor2 = 3 wins? script below
results = iter(["won"] * 3 + ["won"] * 3 + ["lost"])   # floors 1, 2 clear; floor 3 first fight lost
menus = iter([0, 0])
quiet(g.spire)
assert g.spire_best == 2 and all(b.hp == b.max_hp for b in g.party), (g.spire_best, [b.hp for b in g.party])
assert g.money == 140 + 180
print("spire defeat: heals free, keeps floor-2 winnings and best floor OK")

# persistence
Game.battle = real_battle
g.rematches = {CHAMPIONS[0]["name"]: 3}; g.spire_best = 12
quiet(g.store)
g2 = Game(dict(g.save))
assert g2.rematches == {CHAMPIONS[0]["name"]: 3} and g2.spire_best == 12
assert Game({"rematches": {"Nobody": 4}}).rematches == {}
print("rematches + spire best persist, junk dropped OK")
ts.menu, ts.tv_pause, ts.confirm = real_menu, real_pause, real_confirm
print("ALL POST-GAME TESTS PASSED")
