import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-test-"))
import sys, os, random
sys.path.insert(0, os.path.join(ROOT, "sdk"))
sys.path.insert(0, os.path.join(ROOT, "games", "beastling"))
import termstation_sdk as ts
from main import (Beast, may_act, apply_move_effect, STATUS_DURATION,
                   STATUS_VERB, STATUS_TAG, beast_line)

# --- apply_move_effect wires up sleep correctly ---
random.seed(1)
attacker = Beast("cindermole", 20)
defender = Beast("sproutling", 20)
random.random = lambda: 0.0  # force the status-chance roll to succeed
lines = apply_move_effect(attacker, defender, "Seed Volley")
assert defender.status == "sleep", defender.status
assert 1 <= defender.status_turns <= 3, defender.status_turns
assert any("falls asleep" in l for l in lines), lines
print("apply_move_effect(sleep): OK, turns =", defender.status_turns)

# --- apply_move_effect wires up confused correctly ---
defender2 = Beast("sproutling", 20)
lines2 = apply_move_effect(attacker, defender2, "Duskwave")
assert defender2.status == "confused", defender2.status
assert 2 <= defender2.status_turns <= 4, defender2.status_turns
assert any("becomes confused" in l for l in lines2), lines2
print("apply_move_effect(confused): OK, turns =", defender2.status_turns)

# --- can't double-apply a status onto an already-statused beast ---
defender.status_turns = 2
lines3 = apply_move_effect(attacker, defender, "Duskwave")
assert defender.status == "sleep"  # unchanged
assert lines3 == []
print("no-double-status: OK")

# --- sleep guarantees a skipped turn for exactly status_turns turns, then wakes ---
b = Beast("sproutling", 20)
b.status = "sleep"
b.status_turns = 3
seen_wake = False
for i in range(3):
    can_act, lines = may_act(b)
    if i < 2:
        assert can_act is False, f"turn {i}: expected asleep, got can_act={can_act}"
        assert "fast asleep" in lines[0], lines
    else:
        assert can_act is True, f"turn {i}: expected wake, got can_act={can_act}"
        assert "wakes up" in lines[0], lines
        assert b.status is None
        seen_wake = True
assert seen_wake
print("sleep-duration: OK (skipped 2 turns, woke on 3rd without losing that turn)")

# --- paralyze unchanged: real chance to no-sell a turn ---
p = Beast("sproutling", 20)
p.status = "paralyze"
random.random = lambda: 0.0  # force the 25% roll to hit
can_act, lines = may_act(p)
assert can_act is False
assert "fully paralyzed" in lines[0]
random.random = lambda: 0.99  # force it to miss
can_act, lines = may_act(p)
assert can_act is True and lines == []
print("paralyze-unchanged: OK")

# --- confusion: self-hit chance, wears off after status_turns, "snaps out" message survives ---
c = Beast("sproutling", 20)
c.status = "confused"
c.status_turns = 1
random.random = lambda: 0.99  # keep self-hit from firing even if checked
can_act, lines = may_act(c)
assert can_act is True, lines
assert c.status is None
assert any("snaps out of its confusion" in l for l in lines), lines
print("confusion-wake-message: OK (the fallthrough bug is fixed)", lines)

c2 = Beast("sproutling", 20)
c2.status = "confused"
c2.status_turns = 2
random.random = lambda: 0.0  # force the self-hit to fire
can_act, lines = may_act(c2)
assert can_act is False
assert c2.status == "confused"  # still confused, just took a self-hit
assert c2.status_turns == 1
assert any("hurt itself" in l for l in lines), lines
print("confusion-self-hit: OK,", lines)

# --- confusion self-hit can faint the beast, and that's reflected in the lines ---
c3 = Beast("sproutling", 5)
c3.status = "confused"
c3.status_turns = 5
c3.hp = 1
random.random = lambda: 0.0
can_act, lines = may_act(c3)
assert can_act is False
assert c3.hp == 0
assert not c3.alive
assert any("out of the fight" in l for l in lines), lines
print("confusion-self-hit-faint: OK,", lines)

# --- reset_combat_state clears status_turns ---
r = Beast("sproutling", 20)
r.status = "sleep"
r.status_turns = 3
r.reset_combat_state()
assert r.status is None and r.status_turns == 0
print("reset_combat_state: OK")

# --- STATUS_TAG has all four, beast_line doesn't KeyError on sleep/confused ---
for status in ("burn", "paralyze", "sleep", "confused"):
    assert status in STATUS_TAG, status
    b2 = Beast("sproutling", 20)
    b2.status = status
    lines = beast_line(b2)
    assert any(STATUS_TAG[status][0] in l for l in lines), (status, lines)
print("STATUS_TAG + beast_line: OK, all four render without crashing")

# --- STATUS_DURATION / STATUS_VERB wiring ---
assert STATUS_DURATION == {"sleep": (1, 3), "confused": (2, 4)}
assert set(STATUS_VERB) == {"burn", "paralyze", "sleep", "confused"}
print("STATUS_DURATION/STATUS_VERB: OK")

print("ALL STATUS CONDITION TESTS PASSED")
