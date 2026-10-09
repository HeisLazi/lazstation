import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os, random, io, contextlib
os.makedirs(os.environ["TERMSTATION_SAVE_DIR"], exist_ok=True)
os.environ["COLUMNS"] = "66"; os.environ["LINES"] = "24"
sys.path.insert(0, os.path.join(ROOT, "sdk")); sys.path.insert(0, os.path.join(ROOT, "games", "beastling"))
import termstation_sdk as ts
from main import Game, Beast
from beasts import TRAIN_CAP, TRAIN_STEP, train_price, ROUTES, RARE_WEIGHT

ts.tv("x")
real_menu, real_pause = ts.menu, ts.tv_pause
def scripted(seq):
    it = iter(seq)
    ts.menu = lambda *a, **k: next(it)
    ts.tv_pause = lambda *a, **k: None
def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)

# --- stat effect and pricing ---
b = Beast("cindermole", 20)
base = (b.max_hp, b.atk, b.dfn, b.spd)
b.train = {"hp": 8, "atk": 8, "dfn": 8, "spd": 8}
assert b.max_hp == base[0] + 32 and b.atk == base[1] + 12 and b.dfn == base[2] + 12 and b.spd == base[3] + 12
prices = [train_price(p, p) for p in range(TRAIN_CAP)]
assert prices == sorted(prices) and prices[0] == 150
total = sum(train_price(s, 4 * 0 + s * 4 + (0)) for s in range(1))  # smoke
full = 0; t = 0
for stat in range(4):
    for p in range(TRAIN_CAP):
        full += train_price(p, t); t += 1
print(f"fully training one beast costs {full} coins -- OK ({prices[0]}c first point)")

# --- buying through the real menus ---
g = Game({}); g.party = [Beast("cindermole", 20)]; g.money = 1000
atk0 = g.party[0].atk
scripted([0, 1, 1, -1])          # beast 0 -> (Atk, Atk) -> Back   [stat menu index 1 = atk]
# train_beast loop: menu returns 1 (atk) twice then -1 back; then training_hall asks again -> -1
scripted([0, 1, 1, -1, -1])
quiet(g.training_hall)
assert g.party[0].train == {"atk": 2}, g.party[0].train
assert g.money == 1000 - train_price(0, 0) - train_price(1, 1), g.money
assert g.party[0].atk > atk0
print("train twice via menus, money spent exactly OK")
g.money = 10
scripted([0, 2, -1, -1]); quiet(g.training_hall)
assert g.party[0].train == {"atk": 2}, "broke: no purchase"
g.money = 99999; g.party[0].train = {"spd": TRAIN_CAP}
scripted([0, 3, -1, -1]); quiet(g.training_hall)
assert g.party[0].train["spd"] == TRAIN_CAP and g.money == 99999
print("broke / maxed refusals OK")

# --- persistence incl. the hp clamp fix ---
v = Beast("cindermole", 20); v.item = "Vigor Seed"; v.train = {"hp": 8}
v.hp = v.max_hp
d = v.to_dict()
r = Beast.from_dict(d)
assert r.train == {"hp": 8} and r.item == "Vigor Seed" and r.hp == r.max_hp == v.max_hp, (r.hp, r.max_hp, v.max_hp)
junk = Beast.from_dict({"slug": "cindermole", "level": 5, "train": {"atk": 99, "bogus": 3, "hp": -4}})
assert junk.train == {"atk": TRAIN_CAP, "hp": 0}
assert "train" not in Beast("cindermole", 5).to_dict() or Beast("cindermole", 5).to_dict()["train"] == {}
print("persistence + full-HP-survives-load + junk clamped OK")

# --- Rare Scent ---
g2 = Game({}); g2.party = [Beast("cindermole", 20)]; g2.inventory = {"Rare Scent": 1}
scripted([0]); quiet(g2.use_item_menu)
assert g2.scent == 15 and "Rare Scent" not in g2.inventory
log = []; g2.inventory = {"Rare Scent": 1}; g2.scent = 0
scripted([0]); assert quiet(g2.use_item_menu, log) is False and g2.scent == 0 and g2.inventory["Rare Scent"] == 1
print("scent usable at camp, refused mid-fight, not spent on refusal OK")
route = ROUTES[0]; w = route["weights"]
rare = [s for s in route["wild"] if w.get(s, 10) <= RARE_WEIGHT]
def rare_rate(boost, n=20000):
    ws = [w.get(x, 10) * (boost if w.get(x, 10) <= RARE_WEIGHT else 1) for x in route["wild"]]
    picks = random.Random(3).choices(route["wild"], weights=ws, k=n)
    return sum(p in rare for p in picks) / n * 100
print(f"rare rate on {route['name']}: {rare_rate(1):.1f}% -> {rare_rate(5):.1f}% with scent")
assert rare_rate(5) > 3 * rare_rate(1)

ts.menu, ts.tv_pause = real_menu, real_pause
print("ALL SINK TESTS PASSED")
