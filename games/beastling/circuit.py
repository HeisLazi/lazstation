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

import termstation_sdk as ts

from beasts import SPECIES
from main import PAGE, PARTY_MAX, Beast, Game
from tournament import generate_bracket

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
    return ts.load(
        {"name": "", "rank_score": 0, "wins": 0, "losses": 0,
         "best_round_free": 0, "best_round_ranked": 0},
        name="circuit",
    )


def save_profile(profile: dict) -> None:
    ts.save(profile, name="circuit")


def ensure_character(profile: dict) -> dict:
    if profile.get("name"):
        return profile
    ts.tv_clear(page=PAGE)
    ts.tv_print(ts.title("T H E   C I R C U I T"))
    ts.tv_print()
    ts.tv_print(ts.box([
        "  Before you draft, the Circuit wants a name for its records.",
        "",
        "  This trainer is separate from your Story-mode save --",
        "  nothing here needs to be caught first. Draft from every",
        "  known species instead.",
    ]))
    ts.tv_print()
    name = ts.prompt("  Trainer name") or "Drafter"
    profile["name"] = name[:16]
    save_profile(profile)
    return profile


# ---------------------------------------------------------- circuit HUD
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
        ts.tv_print(f"  {n + 1:>2}   Page {page + 1}/{pages} (switch)   "
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
            continue

        slug = all_slugs[pick]
        if slug in chosen:
            chosen.remove(slug)
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


# ---------------------------------------------------------------- bracket
def play_bracket(profile: dict, squad: list[Beast], ranked: bool) -> None:
    bracket = generate_bracket(DRAFT_LEVEL)
    game = CircuitGame(profile["name"], tier_for(profile["rank_score"]))
    game.party = squad
    mode_label = "Ranked" if ranked else "Free"

    game.header("The Circuit")
    ts.tv_print()
    ts.tv_print(ts.box([
        f"  {mode_label} mode -- {len(bracket)} rounds. No healing between them.",
        "",
        f"  Squad ({len(squad)}): " + ", ".join(b.name for b in squad),
    ]))
    ts.tv_print()
    if not ts.confirm("  Enter the circuit?", default=True):
        return

    reached = 0
    for i, rival in enumerate(bracket, 1):
        game.header(f"Round {i}/{len(bracket)}")
        ts.tv_print()
        ts.tv_print(ts.box([
            f"  {rival['name']}  —  {'/'.join(rival['types'])}",
            "",
            f"  {rival['blurb']}",
            "",
            f"  Team of {len(rival['team'])}.",
        ]))
        ts.tv_print()
        if not game.healthy():
            break
        ts.tv_pause("press enter to fight")

        won_round = True
        for slug, level in rival["team"]:
            foe = Beast(slug, level)
            result = game.battle(foe, wild=False, title=f"Round {i} · {rival['name']}",
                                  trainer=rival["name"])
            if result == "lost":
                won_round = False
                break
        if not won_round:
            break
        reached = i

    champion = reached == len(bracket)
    if ranked:
        profile["rank_score"] = profile.get("rank_score", 0) + reached
    if champion:
        profile["wins"] = profile.get("wins", 0) + 1
    else:
        profile["losses"] = profile.get("losses", 0) + 1
    key = "best_round_ranked" if ranked else "best_round_free"
    profile[key] = max(profile.get(key, 0), reached)
    save_profile(profile)

    game.header("The Circuit")
    ts.tv_print()
    new_tier = tier_for(profile.get("rank_score", 0))
    if champion:
        lines = ["  You cleared the whole circuit."]
        if ranked:
            lines += ["", f"  Rank score {profile['rank_score']} -- {new_tier}."]
        ts.tv_print(ts.box(lines, fg="yellow"))
        ts.unlock("circuit-champion", "Circuit Champion", "Won a full Circuit run")
    else:
        lines = [f"  Your squad went down in round {reached + 1}/{len(bracket)}."]
        if ranked:
            lines += ["", f"  Rank score {profile['rank_score']} -- {new_tier}."]
        ts.tv_print(ts.box(lines))
        if reached >= 3:
            ts.unlock("circuit-contender", "Circuit Contender", "Reached round 4 of a Circuit run")
    ts.tv_print()
    ts.tv_pause()


# --------------------------------------------------------------- entry
def run() -> None:
    profile = load_profile()
    profile = ensure_character(profile)

    while True:
        tier = tier_for(profile.get("rank_score", 0))
        ts.tv_clear(page=PAGE)
        ts.tv_print(ts.title("T H E   C I R C U I T"))
        ts.tv_print()
        ts.tv_print(ts.box([
            f"  {profile['name']}   —   {tier}",
            "",
            f"  Record: {profile.get('wins', 0)}W {profile.get('losses', 0)}L"
            f"   (rank score {profile.get('rank_score', 0)})",
            f"  Best round -- Free {profile.get('best_round_free', 0)}/6"
            f"   Ranked {profile.get('best_round_ranked', 0)}/6",
        ]))
        ts.tv_print()
        pick = ts.menu("The Circuit", ["Free mode", "Ranked mode"], back="Back to the hub")
        if pick == -1:
            return
        ranked = pick == 1
        squad = draft_squad(ranked)
        if not squad:
            continue
        play_bracket(profile, squad, ranked)
