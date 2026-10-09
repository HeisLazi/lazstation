"""Arena rules -- the Tournament's own combat.

Why this exists as its own module: measured against the story battle(), a bot
that just spams the strongest move did exactly as well as one that thinks,
because every beast's moves were one type ranked by power, switching never paid
for itself, the AI only ever attacked, and nothing carried over between fights.
These rules fix that in the one place it matters (the Tournament), and leave
Story's battle() alone.

What's different here:
  - A trainer fights with a WHOLE TEAM in one battle: when a beast faints the
    next comes in, and the AI will switch a beast out of a bad matchup.
  - Every move has PP and it does NOT refill between rounds. Big moves are few.
  - Each beast's kit is 2 attacks of its own type, 1 coverage attack of another
    type, and 1 support move (heal / setup / protect / status / debuff).
  - The AI heals, sets up, braces and debuffs instead of only attacking.
  - After a faint you CHOOSE who comes in (free), instead of the first in line.
  - Damage is higher, so a bad matchup costs real HP.
"""
from __future__ import annotations

import random

import termstation_sdk as ts
from beasts import (ARENA_COVERAGE, ARENA_SUPPORT, MOVES, SPECIES, WEATHER_DESC,
                    WEATHER_DURATION)
from main import (STAGE_NAME, Beast, apply_ability_on_hit, apply_move_effect, beast_line,
                  check_mending_berry, check_vengeful, damage, deal_damage, effect_word,
                  effectiveness, may_act, resolve_status_upkeep, show_log)

ARENA_DAMAGE = 1.25          # global damage multiplier: mistakes must cost HP
#: Type effectiveness is raised to this power in the Arena (2.0 -> 2.46,
#: 0.5 -> 0.41 at 1.3). A wider spread makes knowing the matchup matter more
#: than raw stats, which is exactly what spamming one move ignores.
ARENA_TYPE_POWER = 1.3


def _type_factor(move_type: str, defender_type: str) -> float:
    return effectiveness(move_type, defender_type) ** (ARENA_TYPE_POWER - 1.0)
#: The fight in progress, readable by tests/simulators that need to see the
#: foe the player is facing (the prompt functions don't carry it).
CURRENT: dict = {}


# ------------------------------------------------------------------- kits / PP
def move_pp(move: str) -> int:
    spec = MOVES[move]
    p = spec["power"]
    if p == 0:
        kind = spec["effect"][0]
        return {"heal": 5, "heal_cure": 5, "protect": 6, "multi": 8, "status": 10}.get(kind, 8)
    if p <= 45:
        return 25
    if p <= 70:
        return 14
    if p <= 85:
        return 9
    return 5


def build_kit(slug: str) -> list[str]:
    """2 own-type attacks (best two it knows at 30), 1 coverage, 1 support."""
    typ = SPECIES[slug]["type"]
    known = [m for m in Beast(slug, 30).moves if MOVES[m]["power"] > 0 and MOVES[m]["type"] == typ]
    known.sort(key=lambda m: -MOVES[m]["power"])
    kit = known[:2]
    for filler in ("Rock Toss", "Tackle", "Scratch"):
        if len(kit) < 2 and filler not in kit:
            kit.append(filler)
    cov = ARENA_COVERAGE[typ]
    # About half the roster carries a coverage attack (a stable pick per
    # species). If everyone covered their own weakness, counter-picking would
    # be pointless; with half, it is a read: does THIS one have coverage?
    if sum(map(ord, slug)) % 2 == 0 and cov not in kit:
        kit.append(cov)
    else:
        for filler in ("Rock Toss", "Tackle", "Scratch"):
            if filler not in kit and len(kit) < 3:
                kit.append(filler)
    kit.append(ARENA_SUPPORT[typ])
    return kit[:4]


def leave_field(b: Beast) -> None:
    """Stat stages reset when a beast switches out -- otherwise setup could be
    banked for free, and switching would never answer a boosted sweeper."""
    b.atk_stage = b.def_stage = b.spd_stage = 0
    b.protect_streak, b.protected = 0, False


def prepare(b: Beast) -> None:
    """Give a beast its arena kit and full PP. Idempotent: PP persists once
    set, which is the whole point -- call restore_pp to refill it."""
    if getattr(b, "pp", None) is None:
        b.moves = build_kit(b.slug)
        b.pp = {m: move_pp(m) for m in b.moves}
        b.protect_streak = 0
        b.protected = False


def restore_pp(b: Beast, amount: int | None = None) -> None:
    for m in b.moves:
        full = move_pp(m)
        b.pp[m] = full if amount is None else min(full, b.pp.get(m, 0) + amount)


def usable_moves(b: Beast) -> list[str]:
    return [m for m in b.moves if b.pp.get(m, 0) > 0] or ["Struggle"]


def kind_of(move: str) -> str | None:
    e = MOVES[move]["effect"]
    return e[0] if MOVES[move]["power"] == 0 and e else None


_STAT = {"atk": "Atk", "def": "Def", "spd": "Spd"}
_MAY = {"burn": "burn", "sleep": "put to sleep", "paralyze": "paralyze", "poison": "poison",
        "confused": "confuse"}
_DOES = {"burn": "burns the foe", "sleep": "puts the foe to sleep", "paralyze": "paralyzes the foe",
         "poison": "poisons the foe", "confused": "confuses the foe"}


def effect_text(move: str) -> str:
    """What a move does, in mechanics rather than flavour -- for the squad
    card, where the choice of who to bring hangs on it."""
    spec = MOVES[move]
    e, bits = spec["effect"], []

    def pct(x: float) -> str:
        return f"{round(x * 100)}%"

    def stages(changes) -> str:
        who = "you" if changes[0][2] == "self" else "foe"
        return who + " " + ", ".join(f"{_STAT[s]} {d:+d}" for s, d, _ in changes)

    if spec["priority"] > 0 and spec["power"] > 0:
        bits.append("strikes first")
    if e:
        kind = e[0]
        if kind == "status":
            bits.append(_DOES.get(e[1], e[1]) if e[2] >= 1 else f"may {_MAY.get(e[1], e[1])} ({pct(e[2])})")
        elif kind == "stage":
            bits.append(stages([(e[1], e[2], e[3])]) + ("" if e[4] >= 1 else f" ({pct(e[4])})"))
        elif kind == "multi":
            bits.append(stages(e[1]))
        elif kind == "heal":
            bits.append(f"heals {pct(e[1])} HP")
        elif kind == "heal_cure":
            bits.append(f"heals {pct(e[1])} HP, cures status")
        elif kind == "protect":
            bits.append("blocks the next hit; less sure if used twice running")
        elif kind == "recoil":
            bits.append(f"{pct(e[1])} recoil")
    if spec.get("sets_weather"):
        bits.append(f"brings {spec['sets_weather']}")
    return "; ".join(bits)


def expected_damage(att: Beast, de: Beast, move: str) -> float:
    """What the damage formula gives on average (no randomness), as HP."""
    spec = MOVES[move]
    if spec["power"] == 0:
        return 0.0
    mult = effectiveness(spec["type"], de.type) * _type_factor(spec["type"], de.type) \
        * (1.25 if spec["type"] == att.type else 1.0)
    base = ((2 * att.level / 5 + 2) * spec["power"] * att.eff_atk / max(1, de.eff_def)) / 26
    return (base + 2) * mult * 0.925 * ARENA_DAMAGE * spec["accuracy"] / 100


def threat(att: Beast, de: Beast) -> float:
    """Best expected hit from att, as a fraction of de's CURRENT hp."""
    best = max((expected_damage(att, de, m) for m in usable_moves(att)), default=0.0)
    return best / max(1.0, de.hp)


# ---------------------------------------------------------------------- the AI
def ai_decide(foe: Beast, me: Beast, team: list[Beast], idx: int, memo: dict) -> tuple:
    """('move', name) or ('switch', team_index). Not a perfect player -- it
    reads the matchup, protects its HP, sets up when safe, and mixes in
    support moves -- but it is no longer a bot that only presses attack."""
    r = random.random
    usable = usable_moves(foe)
    attacks = [m for m in usable if MOVES[m]["power"] > 0]
    support = {kind_of(m): m for m in usable if kind_of(m)}
    mine, theirs = threat(foe, me), threat(me, foe)
    cd = memo.get("cooldown", 0)
    memo["cooldown"] = max(0, cd - 1)

    # leave a bad matchup (they can hurt me a lot, I can't hurt them back)
    if cd == 0 and theirs >= 0.40 and mine < theirs * 0.75:
        bench = [(threat(b, me) - 0.6 * threat(me, b), j) for j, b in enumerate(team)
                 if b.alive and j != idx]
        if bench:
            gain, j = max(bench)
            if gain > mine - 0.1 and r() < 0.65:
                memo["cooldown"] = 3
                return ("switch", j)
    boosted = me.atk_stage >= 2 or me.spd_stage >= 2
    if boosted:
        if cd == 0 and r() < 0.5:                  # reset it by switching to a fresh beast
            bench = [(threat(b, me) - 0.6 * threat(me, b), j) for j, b in enumerate(team)
                     if b.alive and j != idx]
            if bench:
                memo["cooldown"] = 2
                return ("switch", max(bench)[1])
        if "protect" in support and foe.protect_streak == 0 and r() < 0.45:
            return ("move", support["protect"])
        if "multi" in support and any(w == "foe" for _, _, w in MOVES[support["multi"]]["effect"][1]) \
                and r() < 0.5:
            return ("move", support["multi"])
    healer = support.get("heal") or support.get("heal_cure")
    if healer and foe.hp < 0.42 * foe.max_hp and theirs < 0.9 and r() < 0.8:
        return ("move", healer)
    if "protect" in support and foe.protect_streak == 0 and theirs >= 0.35 and r() < 0.30:
        return ("move", support["protect"])
    if "multi" in support and foe.hp > 0.6 * foe.max_hp and theirs < 0.45 and r() < 0.45:
        spec = MOVES[support["multi"]]["effect"][1]
        # don't stack the same buff/debuff past +-2
        if all(abs(getattr(me if who == "foe" else foe, f"{stat}_stage")) < 2 for stat, _, who in spec):
            return ("move", support["multi"])
    if "status" in support and me.status is None and me.alive and r() < 0.45 and theirs < 0.7:
        return ("move", support["status"])
    if not attacks:
        return ("move", "Struggle")
    weights = [max(0.05, expected_damage(foe, me, m)) ** 2 for m in attacks]
    return ("move", random.choices(attacks, weights=weights, k=1)[0])


# ----------------------------------------------------------------- one action
def _stage(who: Beast, stat: str, delta: int) -> str | None:
    field = f"{stat}_stage"
    before = getattr(who, field)
    after = max(-3, min(3, before + delta))
    setattr(who, field, after)
    if after == before:
        return None
    return f"  {who.name}'s {STAGE_NAME[stat]} {'rose' if after > before else 'fell'}!"


def use_move(att: Beast, de: Beast, mv: str, weather: str | None) -> tuple[list[str], str | None]:
    """Resolve one move. Returns (log lines, weather_set_or_None)."""
    lines: list[str] = []
    if mv != "Struggle":
        att.pp[mv] = att.pp.get(mv, 1) - 1
    spec = MOVES[mv]
    kind = kind_of(mv)
    set_weather = None

    if kind == "protect":
        if random.random() < 0.5 ** att.protect_streak:
            att.protected = True
            att.protect_streak += 1
            lines.append(f"{att.name} used {mv}. It braces!")
        else:
            att.protect_streak = 0
            lines.append(f"{att.name} used {mv}. But it failed.")
        return lines, None
    att.protect_streak = 0
    if kind in ("heal", "heal_cure"):
        got = min(att.max_hp - att.hp, int(att.max_hp * spec["effect"][1]))
        att.hp += got
        lines.append(f"{att.name} used {mv}. It recovered {got} HP.")
        if kind == "heal_cure" and att.status:
            att.status, att.status_turns = None, 0
            lines.append(f"  {att.name} shakes off its ailment.")
        return lines, None
    if kind == "multi":
        lines.append(f"{att.name} used {mv}.")
        if random.randint(1, 100) > spec["accuracy"]:
            lines.append("  It missed.")
            return lines, None
        for stat, delta, who in spec["effect"][1]:
            target = att if who == "self" else de
            if who == "foe" and delta < 0 and target.ability == "Unshaken":
                lines.append(f"  {target.name}'s Unshaken holds its stats steady!")
                continue
            if who == "foe" and de.protected:
                continue
            line = _stage(target, stat, delta)
            if line:
                lines.append(line)
        return lines, None
    if kind == "status":
        lines.append(f"{att.name} used {mv}.")
        if de.protected:
            lines.append(f"  {de.name} protected itself!")
        elif random.randint(1, 100) > spec["accuracy"]:
            lines.append("  It missed.")
        else:
            lines.extend(apply_move_effect(att, de, mv) or ["  It had no effect."])
        return lines, None

    # ---- an attack
    if de.protected:
        lines.append(f"{att.name} used {mv}. {de.name} protected itself!")
        return lines, None
    dealt, mult, hit, crit = damage(att, de, mv, weather,
                                    dmg_mult=ARENA_DAMAGE * _type_factor(spec["type"], de.type))
    if not hit:
        lines.append(f"{att.name}'s {mv} missed.")
        return lines, None
    note = effect_word(mult)
    if crit:
        note = ("A critical hit! " + note).strip()
    lines.append(f"{att.name} used {mv}. {note}".strip())
    lines.append(f"  {de.name} lost {min(dealt, de.hp)} HP.")
    lines.extend(deal_damage(att, de, dealt))
    if spec["sets_weather"]:
        set_weather = spec["sets_weather"]
    if mv == "Struggle":
        cost = max(1, int(dealt * 0.25))
        att.hp = max(0, att.hp - cost)
        lines.append(f"  {att.name} is hurt by the recoil. ({cost} HP)")
    if de.alive and spec["effect"] and spec["effect"][0] in ("status", "stage"):
        lines.extend(apply_move_effect(att, de, mv))
    lines.extend(apply_ability_on_hit(att, de))
    lines.extend(check_vengeful(de))
    lines.extend(check_mending_berry(de))
    return lines, set_weather


# ------------------------------------------------------------------ arena items
ARENA_ITEMS = {
    "Potion": {"desc": "Heals 40 HP.", "heal": 40, "price": 40},
    "Super Potion": {"desc": "Heals 120 HP.", "heal": 120, "price": 110},
    "Full Heal": {"desc": "Cures a status ailment.", "cure": True, "price": 70},
    "Revive": {"desc": "Revives a beast at half HP.", "revive": 0.5, "price": 260},
    "Ether": {"desc": "Restores 10 PP to every move.", "pp": 10, "price": 150},
}


def bag_has_items(game) -> bool:
    return any(game.inventory.get(n, 0) > 0 for n in ARENA_ITEMS)


def item_menu(game, log: list[str] | None) -> bool:
    """Choose an item then a beast. Returns True if one was used (costs the
    turn in a fight). `log` is None between rounds."""
    def say(msg):
        if log is not None:
            log.append(msg)
        else:
            ts.tv_print(f"  {msg}")
            ts.tv_pause()

    stock = [n for n in ARENA_ITEMS if game.inventory.get(n, 0) > 0]
    if not stock:
        say("Your bag is empty.")
        return False
    ts.tv_clear()
    pick = ts.menu("Use which item?",
                   [f"{n} x{game.inventory[n]}  -- {ARENA_ITEMS[n]['desc']}" for n in stock],
                   back="Cancel")
    if pick == -1:
        return False
    name = stock[pick]
    spec = ARENA_ITEMS[name]
    ts.tv_clear()
    who = ts.menu(f"{name} on which beast?",
                  [f"{b.name}  {b.hp}/{b.max_hp} HP" + ("  (down)" if not b.alive else "")
                   + (f"  {b.status}" if b.status else "") for b in game.party], back="Cancel")
    if who == -1:
        return False
    b = game.party[who]
    if "revive" in spec:
        if b.alive:
            say(f"{b.name} isn't down.")
            return False
        b.hp = max(1, int(b.max_hp * spec["revive"]))
        b.reset_combat_state()
        msg = f"{b.name} is back on its feet!"
    elif not b.alive:
        say(f"{b.name} needs a Revive.")
        return False
    elif "heal" in spec:
        if b.hp >= b.max_hp:
            say(f"{b.name} is already at full health.")
            return False
        got = min(spec["heal"], b.max_hp - b.hp)
        b.hp += got
        msg = f"{b.name} recovered {got} HP."
    elif spec.get("cure"):
        if not b.status:
            say(f"{b.name} has nothing to cure.")
            return False
        b.status, b.status_turns = None, 0
        msg = f"{b.name} shakes it off."
    else:                                            # Ether
        restore_pp(b, spec["pp"])
        msg = f"{b.name}'s moves are restored."
    game.inventory[name] -= 1
    if game.inventory[name] <= 0:
        del game.inventory[name]
    if log is not None:
        log.append(msg)
    else:
        ts.tv_print(f"  {msg}")
        ts.tv_pause()
    return True


# --------------------------------------------------------------------- the fight
def _bench_pick(team: list[Beast], me: Beast) -> int | None:
    alive = [(threat(b, me) - 0.5 * threat(me, b), j) for j, b in enumerate(team) if b.alive]
    return max(alive)[1] if alive else None


def arena_fight(game, team: list[Beast], title: str, trainer: str) -> str:
    """One rival's whole team vs. your squad. Returns 'won' or 'lost'."""
    for b in list(game.party) + team:
        prepare(b)
        b.reset_combat_state()
        b.protected, b.protect_streak = False, 0
    idx = 0
    log = [f"{trainer} sends out {team[0].name}!"]
    weather, wturns = None, 0
    memo: dict = {}
    prev_me: Beast | None = None

    while True:
        me = game.lead()
        if me is None:
            return "lost"
        foe = team[idx]
        CURRENT["foe"], CURRENT["team"] = foe, team
        if prev_me is not None and not prev_me.alive:
            # Your beast went down: you choose who comes in, for free. The
            # menu wipes the battle screen, so it repeats what just happened
            # first -- a bare "send out which beast?" read as a glitch.
            if len(game.healthy()) >= 2:
                game.swap_menu(forced=True, heading=f"{prev_me.name} is down -- send out who?",
                               lines=[*(f"  {line}" for line in log[-4:]), "",
                                      f"  Facing {foe.name} ({foe.type})  {foe.hp}/{foe.max_hp} HP"])
                me = game.lead()
            log.append(f"You send out {me.name}!")
        prev_me = me
        weather_set_this_turn = False
        log.extend(check_vengeful(me))
        log.extend(check_vengeful(foe))

        n = len(me.moves)
        forced = all(me.pp.get(m, 0) <= 0 for m in me.moves)
        game.header(f"{title}  ({sum(1 for b in team if b.alive)} left)")
        for line in beast_line(foe):
            ts.tv_print(line)
        for line in beast_line(me):
            ts.tv_print(line)
        if weather:
            ts.tv_print(ts.color(f"   {weather} ({wturns} left) -- {WEATHER_DESC[weather]}",
                                 "bright_yellow"))
        else:
            ts.tv_print(ts.rule("─"))
        show_log(log, keep=3)
        ts.tv_print(ts.rule("─"))
        for i, m in enumerate(me.moves, 1):
            spec = MOVES[m]
            left, full = me.pp.get(m, 0), move_pp(m)
            power = "supp" if spec["power"] == 0 else f"pow{spec['power']:>3}"
            tag = (" quick" if spec["priority"] > 0 and spec["power"] > 0 else "")
            col = "grey" if left <= 0 else "bright_cyan"
            eff = effectiveness(spec["type"], foe.type) if spec["power"] > 0 else 1.0
            mark = (ts.color(" ▲", "bright_green") if eff >= 2 else
                    ts.color(" ▼", "bright_red") if eff <= 0.5 else "")
            ts.tv_print(f"   {ts.color(str(i), col)}  {m.ljust(11)} {spec['type'].ljust(5)} "
                        f"{power} acc{spec['accuracy']:>3} pp{left:>2}/{full:<2}{tag}{mark}")
        has_items = bag_has_items(game)
        tail = f"   {ts.color(str(n + 1), 'bright_cyan')}  swap"
        if has_items:
            tail += f"    {ts.color(str(n + 2), 'bright_cyan')}  item"
        ts.tv_print(tail)

        # ---- the player's choice
        if forced:
            log.append(f"{me.name} has no PP left!")
            mine = ("move", "Struggle")
        else:
            choice = ts.ask_int("your move", 1, n + (2 if has_items else 1))
            if choice <= n:
                if me.pp.get(me.moves[choice - 1], 0) <= 0:
                    log.append("No PP left for that move!")
                    continue
                mine = ("move", me.moves[choice - 1])
            elif choice == n + 1:
                old = me
                if not game.swap_menu(lines=[
                        f"  Facing {foe.name} ({foe.type})  {foe.hp}/{foe.max_hp} HP",
                        "  Swapping uses your turn -- the foe still acts."]):
                    continue
                leave_field(old)
                # prev_me must follow the swap: it is how the next turn knows
                # whose faint to ask about. Left on the old beast, a newcomer
                # KO'd on the switch-in brought the old one back with no
                # menu and no message (found by an LLM playtester).
                me = prev_me = game.lead()
                log.append(f"You send out {me.name}!")
                mine = ("swapped",)
            else:
                if not item_menu(game, log):
                    continue
                mine = ("item",)

        # ---- the foe's choice; a switch happens before any attack lands
        theirs = ai_decide(foe, me, team, idx, memo)
        if theirs[0] == "switch":
            leave_field(foe)
            idx = theirs[1]
            foe = team[idx]
            for b in (me, foe):
                b.protected = False
            log.append(f"{trainer} sends out {foe.name}!")
            theirs = ("swapped",)

        actions = []
        if mine[0] == "move":
            actions.append((me, foe, mine[1]))
        if theirs[0] == "move":
            actions.append((foe, me, theirs[1]))
        actions.sort(key=lambda a: (-MOVES[a[2]]["priority"], -a[0].eff_spd))
        for att, de, mv in actions:
            if not att.alive or (not de.alive and MOVES[mv]["power"] > 0):
                continue
            ok, status_lines = may_act(att)
            log.extend(status_lines)
            if not ok:
                continue
            lines, new_weather = use_move(att, de, mv, weather)
            log.extend(lines)
            if new_weather:
                fresh = new_weather != weather
                weather, wturns, weather_set_this_turn = new_weather, WEATHER_DURATION, True
                log.append(f"  {new_weather} " + ("rolls in!" if fresh else "holds."))
            if not de.alive:
                log.append(f"{de.name} is out of the fight!")
            if not att.alive:
                log.append(f"{att.name} is out of the fight!")
        for b in (me, foe):
            if b.alive:
                log.extend(resolve_status_upkeep(b))
            b.protected = False
        if weather and not weather_set_this_turn:
            wturns -= 1
            if wturns <= 0:
                log.append(f"  {weather} fades.")
                weather = None

        if not foe.alive:
            nxt = _bench_pick(team, me)
            if nxt is None:
                return "won"
            idx = nxt
            memo["cooldown"] = 0
            log.append(f"{trainer} sends out {team[idx].name}!")
