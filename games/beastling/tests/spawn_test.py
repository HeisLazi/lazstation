import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, random, collections
sys.path.insert(0, os.path.join(ROOT, "sdk")); sys.path.insert(0, os.path.join(ROOT, "games", "beastling"))
from beasts import ROUTES, CHAMPIONS, SPECIES, RARE_WEIGHT

rng = random.Random(7)
N = 40000
for r in ROUTES:
    w = r.get("weights", {})
    ws = [w.get(s, 10) for s in r["wild"]]
    c = collections.Counter(rng.choices(r["wild"], weights=ws, k=N))
    rare = [s for s in r["wild"] if w.get(s, 10) <= RARE_WEIGHT]
    rare_pct = sum(c[s] for s in rare) / N * 100
    top = c.most_common(1)[0]
    low = min(c.items(), key=lambda kv: kv[1])
    print(f"{r['name']:17} rare={rare} total {rare_pct:4.1f}% | most common {top[0]} {top[1]/N*100:4.1f}% | rarest {low[0]} {low[1]/N*100:3.1f}%")
    assert 0.5 < rare_pct < 8, rare_pct
for ch in CHAMPIONS:
    for slug, lv in ch["team"]:
        assert slug in SPECIES
    print(ch["name"], [f"{SPECIES[s]['name']} {lv}" for s, lv in ch["team"]],
          "types:", sorted({SPECIES[s]['type'] for s, _ in ch["team"]}))
