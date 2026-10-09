"""Whole District runs, economy included: real arena fights (arena.arena_fight),
real prizes (circuit.round_prize + clean bonus), starting coins 150, and the
Infirmary between rounds. Every combat policy gets the SAME spending policy,
so any gap between them is combat skill, not shopping.
usage: python3 games/beastling/sim/district_sim.py RUNS [pricing,...]   pricing: none | old | new
  none -- no healing between rounds; old -- the pre-v2 all-or-nothing revive; new -- the live prices"""
import os, sys, collections, io, contextlib, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policies as A                       # policies + ts.ask_int/menu wiring (sets up the game path)
import arena, circuit
from main import Beast
from tournament import generate_bracket


def old_prices(b, rnd):
    """The pre-v2 Infirmary, per beast (revive was only sold as a package)."""
    mult = 1 + 0.25 * rnd
    if not b.alive:
        return {"hp": 0, "pp": 0, "revive": int(160 * mult)}
    pp_low = any(b.pp[m] < arena.move_pp(m) for m in b.moves)
    return {"hp": int((8 + (b.max_hp - b.hp) // 3) * mult) if b.hp < b.max_hp else 0,
            "pp": int(14 * mult) if pp_low else 0, "revive": 0}


def spend(party, coins, rnd, pricing):
    """Revive first (strongest first), then heal the most hurt, then PP."""
    if pricing == "none":
        return coins, 0
    spent = 0
    if pricing == "old":                                    # all-or-nothing package
        down = [b for b in party if not b.alive]
        cost = sum(old_prices(b, rnd)["revive"] for b in down)
        if down and coins >= cost:
            coins -= cost; spent += cost
            for b in down:
                circuit.apply_treatment(b, "revive")
        price_of = old_prices
    else:
        price_of = circuit.treatment_prices
        for b in sorted((b for b in party if not b.alive), key=lambda b: -(b.max_hp + b.atk + b.dfn + b.spd)):
            c = price_of(b, rnd)["revive"]
            if coins >= c:
                coins -= c; spent += c
                circuit.apply_treatment(b, "revive")
    for kind, order in (("hp", lambda b: b.hp / b.max_hp), ("pp", lambda b: 0)):
        for b in sorted((b for b in party if b.alive), key=order):
            c = price_of(b, rnd)[kind]
            if c and coins >= c:
                coins -= c; spent += c
                circuit.apply_treatment(b, kind)
    return coins, spent


def run_one(policy, seed, pricing):
    rng = random.Random(seed)
    squad = rng.sample(A.EVOLVED, 6)
    game = circuit.CircuitGame("sim", "Bronze")
    game.party = [Beast(s, circuit.DRAFT_LEVEL) for s in squad]
    for b in game.party:
        arena.prepare(b)
    A.S.update(game=game, policy=A.POL[policy]())
    random.seed(seed * 7 + 1)
    bracket = generate_bracket(circuit.DRAFT_LEVEL, random.Random(seed), level_offset=-2)
    coins, spent, reached = 150, 0, 0
    for i, rival in enumerate(bracket):
        if not game.healthy():
            break
        down_before = sum(1 for b in game.party if not b.alive)
        team = [Beast(s, lv) for s, lv in rival["team"]]
        with contextlib.redirect_stdout(io.StringIO()):
            result = arena.arena_fight(game, team, "r", rival["name"])
        if result != "won":
            break
        reached = i + 1
        clean = sum(1 for b in game.party if not b.alive) == down_before
        coins += circuit.round_prize(i) + (25 if clean else 0)
        if reached < len(bracket):
            coins, s = spend(game.party, coins, reached, pricing)
            spent += s
    return reached, spent


def guarded(policy, seed, pricing):
    """A run that loops (a policy bug) is reported, not left to hang the batch."""
    import signal

    def alarm(*_):
        raise TimeoutError
    signal.signal(signal.SIGALRM, alarm)
    signal.alarm(60)
    try:
        return run_one(policy, seed, pricing)
    except TimeoutError:
        print(f"  !! {pricing}/{policy} seed {seed} hung -- counted as round 0", file=sys.stderr, flush=True)
        return 0, 0
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    PRICINGS = sys.argv[2].split(",") if len(sys.argv) > 2 else ["none", "old", "new"]
    print(f"{RUNS} runs per cell; identical squads/brackets per seed; foes at level offset -2")
    for pricing in PRICINGS:
        for policy in ("spam", "greedy", "smart"):
            res = [guarded(policy, s, pricing) for s in range(RUNS)]
            dist = collections.Counter(r for r, _ in res)
            avg = sum(r for r, _ in res) / RUNS
            spent = sum(s for _, s in res) / RUNS
            print(f"{pricing:<5} {policy:<7} avg rounds {avg:4.2f}/6  clears {dist[6]:3d}/{RUNS}  "
                  f"avg spent {spent:5.0f}c | " + " ".join(f"{k}:{dist[k]}" for k in range(7)), flush=True)
