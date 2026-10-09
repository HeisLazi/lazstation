"""Scripted combat policies for measuring Tournament depth, run through the
real game code (arena.arena_fight). The success metric: smart >> greedy >> spam;
if the three tie, the combat has no decisions in it.

  python3 games/beastling/sim/policies.py RUNS [spam,greedy,smart]   # no healing between rounds
  (district_sim.py adds the economy: prizes, coins and the Infirmary)

Importing this module wires ts.ask_int / ts.menu to the active policy."""
import sys, os, io, random, contextlib, collections, tempfile
os.environ.setdefault("TERMSTATION_SAVE_DIR", tempfile.mkdtemp(prefix="beastling-sim-"))
os.environ["COLUMNS"] = "80"; os.environ["LINES"] = "30"
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, ROOT + "/sdk"); sys.path.insert(0, ROOT + "/games/beastling")
import termstation_sdk as ts
import main as M
from main import Beast
from beasts import SPECIES, MOVES
import arena
import circuit
from arena import expected_damage, threat, usable_moves, kind_of
from tournament import generate_bracket

ts.tv("sim")
ts.tv_pause = lambda *a, **k: None
EVOLVED = sorted({d["evolve"][1] for d in SPECIES.values() if d["evolve"]})
S = {"game": None, "policy": None}
CUR = arena.CURRENT


def any_pp(me):
    """No attack has PP left: use whatever still has PP (a support move),
    the way a player would, until Struggle is forced."""
    for i, m in enumerate(me.moves, 1):
        if me.pp.get(m, 0) > 0:
            return i
    return 1


class Spam:
    """Strongest raw-power move, every turn. Ignores everything else."""
    def act(self, game, foe, me, n):
        mv = max((m for m in me.moves if me.pp.get(m, 0) > 0 and MOVES[m]["power"] > 0),
                 key=lambda m: MOVES[m]["power"], default=None)
        return me.moves.index(mv) + 1 if mv else any_pp(me)

    def swap(self, game, foe, options):
        return self.best_replacement(game, foe)

    def best_replacement(self, game, foe):
        alive = [i for i, b in enumerate(game.party) if b.alive]
        return alive[0] if alive else -1


class Greedy(Spam):
    """Highest expected damage into the current foe; one ply, no memory."""
    def act(self, game, foe, me, n):
        mv = max((m for m in me.moves if me.pp.get(m, 0) > 0 and MOVES[m]["power"] > 0),
                 key=lambda m: expected_damage(me, foe, m), default=None)
        return me.moves.index(mv) + 1 if mv else any_pp(me)


class Smart(Greedy):
    """Reads the matchup: heals when low, sets up / debuffs when safe, braces
    against a big hit, switches out of bad matchups, picks the best beast to
    send in after a faint, and saves its strongest move for when it matters."""
    def __init__(self):
        self.pending = None

    def best_replacement(self, game, foe):
        scored = [(threat(b, foe) - 0.6 * threat(foe, b) + 0.2 * b.hp / b.max_hp, i)
                  for i, b in enumerate(game.party) if b.alive]
        return max(scored)[1] if scored else -1

    def act(self, game, foe, me, n):
        sup = {kind_of(m): m for m in me.moves if kind_of(m) and me.pp.get(m, 0) > 0}
        mine, theirs = threat(me, foe), threat(foe, me)
        healer = sup.get("heal") or sup.get("heal_cure")
        # 1. leave a lost matchup (cheap bench with a clearly better trade)
        if theirs >= 0.40 and mine < theirs * 0.75:
            options = [(threat(b, foe) - 0.6 * threat(foe, b), i)
                       for i, b in enumerate(game.party) if b.alive and b is not me]
            if options:
                gain, i = max(options)
                if gain > mine - 0.05:
                    self.pending = i
                    return n + 1
        # 2. heal before a KO if it buys a turn
        if healer and me.hp < 0.45 * me.max_hp and theirs < 1.0:
            return me.moves.index(healer) + 1
        # 3. brace into a big hit (then the foe's move is wasted)
        if "protect" in sup and theirs >= 0.5 and me.protect_streak == 0 and mine < 0.5:
            return me.moves.index(sup["protect"]) + 1
        # 4. set up / debuff / status when it is safe
        if theirs < 0.40 and me.hp > 0.6 * me.max_hp and foe.hp > 0.5 * foe.max_hp:
            if "multi" in sup:
                spec = MOVES[sup["multi"]]["effect"][1]
                if all(abs(getattr(me if w == "self" else foe, f"{s}_stage")) < 2 for s, _, w in spec):
                    return me.moves.index(sup["multi"]) + 1
            if "status" in sup and foe.status is None:
                return me.moves.index(sup["status"]) + 1
        # 5. otherwise the best attack, sparing the 5-9 PP moves on weak foes
        pool = [m for m in me.moves if me.pp.get(m, 0) > 0 and MOVES[m]["power"] > 0]
        if not pool:
            return any_pp(me)
        def value(m):
            d = expected_damage(me, foe, m)
            scarce = arena.move_pp(m) <= 9 and me.pp[m] <= 3 and foe.hp < 0.35 * foe.max_hp
            return d * (0.6 if scarce else 1.0) + (0.0 if me.pp[m] > 2 else -d * 0.1)
        mv = max(pool, key=value)
        return me.moves.index(mv) + 1

    def swap(self, game, foe, options):
        p, self.pending = self.pending, None
        return p if p is not None else self.best_replacement(game, foe)


POL = {"spam": Spam, "greedy": Greedy, "smart": Smart}


def fake_ask_int(msg, lo=None, hi=None, default=None):
    game, pol = S["game"], S["policy"]
    me = game.lead()
    return pol.act(game, CUR["foe"], me, len(me.moves))


def fake_menu(heading, options, back="Back"):
    """Policies think in party indices; the swap menu lists only beasts still
    standing, so translate the pick into the menu's own numbering."""
    game = S["game"]
    p = S["policy"].swap(game, CUR["foe"], options)
    if p == -1:
        return -1
    choices = game.swap_choices()
    assert p in choices, f"policy picked party index {p}, not on the menu {choices}"
    return choices.index(p)


ts.ask_int = fake_ask_int
ts.menu = fake_menu


def run_one(name, seed, squad=None):
    rng = random.Random(seed)
    squad = squad or rng.sample(EVOLVED, 6)
    game = circuit.CircuitGame("sim", "Bronze")
    game.party = [Beast(s, circuit.DRAFT_LEVEL) for s in squad]
    S.update(game=game, policy=POL[name]())
    random.seed(seed * 7 + 1)
    bracket = generate_bracket(circuit.DRAFT_LEVEL, random.Random(seed), level_offset=-2)
    reached = 0
    for i, rival in enumerate(bracket, 1):
        if not game.healthy():
            break
        team = [Beast(s, lv) for s, lv in rival["team"]]
        with contextlib.redirect_stdout(io.StringIO()):
            result = arena.arena_fight(game, team, "r", rival["name"])
        if result != "won":
            break
        reached = i
    return reached


if __name__ == "__main__":
    RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    NAMES = sys.argv[2].split(",") if len(sys.argv) > 2 else ["spam", "greedy", "smart"]
    print(f"{RUNS} runs per policy, identical squads/brackets (seeded)")
    for name in NAMES:
        dist = collections.Counter(run_one(name, s) for s in range(RUNS))
        avg = sum(k * v for k, v in dist.items()) / RUNS
        print(f"{name:7} avg rounds {avg:4.2f}/6 | full clears {dist[6]:3d}/{RUNS} "
              f"({dist[6] / RUNS * 100:4.1f}%) | " + " ".join(f"{k}:{dist[k]}" for k in range(7)),
              flush=True)
