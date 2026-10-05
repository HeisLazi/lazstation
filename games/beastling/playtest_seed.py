"""Seed a save at a chosen stage so you can playtest without grinding.
usage: python3 seed_stage.py <fresh|mid|late|post> <save_dir>"""
import sys, os
stage, save_dir = sys.argv[1], sys.argv[2]
os.makedirs(save_dir, exist_ok=True)
os.environ["TERMSTATION_SAVE_DIR"] = save_dir
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "..", "..", "sdk"))
sys.path.insert(0, ROOT)
import termstation_sdk as ts
from main import Game, Beast

g = Game({})
if stage == "fresh":
    g.party = []
else:
    spec = {"mid": (2, 18, 1500), "late": (4, 30, 4000), "post": (5, 55, 9000)}[stage]
    badges, lvl, coins = spec
    g.badges, g.money = badges, coins
    g.party = [Beast(s, lvl + i) for i, s in enumerate(
        ["cindermole", "tadpearl", "sproutling", "zapkit", "pebbleton", "dimwisp"])]
    for b in g.party:
        b.hp = b.max_hp
    g.inventory = {"Potion": 6, "Super Potion": 3, "Revive": 2, "Full Heal": 3, "Growth Candy": 2,
                   "Rare Scent": 1, "Power Band": 1, "Guard Charm": 1, "Last Stand": 1, "Lifeleaf": 1}
    g.seen = set(["cindermole", "tadpearl", "sproutling", "zapkit", "pebbleton", "dimwisp"])
g.store()
print(f"seeded '{stage}' save in {save_dir}")
