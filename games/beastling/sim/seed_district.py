"""Seed District saves for row-budget screenshots.
usage: seed_district.py SAVE_DIR MODE   (MODE: worst | poor | faint)
Then e.g.: tools/llm_playtest/shot.py 66 24 2,4 infirmary.png --save SAVE_DIR
  worst -- round 3, 6 beasts: 3 down, the rest hurt with PP drained
  poor  -- like worst, but 250 coins (can't afford every revive)
  faint -- round 1, lead at 1 HP (so its first exchange forces a replacement)"""
import sys, os, shutil, io, contextlib
SAVE, MODE = sys.argv[1], sys.argv[2]
shutil.rmtree(SAVE, ignore_errors=True); os.makedirs(SAVE)
os.environ["TERMSTATION_SAVE_DIR"] = SAVE
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, ROOT + "/sdk"); sys.path.insert(0, ROOT + "/games/beastling")
import random
random.seed(7)
import termstation_sdk as ts
import circuit
from main import Beast
ts.tv("x")
ts.menu = lambda *a, **k: 0
ts.tv_pause = lambda *a, **k: None
ts.confirm = lambda *a, **k: True
circuit.draft_squad = lambda ranked: [Beast(s, 30) for s in
    ("cragjaw", "voltlynx", "brinemaw", "nightveil", "thornwood", "pyrelisk")]
p = circuit.load_profile(); p["name"] = "Pilot"; p["coins"] = 420
p["bag"] = {"Potion": 3, "Ether": 1, "Revive": 1}
d = circuit.District(p)
with contextlib.redirect_stdout(io.StringIO()):
    d.squad_hall()
party = d.game.party
if MODE in ("worst", "poor"):
    p["run"]["round"] = 2
    if MODE == "poor":
        p["coins"] = 250                     # 3 down at 100c each: can afford 2
    for b in party[:3]:
        b.hp = 0
    for b in party[3:]:
        b.hp = max(1, b.max_hp // 3)
        for m in b.moves[:2]:
            b.pp[m] = 1
elif MODE == "faint":
    party[0].hp = 1
d.save()
print("seeded", SAVE, MODE, "round", p["run"]["round"])
