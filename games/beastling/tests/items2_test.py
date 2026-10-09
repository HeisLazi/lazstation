import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os, random, io, contextlib
os.makedirs(os.environ["TERMSTATION_SAVE_DIR"], exist_ok=True)
os.environ["COLUMNS"] = "66"; os.environ["LINES"] = "24"
sys.path.insert(0, os.path.join(ROOT, "sdk")); sys.path.insert(0, os.path.join(ROOT, "games", "beastling"))
import termstation_sdk as ts
import main as M
from main import Game, Beast, damage, deal_damage, apply_move_effect, resolve_status_upkeep
from beasts import ITEMS, SUPPLIES, MOVES

ts.tv("x")
real_menu, real_pause, real_ask = ts.menu, ts.tv_pause, ts.ask_int
def scripted(menu_choices):
    it = iter(menu_choices)
    ts.menu = lambda *a, **k: next(it)
    ts.tv_pause = lambda *a, **k: None
def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return fn(*a, **k)

random.randint = lambda a, b: 1       # always hit
random.uniform = lambda a, b: 1.0
random.random = lambda: 0.99          # no crits/procs by default

# ---- stat items ----
b = Beast("cindermole", 20); base_hp = b.max_hp
b.item = "Vigor Seed"
assert b.max_hp == int(base_hp * 1.15), (base_hp, b.max_hp)
print("Vigor Seed hp_mult OK")

a, d = Beast("cindermole", 20), Beast("sproutling", 20)
plain = damage(a, d, "Cinder Spit")[0]
a.item = "Ember Sash"
sash = damage(a, d, "Cinder Spit")[0]
assert sash > plain * 1.2, (plain, sash)
off = damage(a, d, "Scratch")[0]                  # Stone move: no boost
a.item = None
assert off == damage(a, d, "Scratch")[0]
print(f"Ember Sash boosts Ember moves only ({plain}->{sash}) OK")

random.random = lambda: 0.10                      # between 1/16 and 1/16+0.12
a.item = None
assert damage(a, d, "Scratch")[3] is False
a.item = "Focus Lens"
assert damage(a, d, "Scratch")[3] is True
a.item = None
random.random = lambda: 0.99
print("Focus Lens crit chance OK")

# ---- Last Stand / Thorn Wrap ----
att, de = Beast("cindermole", 20), Beast("sproutling", 20)
de.item = "Last Stand"
lines = deal_damage(att, de, de.hp + 50)
assert de.hp == 1 and de.item_used and "Last Stand" in lines[0], (de.hp, lines)
de.item_used = True; de.hp = 1
lines = deal_damage(att, de, 99)                  # second would-be KO is real
assert de.hp == 0
de2 = Beast("sproutling", 20); de2.item = "Last Stand"; de2.hp = de2.max_hp // 5
deal_damage(att, de2, 999)
assert de2.hp == 0, "below 25% HP: Last Stand can't save it"
print("Last Stand OK")

att, de = Beast("cindermole", 20), Beast("sproutling", 20)
de.item = "Thorn Wrap"; hp0 = att.hp
lines = deal_damage(att, de, 10)
assert att.hp < hp0 and "Thorn Wrap" in lines[0]
att.hp = 1
lines = deal_damage(att, de, 10)
assert att.hp == 0 and "out of the fight" in lines[0]
print("Thorn Wrap recoil + faint OK")

# ---- Lifeleaf ----
l = Beast("cindermole", 20); l.item = "Lifeleaf"; l.hp = 10
out = resolve_status_upkeep(l)
assert l.hp > 10 and "Lifeleaf" in out[0]
l.hp = l.max_hp
assert resolve_status_upkeep(l) == []
print("Lifeleaf OK")

# ---- Status Ward ----
w = Beast("sproutling", 20); w.item = "Status Ward"
random.random = lambda: 0.0
out = apply_move_effect(Beast("sproutling", 20), w, "Seed Volley")
assert w.status is None and "Status Ward" in out[0], out
random.random = lambda: 0.99
print("Status Ward OK")

# ---- supplies from the bag ----
g = Game({})
g.party = [Beast("cindermole", 20), Beast("sproutling", 20), Beast("tadpearl", 20)]
g.inventory = {"Potion": 2, "Revive": 1, "Full Heal": 1, "Growth Candy": 1}
g.party[0].hp = 10
scripted([0, 0]); log = []                       # Potion on beast 0
assert quiet(g.use_item_menu, log) is True and g.party[0].hp == 50 and g.inventory["Potion"] == 1, g.party[0].hp
g.party[1].hp = 0
scripted([1, 1]); log = []                       # Revive (2nd in stock order) ... stock order = SUPPLIES order
stock = [n for n in SUPPLIES if g.inventory.get(n, 0) > 0]
ri = stock.index("Revive")
scripted([ri, 1]); log = []
assert quiet(g.use_item_menu, log) is True and g.party[1].alive and "Revive" not in g.inventory
print("Potion + Revive via bag OK")
scripted([0, 2]); log = []                       # Potion on a full-health beast: refused, not spent
n_before = g.inventory["Potion"]
assert quiet(g.use_item_menu, log) is False and g.inventory["Potion"] == n_before and "full health" in log[-1]
stock = [n for n in SUPPLIES if g.inventory.get(n, 0) > 0]
gi = stock.index("Growth Candy"); lv = g.party[2].level
scripted([gi, 2]); log = []
assert quiet(g.use_item_menu, log) is True and g.party[2].level == lv + 1
print("refuse-without-spending + Growth Candy OK")

# ---- equip from the bag, swapping returns the old item ----
g.inventory = {"Power Band": 1, "Guard Charm": 1}
scripted([0, 0]);  quiet(g.equip_menu)           # beast 0 gets Power Band
assert g.party[0].item == "Power Band" and "Power Band" not in g.inventory
scripted([0, 0]);  quiet(g.equip_menu)           # swap to Guard Charm (only gear left) -> band returns
assert g.party[0].item == "Guard Charm" and g.inventory.get("Power Band") == 1
n_gear = len([n for n in ITEMS if g.inventory.get(n, 0) > 0])
scripted([0, n_gear]); quiet(g.equip_menu)       # "Take Guard Charm back"
assert g.party[0].item is None and g.inventory.get("Guard Charm") == 1
print("equip / swap / take back OK")

# ---- shop: buy, locked, broke, cap ----
g.inventory = {}; g.money = 1000; g.badges = 0
state_msgs = []
real_sec = Game.paged_menu
seq = iter([0, 4, 0, -1])                         # Potion, locked Growth Candy, Potion, Back
Game.paged_menu = lambda self, *a, **k: next(seq)
quiet(g.shop_section, "Medicine", ["Potion", "Full Heal", "Super Potion", "Revive", "Growth Candy"])
Game.paged_menu = real_sec
assert g.inventory == {"Potion": 2} and g.money == 920, (g.inventory, g.money)
g.money = 5
seq = iter([0, -1]); Game.paged_menu = lambda self, *a, **k: next(seq)
quiet(g.shop_section, "Medicine", ["Potion"])
Game.paged_menu = real_sec
assert g.inventory == {"Potion": 2} and g.money == 5
print("shop buy / locked / broke OK")

# ---- drops ----
g.inventory = {}
random.random = lambda: 0.0
out = g.roll_drops(Beast("lumenmoth", 5), True)
assert "rare Lumenmoth dropped" in out[0] and sum(g.inventory.values()) == 1
rare_item = next(iter(g.inventory)); assert rare_item in ("Lifeleaf", "Thorn Wrap", "Last Stand", "Status Ward")
g.inventory = {}
out = g.roll_drops(Beast("lumenmoth", 5), False)
assert out and "You found" in out[0]
random.random = lambda: 0.99
assert g.roll_drops(Beast("lumenmoth", 5), False) == []
cg = __import__("circuit").CircuitGame("t", "Bronze")
assert cg.roll_drops(Beast("lumenmoth", 5), True) == [] and not cg.items_enabled
print("drops OK (circuit: none)")

# ---- persistence ----
g.inventory = {"Potion": 4, "Lifeleaf": 1}
quiet(g.store)
g2 = Game(dict(g.save))
assert g2.inventory == {"Potion": 4, "Lifeleaf": 1}
assert Game({}).inventory == {"Potion": 3}            # new game starts with potions
assert Game({"inventory": {"Gone": 5, "Potion": 0, "Revive": 2}}).inventory == {"Revive": 2}
print("inventory persists, junk dropped, new-game default OK")

ts.menu, ts.tv_pause = real_menu, real_pause
print("ALL ITEM TESTS PASSED")
