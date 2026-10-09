"""Regression tests for the faint/swap flow:
  - a beast KO'd on the switch-in used to silently bring the OLD beast back
    (no menu, no message);
  - the forced replacement offered a Cancel;
  - swap_menu treated index 0 as "already out";
  - downed beasts took numbered options (round-2 review) -- now only beasts
    still standing are listed, downed ones on a "Down:" line;
  - a voluntary swap into a likely one-shot says so in words."""
import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os, random, io, contextlib, re
os.environ["COLUMNS"] = "80"; os.environ["LINES"] = "30"
sys.path.insert(0, ROOT + "/sdk"); sys.path.insert(0, ROOT + "/games/beastling")
import termstation_sdk as ts
from main import Beast, Game
from beasts import MOVES
import arena, circuit

ANSI = re.compile(r"\x1b\[[0-9;]*m")
ts.tv("x")
ts.tv_pause = lambda *a, **k: None
random.random = lambda: 0.0          # every move hits
calls, script = [], []
G = {"game": None}


def fake_menu(heading, options, back="Back"):
    """Scripted picks are PARTY indices; translate to the menu's numbering."""
    calls.append({"heading": heading, "back": back, "options": [ANSI.sub("", o) for o in options]})
    game = G["game"]
    if script:
        p = script.pop(0)
    else:
        alive = [i for i, b in enumerate(game.party) if b.alive]
        p = alive[0] if alive else -1
    return -1 if p == -1 else game.swap_choices().index(p)


def fake_ask_int(msg, lo=None, hi=None, default=None):
    me = G["game"].lead()
    if asks:
        return asks.pop(0)(me)
    for i, m in enumerate(me.moves, 1):
        if me.pp.get(m, 0) > 0 and MOVES[m]["power"] > 0:
            return i
    return 1


ts.menu, ts.ask_int = fake_menu, fake_ask_int


def foe_always_attacks(foe, me, team, idx, memo):
    atk = next(m for m in foe.moves if MOVES[m]["power"] > 0)
    return ("move", atk)


arena.ai_decide = foe_always_attacks


def fight(game, team):
    G["game"] = game
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        res = arena.arena_fight(game, team, "T", "Tester")
    return res, ANSI.sub("", out.getvalue())


# ---- 1. KO'd on the switch-in -> you are ASKED who comes in; no Cancel, no dead options ----
game = circuit.CircuitGame("t", "Bronze")
A, B, C = Beast("cragjaw", 30), Beast("voltlynx", 30), Beast("brinemaw", 30)
game.party = [A, B, C]
for b in game.party:
    arena.prepare(b)
B.hp = 1
random.seed(3)
asks = [lambda me: len(me.moves) + 1]              # turn 1: swap
script[:] = [1,                                     # voluntary: Voltlynx (party index 1)
             2]                                     # forced: Brinemaw (party index 2)
calls.clear()
res, out = fight(game, [Beast("dimwisp", 8)])
assert res == "won", res
assert calls[0]["back"] == "Cancel" and calls[0]["heading"] == "Send out which beast?", calls[0]
forced = calls[1]
assert forced["back"] is None and forced["heading"].startswith("Voltlynx is down"), forced
assert len(forced["options"]) == 2 and not any("down" in o.lower() for o in forced["options"]), forced
assert "Down: Voltlynx" in out, "downed beasts are named on their own line"
assert "Voltlynx is down -- you send out Brinemaw!" in out and "send out Cragjaw!" not in out
assert C.alive and game.lead() is C
assert "Facing Dimwisp" in out
print("switch-in KO -> forced choice (no Cancel, only standing beasts listed, announced) OK")

# ---- 2. only one left after a switch-in KO -> auto-sent, but announced ----
game = circuit.CircuitGame("t", "Bronze")
A, B = Beast("cragjaw", 30), Beast("voltlynx", 30)
game.party = [A, B]
for b in game.party:
    arena.prepare(b)
B.hp = 1
asks = [lambda me: len(me.moves) + 1]
script[:] = [1]
calls.clear()
res, out = fight(game, [Beast("dimwisp", 8)])
assert len(calls) == 1, [c["heading"] for c in calls]   # no menu for a one-beast choice
assert "Voltlynx is down -- you send out Cragjaw!" in out
print("last beast standing is sent in automatically, with a message OK")

# ---- 3. the lead is not at index 0 -> picking it is a no-op, not a swap ----
g = Game({})
G["game"] = g
X, Y, Z = Beast("cragjaw", 30), Beast("voltlynx", 30), Beast("brinemaw", 30)
X.hp = 0
g.party = [X, Y, Z]
assert g.lead() is Y and g.swap_choices() == [1, 2]
script[:] = [1]                                     # Y, the active lead
calls.clear()
with contextlib.redirect_stdout(io.StringIO()):
    moved = g.swap_menu()
assert moved is False and g.party == [X, Y, Z], "picking the active lead must not cost a turn"
assert len(calls[-1]["options"]) == 2, calls[-1]["options"]          # X (down) not offered
script[:] = [2]
with contextlib.redirect_stdout(io.StringIO()):
    moved = g.swap_menu()
assert moved is True and g.lead() is Z
print("picking the active lead (not at index 0) is a free no-op; downed beasts not offered OK")

# ---- 4. the swap label: hits both ways; a voluntary swap into a one-shot says so ----
game = circuit.CircuitGame("t", "Bronze")
G["game"] = game
arena.CURRENT["foe"] = f = Beast("pyrelisk", 32)
arena.prepare(f)
lead = Beast("cragjaw", 30); arena.prepare(lead)
game.party = [lead]
for slug in ("cragjaw", "sproutling", "tadpearl"):
    b = Beast(slug, 30); arena.prepare(b)
    game.party.append(b)
    for forced_flag in (True, False):
        label = ANSI.sub("", game.swap_label(b, forced_flag))
        assert ("KOs in" in label and "KO'd in" in label) or "likely KO'd on entry" in label, label
        assert len("   [6] " + label) <= 62, (len(label), label)
    print("  ", ANSI.sub("", game.swap_label(b, False)))
frail = Beast("sproutling", 30); arena.prepare(frail); frail.hp = 5
game.party.append(frail)
assert "likely KO'd on entry" in ANSI.sub("", game.swap_label(frail, False))
assert "KO'd in 1" in ANSI.sub("", game.swap_label(frail, True))        # forced: no free hit
lead.hp = 5
assert "likely KO'd on entry" not in ANSI.sub("", game.swap_label(lead, False)), "the lead isn't entering"
print("swap label: hits both ways; 'likely KO'd on entry' only on a voluntary swap-in OK")
print("ALL SWAP FLOW TESTS PASSED")
