import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os, random, io, contextlib
os.environ["COLUMNS"] = "66"; os.environ["LINES"] = "24"
sys.path.insert(0, os.path.join(ROOT, "sdk")); sys.path.insert(0, os.path.join(ROOT, "games", "beastling"))
import termstation_sdk as ts
from main import Game, Beast
from beasts import CHAMPIONS, ITEMS, SPECIES, TRAIN_CAP, train_price, RARE_DROPS
ts.tv("x")
def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)

# champion data
for c in CHAMPIONS:
    assert len(c["gear"]) == len(c["team"]), c["name"]
    assert all(g is None or g in ITEMS for g in c["gear"])
    assert sum(g is not None for g in c["gear"]) >= 1, "every champion has a geared ace"
print("champion gear aligned with teams:", [(c["name"].split()[0], max(l for _, l in c["team"])) for c in CHAMPIONS])

# challenge: foes carry gear at full HP; box shows level info
seen = []
def fake_battle(self, foe, wild, title, trainer="", rare=False):
    seen.append((foe.slug, foe.level, foe.item, foe.hp == foe.max_hp)); return "won"
real = Game.battle; Game.battle = fake_battle
shown = []
real_box = ts.box
ts.box = lambda lines, *a, **k: (shown.append(list(lines)), real_box(lines, *a, **k))[1]
ts.confirm = lambda *a, **k: True; ts.tv_pause = lambda *a, **k: None
g = Game({}); g.party = [Beast("cindermole", 20)] * 1
quiet(g.challenge, CHAMPIONS[1])
Game.battle = real; ts.box = real_box
assert [s[2] for s in seen] == CHAMPIONS[1]["gear"] and all(s[3] for s in seen) and g.badges == 1
text = " ".join(shown[0])
assert "top level 15" in text and "Your best six average level 20" in text, text
print("challenge: aces geared, full HP, box shows top level and your average OK")

# spire rest stop on boss floors only
g = Game({}); g.party = [Beast("cindermole", 40) for _ in range(3)]
g.party[0].hp = 10; g.party[1].hp = 0; g.party[2].hp = g.party[2].max_hp
random.random = lambda: 0.99
lines = g.spire_rewards(4)
assert g.party[0].hp == 10 and g.party[1].hp == 0, "no rest stop on ordinary floors"
lines = g.spire_rewards(5)
b0, b1, b2 = g.party
assert b0.hp == 10 + (b0.max_hp - 10) // 2 and b1.hp == b1.max_hp // 4 and b2.hp == b2.max_hp
assert any("Rest stop" in l for l in lines)
print("spire rest stop: halfway heal + quarter revive on boss floors only OK")

# mastery tier pricing
assert train_price(7, 7) < train_price(8, 8) - 350, (train_price(7, 7), train_price(8, 8))
assert TRAIN_CAP == 12
t, tot = 0, 0
for stat in range(4):
    for p in range(TRAIN_CAP):
        t += train_price(p, tot); tot += 1
print(f"fully mastering one beast now costs {t} coins (points 9-12 start at {train_price(8, 32)}c)")
b = Beast.from_dict({"slug": "cindermole", "level": 5, "train": {"atk": 12}})
assert b.train == {"atk": 12}
print("ALL DIFFICULTY/SPIRE/MASTERY TESTS PASSED")
