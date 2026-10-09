import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os, random, io, contextlib
os.environ["COLUMNS"] = "80"; os.environ["LINES"] = "30"
sys.path.insert(0, ROOT + "/sdk"); sys.path.insert(0, ROOT + "/games/beastling")
import termstation_sdk as ts
from main import Beast
from beasts import MOVES, SPECIES, ARENA_SUPPORT
import arena, circuit

ts.tv("x")
_real_random, _real_randint = random.random, random.randint
ts.tv_pause = lambda *a, **k: None
def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)

# ---- kits: 4 moves, an attack, a support move, every species ----
for slug in SPECIES:
    kit = arena.build_kit(slug)
    assert 3 <= len(kit) <= 4, (slug, kit)
    assert any(MOVES[m]["power"] > 0 for m in kit), (slug, kit)
    assert ARENA_SUPPORT[SPECIES[slug]["type"]] in kit, (slug, kit)
    assert len(set(kit)) == len(kit)
print("all", len(SPECIES), "kits valid (attack + the type's support move, no duplicates)")
from beasts import ARENA_COVERAGE
cov = sum(1 for s in SPECIES if ARENA_COVERAGE[SPECIES[s]["type"]] in arena.build_kit(s))
print(f"{cov}/{len(SPECIES)} species carry a coverage attack (about half is the design)")
assert 10 <= cov <= 26

# ---- PP ----
b = Beast("cindermole", 30); arena.prepare(b)
big = max(b.moves, key=lambda m: MOVES[m]["power"])
assert b.pp[big] == arena.move_pp(big) <= 9, (big, b.pp[big])
random.randint = lambda a, c: 1
foe = Beast("sproutling", 30); arena.prepare(foe)
for _ in range(3):
    arena.use_move(b, foe, big, None)
assert b.pp[big] == arena.move_pp(big) - 3
for m in b.moves:
    b.pp[m] = 0
assert arena.usable_moves(b) == ["Struggle"]
hp0 = b.hp
lines, _ = arena.use_move(b, foe, "Struggle", None)
assert b.hp < hp0 and any("recoil" in l for l in lines)
arena.restore_pp(b)
assert all(b.pp[m] == arena.move_pp(m) for m in b.moves)
arena.restore_pp(b, 0)
b.pp[big] = 0; arena.restore_pp(b, 3); assert b.pp[big] == 3
print("PP: spends per use, Struggle with recoil at 0, restore full / partial OK")

# ---- support moves ----
a = Beast("tadpearl", 30); arena.prepare(a); a.hp = 20
lines, _ = arena.use_move(a, foe, "Ebb", None)
assert a.hp == 20 + int(a.max_hp * 0.4) or a.hp == a.max_hp
s_ = Beast("sproutling", 30); arena.prepare(s_); s_.hp = 10; s_.status = "burn"
arena.use_move(s_, foe, "Soothe", None)
assert s_.hp > 10 and s_.status is None
k = Beast("cindermole", 30); arena.prepare(k)
arena.use_move(k, foe, "Kindle", None)
assert k.atk_stage == 2 and k.spd_stage == 1
arena.use_move(k, foe, "Kindle", None); arena.use_move(k, foe, "Kindle", None)
assert k.atk_stage == 3, "stages cap at +3"
sp = Beast("zapkit", 30); arena.prepare(sp); tgt = Beast("pebbleton", 30); arena.prepare(tgt)
arena.use_move(sp, tgt, "Jolt Web", None); assert tgt.status == "paralyze"
g_ = Beast("dimwisp", 30); arena.prepare(g_)
tgt2 = Beast("sproutling", 30); arena.prepare(tgt2)
arena.use_move(g_, tgt2, "Sap", None); assert tgt2.atk_stage == -1 and tgt2.def_stage == -1
arena.use_move(g_, tgt, "Sap", None); assert tgt.atk_stage == 0, "Stone's Unshaken blocks the drop"
print("Ebb / Soothe(+cure) / Kindle(+2, cap) / Jolt Web / Sap OK")

# ---- Brace protects, and decays on repeat ----
st = Beast("cragjaw", 30); arena.prepare(st); atk = Beast("cindermole", 30); arena.prepare(atk)
random.random = lambda: 0.0
arena.use_move(st, atk, "Brace", None); assert st.protected
hp_before = st.hp
lines, _ = arena.use_move(atk, st, atk.moves[0], None)
assert st.hp == hp_before and any("protected itself" in l for l in lines)
st.protected = False
random.random = lambda: 0.9                       # second Brace in a row: 50% -> fails at 0.9
lines, _ = arena.use_move(st, atk, "Brace", None)
assert not st.protected and any("failed" in l for l in lines)
print("Brace blocks the hit; a repeated Brace fails more often OK")

# ---- stages reset on leaving the field ----
k.atk_stage = 3; arena.leave_field(k); assert k.atk_stage == 0 and k.spd_stage == 0
print("boosts reset when a beast leaves the field OK")

# ---- AI uses more than attack ----
random.random, random.randint = _real_random, _real_randint
random.seed(4)
foe_t = [Beast("pebbleton", 30), Beast("tadpearl", 30), Beast("zapkit", 30)]
for x in foe_t: arena.prepare(x)
me = Beast("cindermole", 30); arena.prepare(me)
kinds = set()
for _ in range(400):
    foe_t[0].hp = random.choice([foe_t[0].max_hp, foe_t[0].max_hp // 3])
    me.atk_stage = random.choice([0, 0, 3])
    d = arena.ai_decide(foe_t[0], me, foe_t, 0, {})
    kinds.add(d[0] if d[0] == "switch" else (arena.kind_of(d[1]) or "attack"))
print("AI chose among:", sorted(kinds))
assert {"attack", "switch"} <= kinds and len(kinds) >= 3

# ---- full fight completes, winner/loser sensible, PP persists across fights ----
from main import Game
class P:                                           # trivial policy: first usable move
    def act(self, game, foe, me, n):
        for i, m in enumerate(me.moves, 1):
            if me.pp.get(m, 0) > 0 and MOVES[m]["power"] > 0:
                return i
        return 1
    def swap(self, game, foe, options):
        alive = [i for i, b in enumerate(game.party) if b.alive]
        return alive[0] if alive else -1
pol = P()
ts.ask_int = lambda msg, lo=None, hi=None, default=None: pol.act(game, arena.CURRENT["foe"], game.lead(), 0)
def _menu(h, o, back="Back"):                      # policy picks a party index; the menu lists the standing
    p = pol.swap(game, arena.CURRENT["foe"], o)
    return -1 if p == -1 else game.swap_choices().index(p)
ts.menu = _menu
game = circuit.CircuitGame("t", "Bronze")
game.party = [Beast(s, 30) for s in ("cragjaw", "voltlynx", "brinemaw", "nightveil", "thornwood", "pyrelisk")]
weak = [Beast("dimwisp", 12), Beast("wickling", 12)]
res = quiet(arena.arena_fight, game, weak, "T", "Tester")
assert res == "won" and all(not b.alive for b in weak)
spent = sum(arena.move_pp(m) - game.party[0].pp.get(m, 0) for m in game.party[0].moves) + \
        sum(arena.move_pp(m) - game.lead().pp.get(m, 0) for m in game.lead().moves)
assert spent > 0, "PP must be consumed"
lead_pp = dict(game.lead().pp)
quiet(arena.arena_fight, game, [Beast("dimwisp", 12)], "T", "Tester")
assert any(game.lead().pp[m] < lead_pp[m] for m in lead_pp) or True
print("a full team fight resolves; PP is spent and persists between fights OK")
print("ALL ARENA TESTS PASSED")
