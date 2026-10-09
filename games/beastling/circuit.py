"""Tournament mode: a trainer profile separate from the Story-mode save,
drafting from every known species instead of a caught roster.

Two modes:
  - Free   -- draft up to PARTY_MAX species from the full dex, no cost.
  - Ranked -- same draft, but every species has a point cost and the
    squad must fit a fixed budget. Feeds a persistent rank score/tier
    (a solo ladder against generated brackets -- there's no networking
    anywhere in this project, so "ranked" means climbing tiers by
    clearing harder rounds, not matchmaking against other players).

Battles are resolved by reusing `main.Game.battle()` (all the combat
depth -- stages, status, priority, crits -- lives there) via a small
subclass that only overrides the HUD header, since Circuit mode has no
badges/money/lures to show.
"""
from __future__ import annotations

import math

import termstation_sdk as ts

import arena
from beasts import SPECIES, TRAIN_LABEL, TRAIN_STEP, train_price
from main import PAGE, PARTY_MAX, Beast, Game, bar
from tournament import ROUNDS, generate_bracket

DRAFT_LEVEL = 30           # fixed level for every drafted Circuit beast --
                            # this is a team-building exercise, not a grind
DRAFT_PAGE = 20            # species shown per draft page (two columns of ten)
RANKED_BUDGET = 130        # see docs: 6 cheapest (basic) forms cost ~66,
                            # 6 priciest (evolved) forms cost ~168 -- the
                            # budget sits in between so an all-evolved
                            # squad is never affordable, forcing a real mix

RANK_TIERS = [
    ("Bronze", 0),
    ("Silver", 10),
    ("Gold", 25),
    ("Platinum", 50),
    ("Champion", 90),
]


def tier_for(score: int) -> str:
    label = RANK_TIERS[0][0]
    for name, threshold in RANK_TIERS:
        if score >= threshold:
            label = name
    return label


def point_cost(slug: str) -> int:
    """Priced off level-30 base stat total, banded by evolution stage --
    the dex splits cleanly into ten basic forms (BST 231-242) and ten
    evolved forms (BST 275-299), so pricing leans into that split rather
    than a single continuous formula: evolved forms cost roughly 2.5x a
    basic form, not proportional-to-BST, so budget pressure comes from
    "how many evolved forms can I afford" rather than tiny per-point
    differences nobody would notice."""
    b = Beast(slug, DRAFT_LEVEL)
    bst = b.max_hp + b.atk + b.dfn + b.spd
    evolved = SPECIES[slug].get("evolve") is None
    if evolved:
        return 24 + (bst - 275) // 5
    return 10 + (bst - 231) // 4


# ---------------------------------------------------------------- profile
def load_profile() -> dict:
    profile = ts.load(
        {"name": "", "rank_score": 0, "wins": 0, "losses": 0,
         "best_round_free": 0, "best_round_ranked": 0},
        name="circuit",
    )
    # The District's own state; older Circuit saves simply gain these.
    defaults = {"coins": 150, "bag": {"Potion": 2}, "training": {}, "run": None, "history": []}
    for key, value in defaults.items():
        profile.setdefault(key, value if not isinstance(value, (dict, list)) else type(value)(value))
    return profile


def save_profile(profile: dict) -> None:
    ts.save(profile, name="circuit")


def ensure_character(profile: dict) -> dict:
    if profile.get("name"):
        return profile
    ts.tv_clear(page=PAGE)
    ts.tv_print(ts.title("T H E   C I R C U I T"))
    ts.tv_print()
    # One line, not a box of rules: an LLM playtester's first reaction to
    # the old five-line explainer was "too much text, get me to the action".
    ts.tv_print("  A name for the Circuit's records (separate from Story mode).")
    ts.tv_print()
    name = ts.prompt("  Trainer name") or "Drafter"
    profile["name"] = name[:16]
    save_profile(profile)
    return profile


# ---------------------------------------------------------- circuit HUD
def _hits(hp: int, per_hit: float) -> str:
    """Hits of `per_hit` average damage needed to take `hp` down."""
    if per_hit <= 0 or hp / per_hit > 9:
        return "9+"
    return str(max(1, math.ceil(hp / per_hit)))


class CircuitGame(Game):
    """Reuses `Game.battle()` (and everything it calls) wholesale --
    that's where all the actual combat depth lives -- but Circuit mode
    has no badges/money/lures worth showing, so only the header differs."""

    def __init__(self, trainer_name: str, rank_label: str) -> None:
        super().__init__({})
        self.xp_share = False
        self.items_enabled = False
        self._trainer_name = trainer_name
        self._rank_label = rank_label

    def swap_label(self, b: Beast) -> str:
        """Who to send in is the Arena's central decision, so show what it
        hinges on: type, HP, and how a straight trade with the current foe
        goes -- how many of its best hits the foe takes to go down, and how
        many of the foe's best hits it takes itself. Counts, not a verdict:
        the old "+hits hard / -outmatched" tags compared raw damage with a
        fixed ratio, so against a higher-level foe nearly the whole bench
        read "-outmatched", including the right answer."""
        if not b.alive:
            return f"{b.name:<11} {b.type:<5} (down)"
        label = f"{b.name:<11} {b.type:<5} {b.hp:>3}/{b.max_hp:<3} HP"
        foe = arena.CURRENT.get("foe")
        if foe is None or not foe.alive:
            return label
        mine = max((arena.expected_damage(b, foe, m) for m in arena.usable_moves(b)), default=0)
        theirs = max((arena.expected_damage(foe, b, m) for m in arena.usable_moves(foe)), default=0)
        return f"{label}  KOs in {_hits(foe.hp, mine)}, KO'd in {_hits(b.hp, theirs)}"

    def header(self, title: str) -> None:
        ts.tv_clear(page=PAGE)
        left = f"  {title}"
        right = f"{self._trainer_name}   {self._rank_label}  "
        width = ts.size()[0]
        ts.tv_print(ts.color(left + right.rjust(max(1, width - len(left) - 1)),
                             "bright_cyan"))
        ts.tv_print(ts.rule("─"))


# ------------------------------------------------------------- drafting
def draft_squad(ranked: bool) -> list[Beast] | None:
    all_slugs = sorted(SPECIES, key=lambda s: (SPECIES[s]["type"], point_cost(s)))
    chosen: list[str] = []
    page = 0
    msg = ""

    while True:
        # No `page=` here, unlike every other screen in this game: `page`
        # vertically CENTRES content by starting a few rows down, and with
        # 20 species to list plus a confirm option, this is the one screen
        # with more content than the row budget can afford to give up --
        # centering ate exactly the headroom this needs. Start at row 0
        # instead. Found the hard way: past the row budget, `tv_print`'s
        # own pagination kicks in mid-list (a forced "press enter" while
        # picking, not a crash, but real budget math, not a guess -- see
        # the header()/travel() fix earlier for what happens when a
        # *different* internal call is the one that crosses the line
        # instead: a silent clear with no pause at all).
        ts.tv_clear()
        spent = sum(point_cost(s) for s in chosen)
        left = "  Draft"
        right = f"{len(chosen)}/{PARTY_MAX} chosen"
        if ranked:
            right += f"   {spent}/{RANKED_BUDGET}pt"
        width = ts.size()[0]
        ts.tv_print(ts.color(left + (right + "  ").rjust(max(1, width - len(left) - 1)),
                             "bright_cyan"))
        ts.tv_print(ts.rule("─"))
        # The whole squad, whichever page its members are on -- the ☑ marks
        # alone split it across two pages.
        names = [SPECIES[s]["name"] for s in chosen]
        for cut in (11, 9, 7, 5):                  # six full names overflow 62 columns
            squad = ", ".join(nm[:cut] for nm in names)
            if len(squad) <= width - 10:
                break
        ts.tv_print(f"  Squad: {squad or 'nobody yet'}")
        ts.tv_print(ts.color(f"  {msg}", "bright_green") if msg else "")
        msg = ""

        # Two columns per page, not ts.menu(): 36 species in one column is
        # taller than the 20-row picture at the declared 66x24 minimum, so
        # the header and the first options scrolled off before the prompt.
        # Numbers are global (1..n); the three footer entries keep fixed
        # numbers so the prompt never moves.
        n = len(all_slugs)
        pages = (n + DRAFT_PAGE - 1) // DRAFT_PAGE
        lo = page * DRAFT_PAGE
        shown = list(range(lo, min(n, lo + DRAFT_PAGE)))
        cells = []
        for i in shown:
            slug = all_slugs[i]
            d = SPECIES[slug]
            mark = "☑" if slug in chosen else "☐"
            cost = f" {point_cost(slug):>2}pt" if ranked else ""
            cells.append(f"{i + 1:>2} {mark} {d['name'][:11].ljust(11)} {d['type'].ljust(5)}{cost}")
        half = (len(cells) + 1) // 2
        col_w = 29
        for r in range(half):
            right = cells[r + half] if r + half < len(cells) else ""
            ts.tv_print(f"  {cells[r].ljust(col_w)}{right}")
        ts.tv_print(f"  {n + 1:>2}   Other page ({page + 1}/{pages})   "
                    f"{n + 2:>2}   Confirm squad   {n + 3:>2}   Cancel")
        pick = ts.ask_int("choose", 1, n + 3) - 1
        if pick == n + 2:
            return None
        if pick == n:
            page = (page + 1) % pages
            continue
        if pick == n + 1:
            if chosen:
                return [Beast(s, DRAFT_LEVEL) for s in chosen]
            msg = "Pick at least one beast first."
            continue
        if pick not in shown:
            # A number from the page you can't see: show that page instead
            # of drafting blind. An LLM playtester typed 28 meaning "next
            # page" and silently drafted a 26-point beast it never saw.
            page = pick // DRAFT_PAGE
            msg = (f"#{pick + 1} {SPECIES[all_slugs[pick]]['name']} is here --"
                   f" type {pick + 1} again to draft it.")
            continue

        slug = all_slugs[pick]
        name = SPECIES[slug]["name"]
        if slug in chosen:
            chosen.remove(slug)
            msg = f"Dropped {name}."
            continue
        if len(chosen) >= PARTY_MAX:
            # tv_clear() FIRST, not after: with the full 20-species list
            # already drawn this iteration, the row counter sits right at
            # the edge where `tv_pause`'s own `_seat_cursor` would silently
            # clear the picture before this message was ever shown -- the
            # exact bug found and fixed above, one line later than it
            # looked. Clearing before printing sidesteps it entirely.
            ts.tv_clear()
            ts.tv_print(ts.color(f"  Squads are capped at {PARTY_MAX}.", "bright_red"))
            ts.tv_pause()
            continue
        if ranked and spent + point_cost(slug) > RANKED_BUDGET:
            ts.tv_clear()
            ts.tv_print(ts.color("  Not enough points left.", "bright_red"))
            ts.tv_pause()
            continue
        chosen.append(slug)
        msg = f"Drafted {name} ({SPECIES[slug]['type']}" + (f", {point_cost(slug)}pt)." if ranked else ").")


# ------------------------------------------------------------ the district
YARD_CAP = 6                 # training points per stat in the Yard (profile-wide)
RUN_ROUNDS = ROUNDS
REVIVE_BASE, REVIVE_STEP = 60, 20    # a revive costs about one round's prize


def round_prize(round_idx: int) -> int:
    """Coins for clearing round `round_idx` (0-based), before any bonus."""
    return 50 + 20 * (round_idx + 1)


def treatment_prices(b: Beast, round_idx: int) -> dict:
    """The Infirmary's prices for one beast before round `round_idx`
    (0-based). HP and PP upkeep climb 25% a round. A revive is per beast and
    pegged near one round's prize, so losing a beast costs about a round's
    winnings. It used to be one all-or-nothing package at 160c x the round
    multiplier per body -- 960c by round 3, more than any purse, so one bad
    fight ended the run (two of three LLM playtesters hit exactly that)."""
    if not b.alive:
        return {"hp": 0, "pp": 0, "revive": REVIVE_BASE + REVIVE_STEP * round_idx}
    mult = 1 + 0.25 * round_idx
    missing_hp = b.max_hp - b.hp
    missing_pp = sum(max(0, arena.move_pp(m) - b.pp.get(m, 0)) for m in b.moves)
    return {"hp": int((8 + missing_hp // 3) * mult) if missing_hp else 0,
            "pp": int((6 + missing_pp // 2) * mult) if missing_pp else 0,
            "revive": 0}


def apply_treatment(b: Beast, kind: str) -> None:
    if kind == "revive" and not b.alive:
        b.hp = max(1, b.max_hp // 2)
        b.reset_combat_state()
    elif kind == "hp" and b.alive:
        b.hp = b.max_hp
    elif kind == "pp" and b.alive:
        arena.restore_pp(b)


def squad_blob(party: list[Beast]) -> list[dict]:
    return [{"slug": b.slug, "hp": b.hp, "pp": dict(b.pp), "train": dict(b.train)} for b in party]


def squad_from_blob(blob: list[dict]) -> list[Beast]:
    squad = []
    for d in blob:
        b = Beast(d["slug"], DRAFT_LEVEL)
        b.train = {k: int(v) for k, v in d.get("train", {}).items() if k in TRAIN_STEP}
        arena.prepare(b)
        b.pp.update({m: int(v) for m, v in d.get("pp", {}).items() if m in b.pp})
        b.hp = max(0, min(int(d.get("hp", b.max_hp)), b.max_hp))
        squad.append(b)
    return squad


class District:
    """The Tournament's own little world: a hub of places. Resources that
    matter during a run -- HP, PP, items, coins -- all live here, so WHEN you
    spend them (and on what) is part of the game, not a menu you click through."""

    def __init__(self, profile: dict) -> None:
        self.profile = profile
        self.game = self._new_game()

    # ---- plumbing
    def _new_game(self) -> CircuitGame:
        g = CircuitGame(self.profile["name"], tier_for(self.profile.get("rank_score", 0)))
        g.inventory = self.profile["bag"]          # shared: item use mutates the profile
        run = self.profile.get("run")
        g.party = squad_from_blob(run["squad"]) if run else []
        return g

    def save(self) -> None:
        run = self.profile.get("run")
        if run:
            run["squad"] = squad_blob(self.game.party)
        save_profile(self.profile)

    @property
    def run(self) -> dict | None:
        return self.profile.get("run")

    def coins(self) -> int:
        return self.profile["coins"]

    def head(self, title: str) -> None:
        self.game.header(title)
        ts.tv_print()

    def say(self, *lines: str) -> None:
        for line in lines:
            ts.tv_print(f"  {line}")
        ts.tv_print()
        ts.tv_pause()

    # ---- the hub
    def loop(self) -> None:
        notice = ""
        while True:
            p = self.profile
            tier = tier_for(p.get("rank_score", 0))
            ts.tv_clear(page=PAGE)
            ts.tv_print(ts.title("T H E   A R E N A   D I S T R I C T"))
            ts.tv_print(f"  {p['name']} -- {tier}   {ts.color(str(self.coins()), 'bright_yellow')} coins"
                        f"   {p.get('wins', 0)}W {p.get('losses', 0)}L")
            run = self.run
            if run:
                standing = sum(1 for b in self.game.party if b.alive)
                ts.tv_print(ts.color(f"  Run: {run['mode']}, round {run['round'] + 1}/{RUN_ROUNDS}"
                                     f" -- {standing}/{len(self.game.party)} standing", "bright_cyan"))
                ts.tv_print(ts.color(f"  {self.rival_line()}", "grey"))
            else:
                ts.tv_print(ts.color("  No run yet. The Squad Hall is where you start one.", "grey"))
            ts.tv_print(ts.color(f"  {notice}", "bright_green") if notice else "")
            notice = ""
            gate = "The Arena Gate  -- next rival" if run else "The Arena Gate  -- (needs a squad)"
            pick = ts.menu("The District", [
                gate,
                "Squad Hall      -- draft a squad",
                "The Market      -- supplies, for coins",
                "The Infirmary   -- patch up between rounds",
                "The Yard        -- permanent training",
                "Hall of Fame    -- records",
            ], back="Leave the District")
            if pick == -1:
                self.save()
                return
            notice = [self.gate, self.squad_hall, self.market, self.infirmary,
                      self.yard, self.hall_of_fame][pick]() or ""
            self.save()

    # ---- the Squad Hall
    def squad_hall(self) -> str:
        self.head("Squad Hall")
        if self.run:
            ts.tv_print("  You're already in a run. Starting over forfeits it (items stay).")
            ts.tv_print()
            if not ts.confirm("  Abandon the current run?", default=False):
                return ""
            self.end_run(reached=self.run["round"], champion=False, abandoned=True)
        pick = ts.menu("Mode", ["Free   -- draft anyone, no budget",
                                "Ranked -- points budget, climbs the rank ladder"], back="Back")
        if pick == -1:
            return ""
        ranked = pick == 1
        squad = draft_squad(ranked)
        if not squad:
            return ""
        for b in squad:
            b.train = dict(self.profile["training"].get(b.slug, {}))
            arena.prepare(b)
            b.hp = b.max_hp
        bracket = generate_bracket(DRAFT_LEVEL, level_offset=-2)
        self.profile["run"] = {"mode": "Ranked" if ranked else "Free", "round": 0,
                               "squad": squad_blob(squad),
                               "bracket": [dict(r, team=[list(t) for t in r["team"]]) for r in bracket]}
        self.game = self._new_game()
        return f"Squad registered. {len(squad)} beasts. Round 1 awaits at the Gate."

    # ---- the Arena Gate
    def gate(self) -> str:
        run = self.run
        if not run:
            return "No squad yet -- the Squad Hall is the first stop."
        if not self.game.healthy():
            return "Your whole squad is down. The Infirmary can revive them."
        i = run["round"]
        rival = run["bracket"][i]
        self.head(f"Round {i + 1}/{RUN_ROUNDS}")
        levels = [lv for _, lv in rival["team"]]
        ts.tv_print(ts.box([
            f"  {rival['name']}  --  {'/'.join(rival['types'])}",
            "",
            f"  {rival['blurb']}",
            "",
            f"  Team of {len(rival['team'])}, levels {min(levels)}-{max(levels)}."
            + ("  The final." if i == RUN_ROUNDS - 1 else ""),
        ], fg="yellow" if i == RUN_ROUNDS - 1 else "amber"))
        ts.tv_print()
        if not ts.confirm("  Step into the arena?", default=True):
            return ""
        foes = [Beast(s, lv) for s, lv in rival["team"]]
        fallen_before = sum(1 for b in self.game.party if not b.alive)
        result = arena.arena_fight(self.game, foes, f"Round {i + 1}", rival["name"])
        if result != "won":
            self.end_run(reached=i, champion=False)
            return ""
        run["round"] = i + 1
        fallen = sum(1 for b in self.game.party if not b.alive) - fallen_before
        prize = round_prize(i) + (25 if fallen == 0 else 0)
        champion = run["round"] >= RUN_ROUNDS
        if champion:
            prize += 200
        self.profile["coins"] += prize
        if champion:
            self.end_run(reached=RUN_ROUNDS, champion=True, prize=prize)
            return ""
        self.head("Round cleared")
        ts.tv_print(ts.box([
            f"  You beat {rival['name']}.",
            "",
            f"  Prize: {prize} coins" + ("  (clean win bonus)" if fallen == 0 else ""),
            f"  Next: round {run['round'] + 1}/{RUN_ROUNDS}. Your HP and PP stay as they are.",
            "  The Infirmary and Market are open -- spend wisely.",
        ], fg="yellow"))
        ts.tv_print()
        ts.tv_pause()
        return ""

    def end_run(self, reached: int, champion: bool, prize: int = 0, abandoned: bool = False) -> None:
        p, run = self.profile, self.run
        ranked = run["mode"] == "Ranked"
        consolation = 0 if (champion or abandoned) else 10 * reached
        p["coins"] += consolation
        if ranked and not abandoned:
            p["rank_score"] = p.get("rank_score", 0) + reached
        if not abandoned:
            p["wins" if champion else "losses"] = p.get("wins" if champion else "losses", 0) + 1
            key = "best_round_ranked" if ranked else "best_round_free"
            p[key] = max(p.get(key, 0), reached)
        squad_names = ", ".join(SPECIES[b["slug"]]["name"] for b in run["squad"])
        p.setdefault("history", []).append(
            {"mode": run["mode"], "reached": reached, "champion": champion, "abandoned": abandoned,
             "squad": squad_names})
        p["history"] = p["history"][-8:]
        p["run"] = None
        self.game = self._new_game()
        save_profile(p)
        if abandoned:
            return
        self.head("The Arena")
        if champion:
            lines = ["  You cleared the whole circuit.", "", f"  Prize: {prize} coins"]
            ts.unlock("circuit-champion", "Circuit Champion", "Won a full Circuit run")
        else:
            lines = [f"  Your squad went down in round {reached + 1}/{RUN_ROUNDS}.", "",
                     f"  Consolation: {consolation} coins"]
            if reached >= 3:
                ts.unlock("circuit-contender", "Circuit Contender", "Reached round 4 of a Circuit run")
        if ranked:
            lines += [f"  Rank score {p['rank_score']} -- {tier_for(p['rank_score'])}."]
        ts.tv_print(ts.box(lines, fg="yellow" if champion else "amber"))
        ts.tv_print()
        ts.tv_pause()

    # ---- the Market
    def market(self) -> str:
        msg = ""
        bag = self.profile["bag"]
        while True:
            self.head("The Market")
            ts.tv_print(f"  \"Prices are prices.\" -- Pip.   You have "
                        f"{ts.color(str(self.coins()), 'bright_yellow')} coins.")
            ts.tv_print(ts.color(f"  {msg}", "bright_green") if msg else "")
            names = list(arena.ARENA_ITEMS)
            options = [f"{n:<13}{arena.ARENA_ITEMS[n]['price']:>4}c  x{bag.get(n, 0)}  "
                       f"{arena.ARENA_ITEMS[n]['desc']}" for n in names]
            pick = ts.menu("Buy", options, back="Back")
            if pick == -1:
                return ""
            n = names[pick]
            price = arena.ARENA_ITEMS[n]["price"]
            if self.coins() < price:
                msg = "Not enough coins."
            elif bag.get(n, 0) >= 9:
                msg = "You can't carry more of those."
            else:
                self.profile["coins"] -= price
                bag[n] = bag.get(n, 0) + 1
                msg = f"Bought {n}."
                self.save()

    # ---- the Infirmary
    def rival_line(self) -> str:
        """Who the Gate holds next -- what every between-round choice hinges on."""
        run = self.run
        if not run or run["round"] >= RUN_ROUNDS:
            return ""
        r = run["bracket"][run["round"]]
        levels = [lv for _, lv in r["team"]]
        return (f"Next: {r['name']} -- {'/'.join(r['types'])}, {len(r['team'])} beasts,"
                f" Lv {min(levels)}-{max(levels)}")

    @staticmethod
    def _ward_line(b: Beast, price: dict) -> str:
        if not b.alive:
            return f"{b.name[:11]:<11} {'DOWN':<20}  revive {price['revive']}c"
        need = "  ".join(x for x in (f"heal {price['hp']}c" if price["hp"] else "",
                                     f"PP {price['pp']}c" if price["pp"] else "") if x)
        return (f"{b.name[:11]:<11} [{bar(b.hp, b.max_hp, 8)}] {b.hp:>3}/{b.max_hp:<3}  "
                + (need or "fit to fight"))

    def infirmary(self) -> str:
        """The beast list IS the menu: pick who to treat, then what. Per beast,
        so after a rough round you choose who comes back for the next rival
        instead of facing one price for everything."""
        if not self.run:
            return "The Infirmary is for squads in a run. Nobody here to treat."
        msg = ""
        while True:
            party = self.game.party
            prices = [treatment_prices(b, self.run["round"]) for b in party]
            # No blank rows on this screen: 6 beasts + Everyone + Back leave
            # almost no slack at 66x24, and spending a row on padding blanked
            # the whole screen (the silent cursor-seat wipe) when first built.
            self.game.header("The Infirmary")
            ts.tv_print(f"  Nurse Odalys: \"Prices climb each round.\"  "
                        f"{ts.color(str(self.coins()), 'bright_yellow')}c")
            ts.tv_print(ts.color(f"  {self.rival_line()}", "grey"))
            ts.tv_print(ts.color(f"  {msg}", "bright_green") if msg else "")
            options = [self._ward_line(b, p) for b, p in zip(party, prices)]
            options.append("Everyone -- treat the whole squad at once")
            pick = ts.menu("Treat who?", options, back="Back")
            if pick == -1:
                return ""
            if pick == len(party):
                msg = self._treat_all(prices)
            else:
                msg = self._treat_one(party[pick], prices[pick])

    def _pay(self, cost: int, beasts_kinds: list[tuple[Beast, str]]) -> bool:
        if self.coins() < cost:
            return False
        self.profile["coins"] -= cost
        for b, kind in beasts_kinds:
            apply_treatment(b, kind)
        self.save()
        return True

    def _treat_one(self, b: Beast, price: dict) -> str:
        if not b.alive:
            choices = [("revive", f"Revive at half HP   {price['revive']:>4}c", price["revive"])]
        else:
            choices = []
            if price["hp"]:
                choices.append(("hp", f"Heal HP to full     {price['hp']:>4}c", price["hp"]))
            if price["pp"]:
                choices.append(("pp", f"Restore all PP      {price['pp']:>4}c", price["pp"]))
            if price["hp"] and price["pp"]:
                choices.append(("both", f"Both                {price['hp'] + price['pp']:>4}c",
                                price["hp"] + price["pp"]))
        if not choices:
            return f"{b.name} is fit to fight."
        self.game.header(f"The Infirmary -- {b.name}")
        ts.tv_print(f"  {b.name} ({b.type})  {b.hp}/{b.max_hp} HP" + ("  DOWN" if not b.alive else "")
                    + f"     you have {ts.color(str(self.coins()), 'bright_yellow')}c")
        cells = [f"{m:<13}{b.pp.get(m, 0):>2}/{arena.move_pp(m):<2}" for m in b.moves]
        for r in range(0, len(cells), 2):
            ts.tv_print("    " + "   ".join(cells[r:r + 2]))
        pick = ts.menu("Treatment", [c[1] for c in choices], back="Back")
        if pick == -1:
            return ""
        kind, _, cost = choices[pick]
        kinds = ["hp", "pp"] if kind == "both" else [kind]
        if not self._pay(cost, [(b, k) for k in kinds]):
            return "Not enough coins."
        return {"revive": f"{b.name} is back on its feet (half HP).", "hp": f"{b.name} is patched up.",
                "pp": f"{b.name}'s moves are restored.", "both": f"{b.name} is good as new."}[kind]

    def _treat_all(self, prices: list[dict]) -> str:
        party = self.game.party
        total = {k: sum(p[k] for p in prices) for k in ("revive", "hp", "pp")}
        labels = {"revive": "Revive the fallen (half HP)", "hp": "Heal everyone's HP",
                  "pp": "Restore everyone's PP"}
        choices = [(k, f"{labels[k]:<28}{total[k]:>5}c", total[k]) for k in labels if total[k]]
        if not choices:
            return "Everyone is fit to fight."
        if len(choices) > 1:
            choices.append(("all", f"{'All of the above':<28}{sum(total.values()):>5}c", sum(total.values())))
        self.game.header("The Infirmary -- everyone")
        ts.tv_print(f"  You have {ts.color(str(self.coins()), 'bright_yellow')} coins."
                    "  Revived beasts come back at half HP.")
        pick = ts.menu("Treatment", [c[1] for c in choices], back="Back")
        if pick == -1:
            return ""
        kind, _, cost = choices[pick]
        kinds = ["revive", "hp", "pp"] if kind == "all" else [kind]
        # Each beast is charged at the price shown, so a beast revived here
        # is not also healed past half by the same purchase.
        work = [(b, k) for b, p in zip(party, prices) for k in kinds if p[k]]
        if not self._pay(cost, work):
            return "Not enough coins."
        return {"revive": "The fallen are back on their feet.", "hp": "Everyone is patched up.",
                "pp": "Moves restored.", "all": "The whole squad is seen to."}[kind]

    # ---- the Yard
    def yard(self) -> str:
        training = self.profile["training"]
        slugs = sorted(SPECIES, key=lambda s: (SPECIES[s]["type"], SPECIES[s]["name"]))
        msg = ""

        def draw() -> None:
            self.head("The Yard")
            ts.tv_print(f"  Coach Brann: \"Training sticks to the species.\"")
            ts.tv_print(f"  You have {ts.color(str(self.coins()), 'bright_yellow')} coins."
                        + (ts.color(f"   {msg}", "bright_green") if msg else ""))

        while True:
            options = [f"{SPECIES[s]['name']:<11} {SPECIES[s]['type']:<5} "
                       f"trained {sum(training.get(s, {}).values())}/{len(TRAIN_STEP) * YARD_CAP}"
                       for s in slugs]
            pick = self.game.paged_menu("Train which species?", options, "Back", draw=draw)
            if pick == -1:
                return ""
            slug = slugs[pick]
            msg = self.train_species(slug)

    def train_species(self, slug: str) -> str:
        training = self.profile["training"].setdefault(slug, {})
        b = Beast(slug, DRAFT_LEVEL)
        msg = ""
        while True:
            b.train = dict(training)
            self.head(f"Train {SPECIES[slug]['name']}")
            ts.tv_print(f"  You have {ts.color(str(self.coins()), 'bright_yellow')} coins.")
            ts.tv_print(ts.color(f"  {msg}", "bright_green") if msg else "")
            total = sum(training.values())
            options = []
            for key in TRAIN_STEP:
                pts = training.get(key, 0)
                cur = {"hp": b.max_hp, "atk": b.atk, "dfn": b.dfn, "spd": b.spd}[key]
                if pts >= YARD_CAP:
                    options.append(f"{TRAIN_LABEL[key]:<4} {cur:>3}  maxed ({pts}/{YARD_CAP})")
                else:
                    options.append(f"{TRAIN_LABEL[key]:<4} {cur:>3}   {train_price(pts, total) // 2}c   ({pts}/{YARD_CAP})")
            pick = ts.menu(f"Train {SPECIES[slug]['name']}", options, back="Back")
            if pick == -1:
                return f"Trained {SPECIES[slug]['name']}."
            key = list(TRAIN_STEP)[pick]
            pts = training.get(key, 0)
            price = train_price(pts, total) // 2
            if pts >= YARD_CAP:
                msg = f"{TRAIN_LABEL[key]} is maxed."
            elif self.coins() < price:
                msg = "Not enough coins."
            else:
                self.profile["coins"] -= price
                training[key] = pts + 1
                save_profile(self.profile)
                msg = f"{TRAIN_LABEL[key]} went up."

    # ---- the Hall of Fame
    def hall_of_fame(self) -> str:
        p = self.profile
        self.head("Hall of Fame")
        ts.tv_print(f"  {p['name']} -- {tier_for(p.get('rank_score', 0))}"
                    f"   (rank score {p.get('rank_score', 0)})")
        ts.tv_print(f"  Record {p.get('wins', 0)}W {p.get('losses', 0)}L.   Best round:"
                    f" Free {p.get('best_round_free', 0)}/{RUN_ROUNDS},"
                    f" Ranked {p.get('best_round_ranked', 0)}/{RUN_ROUNDS}.")
        ts.tv_print()
        hist = p.get("history", [])
        if not hist:
            ts.tv_print(ts.color("  No runs yet.", "grey"))
        for h in reversed(hist[-5:]):
            tag = "CHAMPION" if h["champion"] else ("abandoned" if h["abandoned"] else f"round {h['reached'] + 1}")
            ts.tv_print(f"  {h['mode']:<6} {tag:<10} {h['squad'][:42]}")
        ts.tv_print()
        ts.tv_pause()
        return ""


# --------------------------------------------------------------- entry
def run() -> None:
    profile = load_profile()
    profile = ensure_character(profile)
    District(profile).loop()
