import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os, random, io, contextlib, json, shutil
SAVE = tempfile.mkdtemp(prefix="beastling-district-")
shutil.rmtree(SAVE, ignore_errors=True); os.makedirs(SAVE)
os.environ["TERMSTATION_SAVE_DIR"] = SAVE
os.environ["COLUMNS"] = "80"; os.environ["LINES"] = "30"
sys.path.insert(0, ROOT + "/sdk"); sys.path.insert(0, ROOT + "/games/beastling")
import termstation_sdk as ts
from main import Beast
import arena, circuit
from circuit import District, load_profile, DRAFT_LEVEL

ts.tv("x")
real_menu, real_pause, real_confirm, real_draft, real_fight = ts.menu, ts.tv_pause, ts.confirm, circuit.draft_squad, arena.arena_fight
def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)
def menus(*picks):
    it = iter(picks)
    ts.menu = lambda *a, **k: next(it)
    ts.tv_pause = lambda *a, **k: None
def squad(slugs=("cragjaw", "voltlynx", "brinemaw", "nightveil", "thornwood", "pyrelisk")):
    return [Beast(s, DRAFT_LEVEL) for s in slugs]

# ---- fresh profile
p = load_profile(); p["name"] = "Tester"
assert p["coins"] == 150 and p["bag"] == {"Potion": 2} and p["run"] is None and p["training"] == {}
d = District(p)
assert "Squad Hall" in d.gate() and "Infirmary is for squads" in d.infirmary()
print("fresh profile: defaults OK; gate/infirmary politely refuse with no run")

# ---- squad hall creates a run
circuit.draft_squad = lambda ranked: squad()
ts.confirm = lambda *a, **k: True
menus(0)                                   # mode: Free
note = quiet(d.squad_hall)
run = p["run"]
assert run and run["mode"] == "Free" and run["round"] == 0 and len(run["bracket"]) == 6 and len(d.game.party) == 6
assert all(b.pp and b.hp == b.max_hp for b in d.game.party) and "Round 1" in note
sizes = [len(r["team"]) for r in run["bracket"]]
assert sizes == [2, 2, 3, 3, 3, 4], sizes
print("squad hall: run created, 6 beasts with kits+PP, bracket sizes", sizes)

# ---- the Yard trains a species; the next squad gets it
p["coins"] = 1000
menus(0, -1, -1)                           # paged menu stub below handles species pick
d.game.paged_menu = lambda *a, **k: sorted(circuit.SPECIES, key=lambda s: (circuit.SPECIES[s]["type"], circuit.SPECIES[s]["name"])).index("voltlynx")
seq = iter([1, 1, -1, -1])                 # Atk, Atk, back out; then back out of the yard list
ts.menu = lambda *a, **k: next(seq)
# train_species uses ts.menu; yard's species pick uses paged_menu -> return voltlynx once then -1
picks = iter([circuit.sorted if False else None])
state = {"n": 0}
def paged(*a, **k):
    state["n"] += 1
    return (sorted(circuit.SPECIES, key=lambda s: (circuit.SPECIES[s]["type"], circuit.SPECIES[s]["name"])).index("voltlynx")
            if state["n"] == 1 else -1)
d.game.paged_menu = paged
quiet(d.yard)
t = p["training"]["voltlynx"]
assert t == {"atk": 2}, t
spent = 1000 - p["coins"]
from beasts import train_price
assert spent == train_price(0, 0) // 2 + train_price(1, 1) // 2, spent
print(f"yard: trained voltlynx Atk x2 for {spent} coins (half the Story Training Hall price) OK")

# ---- fighting: win a round (stub the fight), prize + clean bonus
def win_clean(game, team, title, trainer):
    for b in team: b.hp = 0
    return "won"
arena.arena_fight = win_clean
coins0 = p["coins"]
menus()
quiet(d.gate)
assert p["run"]["round"] == 1
assert p["coins"] == coins0 + 50 + 20 + 25, p["coins"] - coins0
print("round 1 cleared: prize 50+20+25 clean bonus OK")

def win_dirty(game, team, title, trainer):
    game.party[0].hp = 0
    return "won"
arena.arena_fight = win_dirty
coins0 = p["coins"]; quiet(d.gate)
assert p["coins"] == coins0 + 50 + 40 and p["run"]["round"] == 2
print("a win that costs a beast pays no clean bonus OK")

# ---- infirmary: per-beast HP / PP / revive, prices by round, refuses when broke
party = d.game.party
assert not party[0].alive                       # win_dirty left it down
party[1].hp = 10
party[2].pp[party[2].moves[0]] = 0
prices = [circuit.treatment_prices(b, 2) for b in party]
assert prices[0] == {"hp": 0, "pp": 0, "revive": 60 + 20 * 2}, prices[0]
assert prices[1]["hp"] == int((8 + (party[1].max_hp - 10) // 3) * 1.5) and prices[1]["pp"] == 0
assert prices[2]["pp"] > 0 and prices[2]["hp"] == 0
assert prices[3] == {"hp": 0, "pp": 0, "revive": 0}
p["coins"] = 5
menus(1, 0, -1); quiet(d.infirmary)            # Sproutling-ish: heal -> too poor
assert party[1].hp == 10 and p["coins"] == 5, "too poor to heal"
menus(3, -1); quiet(d.infirmary)               # a fit beast: no submenu, no charge
assert p["coins"] == 5
p["coins"] = 5000
menus(1, 0,                                    # heal beast 1
      2, 0,                                    # restore beast 2's PP (its only need)
      0, 0,                                    # revive beast 0
      -1); quiet(d.infirmary)
assert party[1].hp == party[1].max_hp
assert party[2].pp[party[2].moves[0]] == arena.move_pp(party[2].moves[0])
assert party[0].alive and party[0].hp == party[0].max_hp // 2
assert p["coins"] == 5000 - prices[1]["hp"] - prices[2]["pp"] - prices[0]["revive"], p["coins"]
# Everyone -> "All of the above": revive at half, heal and restore the rest, one bill
party[4].hp = 0; party[5].hp = 7; party[0].pp[party[0].moves[0]] = 0
prices = [circuit.treatment_prices(b, 2) for b in party]
bill = sum(sum(pr.values()) for pr in prices)
coins0 = p["coins"]
menus(6, 3, -1); quiet(d.infirmary)            # Everyone, then "All of the above" (4th entry)
assert party[4].hp == party[4].max_hp // 2 and party[5].hp == party[5].max_hp
assert all(b.pp[m] == arena.move_pp(m) for b in party for m in b.moves if b is not party[4])
assert p["coins"] == coins0 - bill, (coins0 - p["coins"], bill)
print(f"infirmary: per-beast prices (revive {prices[0]['revive'] if prices[0]['revive'] else 100}c at round 3),"
      " refuses when broke, one-at-a-time and everyone-at-once OK")
# Can't afford every revive -> "Revive N of M, strongest first" sits right after the full revive line
for b in party[:3]:
    b.hp = 0
each = circuit.treatment_prices(party[0], 2)["revive"]
p["coins"] = 2 * each + 5
seen = []
real = ts.menu
def spy(heading, options, back="Back"):
    seen.append(list(options))
    return next(it2)
it2 = iter([6, 1, -1])                         # Everyone -> "Revive 2 of 3" -> Back
ts.menu = spy
quiet(d.infirmary)
assert "Revive 2 of 3, strongest first" in seen[1][1], seen[1]
strongest = sorted(party[:3], key=lambda b: -(b.max_hp + b.atk + b.dfn + b.spd))[:2]
assert all(b.alive for b in strongest) and sum(1 for b in party[:3] if not b.alive) == 1
assert p["coins"] == 5, p["coins"]
print("infirmary: short of coins -> 'Revive 2 of 3, strongest first' revives the two strongest OK")

# ---- market
p["coins"] = 500; p["bag"] = {}
menus(0, 4, 4, -1); quiet(d.market)
assert p["bag"] == {"Potion": 1, "Ether": 2}, p["bag"]
assert p["coins"] == 500 - 40 - 2 * 150
print("market: bought a Potion and 2 Ether at listed prices OK")

# ---- persistence across a 'restart'
d.game.party[3].hp = 33
d.game.party[3].pp[d.game.party[3].moves[0]] = 2
d.save()
p2 = load_profile()
d2 = District(p2)
assert d2.game.party[3].hp == 33 and d2.game.party[3].pp[d2.game.party[3].moves[0]] == 2
assert p2["run"]["round"] == 2 and p2["bag"] == p["bag"] and p2["training"] == {"voltlynx": {"atk": 2}}
print("quit and reload: mid-run squad HP, PP, round, bag and training all restored OK")

# ---- finishing the circuit
def win_all(game, team, title, trainer): return "won"
arena.arena_fight = win_all
wins0, coins0 = p2.get("wins", 0), p2["coins"]
for _ in range(4):
    quiet(d2.gate)
assert p2["run"] is None and p2["wins"] == wins0 + 1 and p2["best_round_free"] == 6
assert p2["coins"] > coins0 + 200 and p2["history"][-1]["champion"]
print("won all 6 rounds: champion recorded, +200 finale, run cleared, history written OK")

# ---- losing: consolation, ranked score
menus(1)                                   # Ranked
circuit.draft_squad = lambda ranked: squad()
quiet(d2.squad_hall)
arena.arena_fight = win_clean
quiet(d2.gate); quiet(d2.gate)             # clear 2 rounds
arena.arena_fight = lambda *a, **k: "lost"
coins0, rank0, losses0 = p2["coins"], p2.get("rank_score", 0), p2.get("losses", 0)
quiet(d2.gate)
assert p2["run"] is None and p2["losses"] == losses0 + 1
assert p2["rank_score"] == rank0 + 2 and p2["coins"] == coins0 + 20
print("loss in round 3 (ranked): rank +2, consolation 20 coins, run cleared OK")

# ---- mid-run Squad Hall: look the squad over; abandoning is explicit
menus(0); circuit.draft_squad = lambda ranked: squad(); quiet(d2.squad_hall)
assert p2["run"] is not None
run_before = p2["run"]
out = io.StringIO()
menus(2, -1)                                  # open beast 3's card, then Back
with contextlib.redirect_stdout(out):
    d2.squad_hall()
assert p2["run"] is run_before, "looking at the squad must not touch the run"
card = out.getvalue()
b3 = d2.game.party[2]
assert b3.name in card and all(m in card for m in b3.moves) and "PP" in card and "Ability" in card
out = io.StringIO()
menus(6, -1)                                  # Type chart, then Back
with contextlib.redirect_stdout(out):
    d2.squad_hall()
chart = out.getvalue()
assert all(t in chart for t in ("Ember", "Tide", "Bloom", "Stone", "Spark", "Gloom")) and "▲" in chart and "▼" in chart
ts.confirm = lambda *a, **k: False
menus(7, -1); quiet(d2.squad_hall)            # Abandon -> "no" -> Back
assert p2["run"] is run_before, "declining the abandon must keep the run"
ts.confirm = lambda *a, **k: True
menus(7, 0); quiet(d2.squad_hall)             # Abandon -> yes -> Free draft
assert p2["history"][-1]["abandoned"] and p2["run"]["round"] == 0
print("mid-run Squad Hall: squad + beast cards, abandon only on an explicit yes OK")

arena.arena_fight, circuit.draft_squad = real_fight, real_draft
ts.menu, ts.tv_pause, ts.confirm = real_menu, real_pause, real_confirm
print("ALL DISTRICT TESTS PASSED")
