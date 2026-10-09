"""Round-3 fixes from the v2 brain review: item menu shows the trade and only
useful targets; combat log lines fit the picture; swapping with nobody left
says so."""
import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os, io, contextlib, re, random
os.environ["COLUMNS"] = "66"; os.environ["LINES"] = "24"
sys.path.insert(0, ROOT + "/sdk"); sys.path.insert(0, ROOT + "/games/beastling")
import termstation_sdk as ts
import main
from main import Beast
from beasts import MOVES, SPECIES
import arena, circuit

ANSI = re.compile(r"\x1b\[[0-9;]*m")
ts.tv("x")
ts.tv_pause = lambda *a, **k: None
seen = []


def scripted(*picks):
    it = iter(picks)

    def menu(heading, options, back="Back"):
        seen.append((heading, [ANSI.sub("", o) for o in options]))
        return next(it)
    ts.menu = menu


# ---- item menu: only beasts the item helps; the trade is on screen ----
game = circuit.CircuitGame("t", "Bronze")
a, b, c = Beast("sproutling", 30), Beast("cragjaw", 30), Beast("tadpearl", 30)
for x in (a, b, c):
    arena.prepare(x)
game.party = [a, b, c]
a.hp, b.hp = 22, 0                                  # a hurt lead, b down, c fine
game.inventory = {"Potion": 2, "Revive": 1}
foe = Beast("cairnhorn", 31); arena.prepare(foe)
arena.CURRENT["foe"] = foe
log = []
scripted(0, 0)                                      # Potion -> the only target (Sproutling)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    used = arena.item_menu(game, log)
text = ANSI.sub("", out.getvalue())
assert used and a.hp == 62 and game.inventory["Potion"] == 1, (used, a.hp)
heading, opts = seen[-1]
assert heading == "Potion on which beast?" and len(opts) == 1 and "22/110 HP  -> 62/110" in opts[0], opts
assert "An item spends your turn" in text and "Cairnhorn's best hit on Sproutling: about" in text, text[-300:]
expect = round(max(arena.expected_damage(foe, a, m) for m in arena.usable_moves(foe)))
seen.clear()
a.hp = 22
scripted(0, -1)
with contextlib.redirect_stdout(io.StringIO()) as o2:
    arena.item_menu(game, [])
assert f"about {round(max(arena.expected_damage(foe, a, m) for m in arena.usable_moves(foe)))} HP" in ANSI.sub("", o2.getvalue())
seen.clear()
scripted(1, 0)                                      # Revive -> only the downed beast is listed
with contextlib.redirect_stdout(io.StringIO()):
    used = arena.item_menu(game, log)
assert used and b.alive and len(seen[-1][1]) == 1 and "Cragjaw" in seen[-1][1][0], seen[-1]
game.inventory = {"Full Heal": 1}
seen.clear()
scripted(0)
with contextlib.redirect_stdout(io.StringIO()):
    used = arena.item_menu(game, log)
assert not used and log[-1] == "Nobody needs a Full Heal right now.", log[-1]
print(f"item menu: only useful targets, HP-after preview, foe's hit (~{expect}) shown OK")

# ---- combat log: the longest names and moves fit the 62-column picture ----
longest_name = max((SPECIES[s]["name"] for s in SPECIES), key=len)
longest_move = max(MOVES, key=len)
for crit in (True, False):
    for mult in (2.0, 0.5, 1.0):
        for line in main.hit_lines(longest_name, longest_move, longest_name, 999, mult, crit):
            assert len("  " + line) <= 60, (len(line), line)
print("hit_lines: worst case", max(len("  " + l) for l in main.hit_lines(longest_name, longest_move,
      longest_name, 999, 2.0, True)), "columns (picture is 62) OK")

# ---- swapping with nobody else standing says so, and costs nothing ----
game = circuit.CircuitGame("t", "Bronze")
solo, gone = Beast("cragjaw", 30), Beast("voltlynx", 30)
for x in (solo, gone):
    arena.prepare(x)
gone.hp = 0
game.party = [solo, gone]
asks = iter([len(solo.moves) + 1] + [1] * 200)
ts.ask_int = lambda *a, **k: next(asks)
arena.ai_decide = lambda f, m, t, i, memo: ("move", next(x for x in f.moves if MOVES[x]["power"] > 0))
random.seed(1)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    res = arena.arena_fight(game, [Beast("dimwisp", 8)], "T", "Tester")
assert "Nobody else is standing to swap in." in ANSI.sub("", out.getvalue())
print("swap with nobody else standing: says so, no turn lost OK")

# ---- battle log: only this turn's events; a KO and its replacement on one line ----
out = io.StringIO()
with contextlib.redirect_stdout(out):
    arena._turn_log(["Tadpearl's Deluge missed.", "old line", "Tadpearl used Tide Pull.", "  Cairnhorn lost 9 HP."], 2)
shown = ANSI.sub("", out.getvalue())
assert "Tide Pull" in shown and "Deluge missed" not in shown, shown   # last turn's miss is gone
log = ["Haarscale is out of the fight!"]
arena._down_then(log, "Haarscale", "Undra sends out Moatshell!", "Undra sends out Moatshell!")
assert log == ["Haarscale is down -- Undra sends out Moatshell!"], log
wide = "Ember & Bloom's Keeper sends out Thunderwing!"
log = ["Orchidreign is out of the fight!"]
arena._down_then(log, "Orchidreign", wide, wide)
assert log == ["Orchidreign is out of the fight!", wide], log            # too wide to merge
assert arena.LOG_ROWS == 4

# an AI switch names who left as well as who came in
game = circuit.CircuitGame("t", "Bronze")
mine = Beast("cragjaw", 30); arena.prepare(mine)
game.party = [mine]
foes = [Beast("dimwisp", 8), Beast("wickling", 8)]
calls = {"n": 0}
def switch_once(f, m, team, idx, memo):
    calls["n"] += 1
    if calls["n"] == 1:
        return ("switch", 1)
    return ("move", next(x for x in f.moves if MOVES[x]["power"] > 0))
arena.ai_decide = switch_once
asks = iter([1] * 300)
ts.ask_int = lambda *a, **k: next(asks)
random.seed(2)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    arena.arena_fight(game, foes, "T", "Tester")
assert "Tester swaps Dimwisp for Wickling!" in ANSI.sub("", out.getvalue())
print("battle log: this turn only; 'X is down -- Y sends out Z!'; AI swaps name who left OK")
print("ALL ROUND-3 TESTS PASSED")
