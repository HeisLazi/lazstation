#!/usr/bin/env python3
"""Ekse Slaan Ball: a deterministic, explainable football management career.

Authored clubs, players, formations, fixtures, and narrative live in
``content.py``. The functions below contain the simulation rules so they can
be exercised headlessly without curses, a save file, or a terminal.
"""
from __future__ import annotations

import copy
import curses
import random
import sys
from itertools import combinations
from typing import Any

import termstation_sdk as ts
import termstation_ui as ui

if __package__:
    from . import content
else:
    import content


SAVE_DEFAULTS = {"version": 2, "career": None}
POSITION_NAMES = {"GK": "Goalkeeper", "DEF": "Defender", "MID": "Midfielder",
                  "WNG": "Wide player", "FWD": "Forward"}
ATTRIBUTE_NAMES = {
    "pace": "Pace", "passing": "Passing", "finishing": "Finishing",
    "defending": "Defending", "stamina": "Stamina", "first_touch": "First touch",
    "technique": "Technique", "vision": "Vision", "decisions": "Decisions",
    "work_rate": "Work rate", "strength": "Strength", "aerial": "Aerial",
    "positioning": "Positioning", "tackling": "Tackling", "composure": "Composure",
    "reflexes": "Reflexes", "handling": "Handling", "kicking": "Kicking",
}
TACTIC_KEYS = ("press", "line", "width", "build", "tempo")
LEVELS = ("low", "mid", "high")
TRAINING_INTENSITIES = ("low", "normal", "high")
MATCH_MINUTES = 90
MATCH_VIEWS = ("live", "events", "stats")
SECTION_PAGES = ("home", "squad", "tactics", "training", "market", "table", "history")
SECTION_LABELS = ("HOME", "SQUAD", "PLAN", "TRAIN", "MARKET", "TABLE", "LOGS")
MATCH_NAV_INDEX = len(SECTION_PAGES)
PAGE_BREADCRUMBS = {
    "career_select": "NEW CAREER / CHOOSE A CLUB",
    "help": "HELP / GAME CONTROLS",
    "team_talk": "MATCHDAY / TEAM TALK · PRE-KICKOFF",
    "match_subs": "MATCHDAY / CHANGES · SELECT A PAIR",
    "offer": "MARKET / CONTRACT NEGOTIATION",
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def stable_number(value: str) -> int:
    """Stable small hash; unlike hash(), this is identical across processes."""
    return sum((index + 1) * ord(char) for index, char in enumerate(value))


def _secondary_skills(seed: dict[str, Any]) -> dict[str, int]:
    """Turn editable five-skill seeds into coherent individual profiles."""
    pace = int(seed["pace"])
    passing = int(seed["passing"])
    finishing = int(seed["finishing"])
    defending = int(seed["defending"])
    stamina = int(seed["stamina"])
    pos = seed["position"]
    salt = stable_number(str(seed["id"]))

    def blend(*values: float, offset: int = 0) -> int:
        return int(clamp(round(sum(values) / len(values) + offset), 5, 99))

    profile = {
        "first_touch": blend(passing, pace, finishing, offset=(salt % 9) - 4),
        "technique": blend(passing, finishing, pace, offset=((salt // 3) % 9) - 4),
        "vision": blend(passing, defending, stamina, offset=((salt // 7) % 11) - 5),
        "decisions": blend(passing, defending, stamina, offset=((salt // 11) % 9) - 4),
        "work_rate": blend(stamina, defending, pace, offset=((salt // 13) % 9) - 4),
        "strength": int(clamp(44 + ((salt // 17) % 31) + (defending - 60) * 0.18, 25, 92)),
        "aerial": blend(defending, finishing, stamina, offset=((salt // 19) % 11) - 5),
        "positioning": blend(defending, (passing + stamina) / 2,
                              stamina, offset=((salt // 23) % 9) - 4),
        "tackling": blend(defending, stamina, passing, offset=((salt // 29) % 7) - 3),
        "composure": blend(finishing, passing, defending, offset=((salt // 31) % 9) - 4),
        "reflexes": int(clamp(28 + defending * 0.72 + pace * 0.08
                              + ((salt // 37) % 9) - 4, 20, 96)) if pos == "GK" else 12,
        "handling": int(clamp(24 + defending * 0.68 + passing * 0.1
                              + ((salt // 41) % 9) - 4, 18, 95)) if pos == "GK" else 12,
        "kicking": int(clamp(30 + passing * 0.58 + pace * 0.12
                             + ((salt // 43) % 9) - 4, 20, 95)) if pos == "GK" else 12,
    }
    # Keep the profile generative but position-aware: a centre-back is not a
    # winger merely because one seed stat happens to be high.
    if pos == "GK":
        profile["positioning"] = blend(defending, profile["reflexes"], stamina)
        profile["composure"] = blend(passing, defending, profile["handling"])
    elif pos == "DEF":
        profile["positioning"] = int(clamp(profile["positioning"] + 5, 5, 99))
        profile["aerial"] = int(clamp(profile["aerial"] + 4, 5, 99))
    elif pos in ("MID", "WNG"):
        profile["first_touch"] = int(clamp(profile["first_touch"] + 3, 5, 99))
        profile["vision"] = int(clamp(profile["vision"] + 4, 5, 99))
    elif pos == "FWD":
        profile["composure"] = int(clamp(profile["composure"] + 5, 5, 99))
    return profile


def player_overall(player: dict[str, Any]) -> int:
    """Position-weighted overview. Match outcomes use the underlying skills."""
    pos = player["position"]
    weights = {
        "GK": {"reflexes": .32, "handling": .24, "positioning": .2,
               "kicking": .1, "decisions": .08, "composure": .06},
        "DEF": {"defending": .23, "tackling": .18, "positioning": .18,
                "aerial": .12, "pace": .1, "passing": .08,
                "decisions": .06, "strength": .05},
        "MID": {"passing": .18, "vision": .18, "decisions": .15,
                "technique": .13, "stamina": .12, "defending": .1,
                "first_touch": .08, "work_rate": .06, "finishing": .04},
        "WNG": {"pace": .21, "technique": .17, "first_touch": .15,
                "passing": .12, "finishing": .12, "stamina": .1,
                "vision": .07, "composure": .06},
        "FWD": {"finishing": .24, "composure": .17, "first_touch": .14,
                "pace": .13, "decisions": .1, "strength": .08,
                "aerial": .07, "technique": .07},
    }
    mapping = weights.get(pos, weights["MID"])
    return round(sum(float(player.get(skill, 50)) * weight
                     for skill, weight in mapping.items()))


def make_player(seed: dict[str, Any]) -> dict[str, Any]:
    """Build the mutable career record from one editable content seed."""
    player = copy.deepcopy(seed)
    player.update(_secondary_skills(seed))
    overall = player_overall(player)
    personality = content.PERSONALITIES[stable_number(seed["id"]) % len(content.PERSONALITIES)]
    player.update({
        "overall": overall,
        "potential": int(clamp(overall + max(0, 22 - int(seed["age"]))
                               * (1.15 + (stable_number(seed["id"]) % 30) / 100),
                               overall, 96)),
        "personality": personality["id"],
        "morale": int(seed.get("morale", 66)),
        "fitness": int(seed.get("fitness", 93)),
        "sharpness": 62,
        "form": 6.5,
        "trust": 54,
        "familiarity": 52,
        "wage": round(.75 + overall * .022, 1),
        "wage_demand": round(.9 + overall * .024
                             + (stable_number(seed["id"]) % 60) / 100, 1),
        "contract_years": 0 if seed.get("club") is None else 1 + stable_number(seed["id"]) % 4,
        "injury_until_round": -1,
        "career_apps": 0,
        "career_goals": 0,
        "career_assists": 0,
    })
    if player["position"] == "GK":
        player["goalkeeping"] = round(player["reflexes"] * .54 + player["handling"] * .3
                                      + player["positioning"] * .16)
    else:
        player["goalkeeping"] = 10
    return player


def empty_table() -> dict[str, dict[str, int]]:
    return {club["id"]: {"played": 0, "won": 0, "drawn": 0, "lost": 0,
                         "gf": 0, "ga": 0, "points": 0}
            for club in content.CLUBS}


def default_tactics(club_id: str) -> dict[str, str]:
    manager = content.MANAGERS[club_id]
    approach = manager["approach"].lower()
    return {
        "in_shape": manager["formation"], "out_shape": manager["formation"],
        "press": manager["press"], "line": manager["line"],
        "width": "wide" if "wide" in approach or "front" in approach else "balanced",
        "build": manager["build"], "tempo": "standard",
    }


def new_career(club_id: str, seed: int = 1) -> dict[str, Any]:
    """Create an editable, reproducible world; safe to call in a unit test."""
    if club_id not in {club["id"] for club in content.CLUBS}:
        raise ValueError(f"unknown club id: {club_id}")
    players = {player_id: make_player(player)
               for player_id, player in content.PLAYERS.items()}
    clubs: dict[str, dict[str, Any]] = {}
    for club in content.CLUBS:
        cid = club["id"]
        roster = [pid for pid, player in players.items() if player.get("club") == cid]
        wages = sum(players[pid]["wage"] for pid in roster)
        identity = content.CLUB_IDENTITY[cid]
        clubs[cid] = {
            "roster": roster,
            "lineup": [],
            "division": club["division"],
            "tactics": default_tactics(cid),
            "training": {"focus": "Tactical", "intensity": "normal"},
            "finance": {"cash": int(club["budget"] * 5),
                        "transfer_budget": int(club["budget"]),
                        "wage_budget": 38 if cid == "CWC" else 31,
                        "weekly_wages": wages},
            "board_confidence": 64,
            "supporter_mood": 63,
            "attendance": identity["attendance"],
            "expected_place": identity["expectation"],
            "board_patience": identity["patience"],
            "wins": 0,
        }
    career = {
        "version": 2, "seed": int(seed), "club_id": club_id,
        "season": 1, "round": 0, "career_week": 0, "season_complete": False,
        "players": players, "clubs": clubs, "table": empty_table(),
        "fixtures": copy.deepcopy(content.DIVISION_FIXTURES),
        "market": list(content.PROSPECT_IDS), "scouting": {},
        "played_ids": [], "results": [], "season_history": [],
        "news": [{"round": 0, "kind": "club", "text":
                  content.NEWS_LINES["career_open"].format(club=club_by_id(club_id)["name"])}],
        "chemistry": {}, "rivalries": {}, "training_applied_round": -1,
        "live_match": None, "manager_name": "You",
    }
    for cid, club_state in clubs.items():
        club_state["lineup"] = best_lineup(career, cid, club_state["tactics"]["in_shape"])
    return career


def club_by_id(club_id: str) -> dict[str, Any]:
    return next(club for club in content.CLUBS if club["id"] == club_id)


def division_id(career: dict[str, Any], club_id: str | None = None) -> str:
    """Return a club's current competition after any saved promotion movement."""
    cid = club_id or career["club_id"]
    return career["clubs"][cid].get("division", club_by_id(cid)["division"])


def division_clubs(career: dict[str, Any], competition: str | None = None) -> list[str]:
    target = competition or division_id(career)
    return [club["id"] for club in content.CLUBS
            if division_id(career, club["id"]) == target]


def division_name(competition: str) -> str:
    return content.DIVISION_BY_ID[competition]["name"]


def fixtures_for(career: dict[str, Any], competition: str | None = None):
    target = competition or division_id(career)
    return career.get("fixtures", content.DIVISION_FIXTURES)[target]


def generate_double_round_robin(club_ids: list[str]) -> list[list[tuple[str, str]]]:
    """Rebuild a balanced calendar after clubs move between divisions."""
    rotation: list[str | None] = list(club_ids)
    if len(rotation) % 2:
        rotation.append(None)
    first_leg = []
    for round_index in range(len(rotation) - 1):
        fixtures = []
        for pair_index in range(len(rotation) // 2):
            home, away = rotation[pair_index], rotation[-pair_index - 1]
            if home is None or away is None:
                continue
            if (round_index + pair_index) % 2:
                home, away = away, home
            fixtures.append((home, away))
        first_leg.append(fixtures)
        rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
    return first_leg + [[(away, home) for home, away in fixtures]
                        for fixtures in first_leg]


def player_by_id(career: dict[str, Any], player_id: str) -> dict[str, Any]:
    return career["players"][player_id]


def is_available(career: dict[str, Any], player: dict[str, Any]) -> bool:
    return int(player.get("injury_until_round", -1)) <= int(career.get("career_week", career["round"]))


def role_skill(player: dict[str, Any], role: str) -> float:
    if role == "GK":
        score = player.get("goalkeeping", 10) * .72 + player.get("decisions", 50) * .16
        score += player.get("kicking", 10) * .12
    elif role == "DEF":
        score = (player["defending"] * .27 + player["tackling"] * .2
                 + player["positioning"] * .2 + player["pace"] * .12
                 + player["aerial"] * .1 + player["decisions"] * .11)
    elif role == "MID":
        score = (player["passing"] * .22 + player["vision"] * .19
                 + player["first_touch"] * .14 + player["decisions"] * .15
                 + player["stamina"] * .12 + player["technique"] * .1
                 + player["defending"] * .08)
    elif role == "WNG":
        score = (player["pace"] * .22 + player["technique"] * .16
                 + player["first_touch"] * .15 + player["passing"] * .13
                 + player["finishing"] * .12 + player["work_rate"] * .12
                 + player["vision"] * .1)
    else:
        score = (player["finishing"] * .26 + player["composure"] * .18
                 + player["pace"] * .15 + player["first_touch"] * .14
                 + player["decisions"] * .12 + player["strength"] * .08
                 + player["aerial"] * .07)
    preferred = player["position"]
    if preferred == role:
        score += 8
    elif (preferred, role) in (("WNG", "FWD"), ("MID", "WNG"),
                               ("FWD", "WNG"), ("DEF", "MID")):
        score += 2
    else:
        score -= 9
    return score


def best_lineup(career: dict[str, Any], club_id: str,
                formation: str | None = None) -> list[str]:
    """Pick the best available player for every positional slot."""
    shape = formation or career["clubs"][club_id]["tactics"]["in_shape"]
    roles = content.FORMATIONS.get(shape)
    if not roles:
        raise ValueError(f"unknown formation: {shape}")
    candidates = [career["players"][pid]
                  for pid in career["clubs"][club_id]["roster"]
                  if is_available(career, career["players"][pid])]
    selected: list[str] = []
    for role in roles:
        options = [p for p in candidates if p["id"] not in selected]
        if not options:
            break
        chosen = max(options, key=lambda p: (role_skill(p, role), p["overall"], p["id"]))
        selected.append(chosen["id"])
    return selected


def lineup_for(career: dict[str, Any], club_id: str,
               formation: str | None = None) -> list[str]:
    club_state = career["clubs"][club_id]
    shape = formation or club_state["tactics"]["in_shape"]
    available = [pid for pid in club_state["lineup"]
                 if pid in club_state["roster"]
                 and is_available(career, career["players"][pid])]
    if len(available) < 11:
        replacements = [pid for pid in best_lineup(career, club_id, shape)
                        if pid not in available]
        available.extend(replacements[:11 - len(available)])
    if len(available) < 11:
        for pid in club_state["roster"]:
            if pid not in available:
                available.append(pid)
            if len(available) == 11:
                break
    return available[:11]


def toggle_starter(career: dict[str, Any], club_id: str, player_id: str) -> str:
    """Toggle a squad player; adding an eleventh replaces a like-for-like starter."""
    state = career["clubs"][club_id]
    if player_id not in state["roster"]:
        return "That player is not registered at the club."
    player = career["players"][player_id]
    if not is_available(career, player):
        return f"{player['name']} is injured and cannot be selected."
    if player_id in state["lineup"]:
        if len(state["lineup"]) <= 7:
            return "Keep at least seven starters selected; the matchday XI auto-fills."
        state["lineup"].remove(player_id)
        return f"{player['name']} moved to the bench."
    if len(state["lineup"]) >= 11:
        shape = state["tactics"]["in_shape"]
        slots = content.FORMATIONS[shape]
        current_scores = [(role_skill(career["players"][pid], slots[index % len(slots)]),
                           pid)
                          for index, pid in enumerate(state["lineup"])]
        outgoing = min(current_scores)[1]
        state["lineup"].remove(outgoing)
        state["lineup"].append(player_id)
        return f"{player['name']} replaces {career['players'][outgoing]['name']} in the XI."
    state["lineup"].append(player_id)
    return f"{player['name']} added to the starting XI."


def expected_goals(depth: int, lane: str = "center", pressure: int = 1,
                   action: str = "open_play") -> float:
    """Chance quality from location/context only; never reads player skills."""
    base = {0: .035, 1: .055, 2: .085, 3: .17, 4: .29}.get(int(depth), .08)
    base += {"left": -.025, "center": .055, "right": -.025}.get(lane, 0)
    base -= clamp(pressure, 0, 3) * .026
    base += {"through_ball": .045, "cutback": .055, "cross": -.02,
             "counter": .025, "open_play": 0}.get(action, 0)
    return round(clamp(base, .015, .62), 3)


def conversion_probability(xg: float, finishing: float, keeper: float) -> float:
    """Conditional scoring chance; keeper/finisher never change the shot's xG."""
    on_target = clamp(.28 + float(xg) * .85 + (finishing - 55) * .003
                      - .06, .22, .82)
    finishing_factor = clamp(.86 + (finishing - 60) * .0055, .62, 1.12)
    keeper_factor = clamp(1.0 - (keeper - 60) * .0045, .76, 1.22)
    return clamp((float(xg) / on_target) * finishing_factor * keeper_factor, .015, .92)


def on_target_probability(xg: float, finisher: dict[str, Any], pressure: int) -> float:
    """Readiness and confidence affect execution, never the chance's xG."""
    return clamp(.27 + float(xg) * .72 + (finisher["finishing"] - 55) * .0022
                 + (float(finisher.get("sharpness", 50)) - 50) * .001
                 + (float(finisher.get("morale", 60)) - 60) * .00045
                 + (float(finisher.get("form", 6.5)) - 6.5) * .012
                 - pressure * .035, .19, .77)


def effective_goalkeeping(keeper: dict[str, Any]) -> float:
    """Use the keeper's current match readiness around their trained ability."""
    base = float(keeper.get("goalkeeping", keeper.get("reflexes", 50)))
    base += (float(keeper.get("form", 6.5)) - 6.5) * 1.5
    base += (float(keeper.get("morale", 60)) - 60) * .12
    base += (float(keeper.get("sharpness", 50)) - 50) * .06
    return clamp(base, 20, 99)


def _empty_stats() -> dict[str, float | int]:
    return {"shots": 0, "on_target": 0, "goals": 0, "xg": 0.0,
            "chances": 0, "corners": 0, "possessions": 0,
            "passes_attempted": 0, "passes_completed": 0,
            "high_regains": 0, "through_balls": 0, "saves": 0}


def _add_event(match: dict[str, Any], event: dict[str, Any]) -> None:
    event.setdefault("period", match["period"] + 1)
    event.setdefault("minute", min(89, match["period"] * 15 + 1))
    event.setdefault("zone", "C-MID")
    event.setdefault("phase", "transition")
    event.setdefault("action", "play")
    event.setdefault("threat_delta", 0.0)
    event.setdefault("xg", 0.0)
    match["events"].append(event)


def new_match(career: dict[str, Any], home: str, away: str,
              round_index: int | None = None, match_seed: int | None = None) -> dict[str, Any]:
    """Create a persistent match state; simulation can be advanced by period."""
    r = int(career["round"] if round_index is None else round_index)
    key = f"S{career['season']}-W{r + 1:02d}-{home}-{away}"
    seed = int(match_seed if match_seed is not None else
               career["seed"] + career["season"] * 1_000_003
               + r * 10_007 + stable_number(home + away))
    lineups = {home: lineup_for(career, home), away: lineup_for(career, away)}
    tactics = {
        home: copy.deepcopy(career["clubs"][home]["tactics"]),
        away: copy.deepcopy(career["clubs"][away]["tactics"]),
    }
    match = {
        "id": key, "home": home, "away": away, "round": r,
        "seed": seed, "player_club": career["club_id"],
        "period": 0, "minute": 0, "finished": False, "resolved": False,
        "score": {home: 0, away: 0}, "stats": {home: _empty_stats(), away: _empty_stats()},
        "events": [], "lineups": lineups, "tactics": tactics,
        "substitutions": {home: 0, away: 0}, "load": {}, "player_stats": {},
        "current_period_start": 0, "ai_changes": [], "chemistry": {},
        "team_talk": None, "substitution_history": [],
    }
    rivalry = next((rivalry for rivalry in content.RIVALRIES
                    if {rivalry["home"], rivalry["away"]} == {home, away}), None)
    home_name, away_name = club_by_id(home)["name"], club_by_id(away)["name"]
    title = f"{home_name} host {away_name}"
    if rivalry:
        title = f"{rivalry['name']}: {title}"
    _add_event(match, {"kind": "kickoff", "club_id": None,
                       "text": content.NEWS_LINES["kickoff"].format(title=title),
                       "phase": "pre-match", "action": "kickoff"})
    return match


def _player_match_stats(match: dict[str, Any], player_id: str) -> dict[str, Any]:
    return match["player_stats"].setdefault(player_id, {
        "minutes": 0, "goals": 0, "assists": 0, "shots": 0,
        "key_passes": 0, "tackles": 0, "saves": 0,
    })


def _select_player(career: dict[str, Any], match: dict[str, Any], club_id: str,
                   positions: tuple[str, ...], skill: str,
                   rng: random.Random) -> dict[str, Any]:
    players = [career["players"][pid] for pid in match["lineups"][club_id]]
    suitable = [p for p in players if p["position"] in positions]
    options = suitable or players
    weights = [max(1.0, float(p.get(skill, p["overall"])) +
                   role_skill(p, p["position"]) * .08) for p in options]
    return rng.choices(options, weights=weights, k=1)[0]


def _tactical_index(value: str, order: tuple[str, ...] = LEVELS) -> int:
    try:
        return order.index(value)
    except ValueError:
        return 1


def _ai_adapt(match: dict[str, Any], club_id: str) -> None:
    if club_id == match["player_club"]:
        return
    tactic = match["tactics"][club_id]
    goal_diff = match["score"][club_id] - match["score"][
        match["away"] if club_id == match["home"] else match["home"]]
    period = match["period"]
    change = None
    if period >= 3 and goal_diff < 0 and tactic["press"] != "high":
        tactic["press"] = "high"
        tactic["tempo"] = "fast"
        change = content.MATCH_LINES["ai_chase"]
    elif period >= 4 and goal_diff > 0 and tactic["line"] == "high":
        tactic["line"] = "mid"
        tactic["tempo"] = "slow"
        change = content.MATCH_LINES["ai_protect"]
    if change:
        match["ai_changes"].append({"period": period + 1, "club_id": club_id,
                                    "text": change})
        _add_event(match, {"kind": "tactical_change", "club_id": club_id,
                           "text": change, "phase": "touchline",
                           "action": "adapt"})


def _relationship(career: dict[str, Any], first: str, second: str,
                 match: dict[str, Any] | None = None) -> float:
    key = "|".join(sorted((first, second)))
    if match is not None and key in match.get("chemistry", {}):
        return float(match["chemistry"][key])
    return float(career["chemistry"].get(key, 50))


def _record_link(career: dict[str, Any], match: dict[str, Any],
                 first: str, second: str) -> None:
    if first == second:
        return
    key = "|".join(sorted((first, second)))
    match.setdefault("chemistry", {})[key] = round(
        clamp(_relationship(career, first, second, match) + .55, 20, 90), 1)


def _simulate_possession(career: dict[str, Any], match: dict[str, Any],
                         attacking: str, rng: random.Random,
                         minute: int) -> None:
    defending = match["away"] if attacking == match["home"] else match["home"]
    attack_tactic, defend_tactic = match["tactics"][attacking], match["tactics"][defending]
    attack_stats, defend_stats = match["stats"][attacking], match["stats"][defending]
    attack_stats["possessions"] += 1

    passer = _select_player(career, match, attacking, ("MID", "WNG"), "passing", rng)
    runner = _select_player(career, match, attacking, ("FWD", "WNG"), "finishing", rng)
    midfielders = [career["players"][pid] for pid in match["lineups"][attacking]
                   if career["players"][pid]["position"] in ("MID", "WNG")]
    defense = [career["players"][pid] for pid in match["lineups"][defending]
               if career["players"][pid]["position"] in ("DEF", "MID")]
    average_pass = sum(p["passing"] for p in midfielders) / max(1, len(midfielders))
    average_defend = sum(p["defending"] for p in defense) / max(1, len(defense))
    average_fitness = sum(float(match["load"].get(p["id"], p["fitness"]))
                          for p in midfielders) / max(1, len(midfielders))
    average_familiarity = sum(float(p.get("familiarity", 50))
                              for p in midfielders) / max(1, len(midfielders))
    average_sharpness = sum(float(p.get("sharpness", 50))
                            for p in midfielders) / max(1, len(midfielders))
    average_morale = sum(float(p.get("morale", 60))
                         for p in midfielders) / max(1, len(midfielders))
    press = _tactical_index(defend_tactic["press"])
    build = attack_tactic["build"]
    attacking_shape = content.FORMATION_EFFECTS.get(
        attack_tactic.get("in_shape"), content.FORMATION_EFFECTS["4-3-3"])
    defending_shape = content.FORMATION_EFFECTS.get(
        defend_tactic.get("out_shape"), content.FORMATION_EFFECTS["4-3-3"])
    press_cost = (press - 1) * .055
    build_bonus = {"short": (average_pass - 60) * .0025,
                   "balanced": (average_pass - 60) * .0015,
                   "direct": (runner["pace"] - 60) * .0022 - .015}[build]
    relationship = _relationship(career, passer["id"], runner["id"], match)
    stamina_factor = clamp((average_fitness - 45) / 55, .5, 1.0)
    pass_chance = clamp(.65 + build_bonus + (average_pass - average_defend) * .001
                        - press_cost + (relationship - 50) * .0008
                        + (average_familiarity - 50) * .0012
                        + (average_sharpness - 50) * .00035
                        + (average_morale - 60) * .0004
                        + attacking_shape["pass_support"]
                        - defending_shape["midfield_screen"]
                        + (stamina_factor - .8) * .12, .43, .84)
    attack_stats["passes_attempted"] += 1
    passer_stats = _player_match_stats(match, passer["id"])

    if rng.random() > pass_chance:
        if press >= 2:
            defend_stats["high_regains"] += 1
            tackler = _select_player(career, match, defending, ("MID", "DEF"), "tackling", rng)
            _player_match_stats(match, tackler["id"])["tackles"] += 1
            template = rng.choice(content.COMMENTARY["regain_high"])
            text = template.format(player=tackler["name"], detail=runner["name"])
            kind = "high_regain"
            explanation = content.TACTICAL_REASONS["high_regain"].format(
                press=defend_tactic["press"])
        else:
            text = rng.choice(content.COMMENTARY["bad_connection"])
            kind = "turnover"
            explanation = content.TACTICAL_REASONS["bad_link"].format(reason=text)
        _add_event(match, {"kind": kind, "club_id": defending if press >= 2 else attacking,
                           "actor_id": passer["id"], "target_id": runner["id"],
                           "text": text, "minute": minute, "phase": "build-up",
                           "action": "turnover", "tactical_reason": explanation,
                           "threat_delta": -.035})
        return

    attack_stats["passes_completed"] += 1
    line_level = _tactical_index(defend_tactic["line"])
    directness = {"short": 0, "balanced": 1, "direct": 2}[build]
    behind_probability = clamp(.13 + directness * .14 + (line_level - 1) * .12
                               + defending_shape["space_behind"]
                               + max(0, runner["pace"] - 65) * .002, .04, .72)
    through_ball = rng.random() < behind_probability
    base_progress = .51 + (average_pass - average_defend) * .0025
    if through_ball:
        base_progress += .14
        attack_stats["through_balls"] += 1
        depth = rng.choice((3, 4))
        phase = "penetration"
        action = "through_ball"
        zone = "C-FINAL" if attack_tactic["width"] != "wide" else rng.choice(("L-FINAL", "R-FINAL"))
        template = rng.choice(content.COMMENTARY["through_ball"])
        text = template.format(player=passer["name"], detail=runner["name"])
        explanation = content.TACTICAL_REASONS["through_ball"].format(
            build=build.title(), line=defend_tactic["line"])
    else:
        depth = rng.choices((1, 2, 3, 4), weights=(.12, .34, .39, .15), k=1)[0]
        phase = "progression"
        action = "combination" if build == "short" else "carry"
        if attack_tactic["width"] == "wide":
            lane = rng.choices(("left", "center", "right"), weights=(.42, .16, .42), k=1)[0]
        elif attack_tactic["width"] == "narrow":
            lane = rng.choices(("left", "center", "right"), weights=(.2, .6, .2), k=1)[0]
        else:
            lane = rng.choice(("left", "center", "right"))
        zone = f"{lane[0].upper()}-" + ("FINAL" if depth >= 3 else "MID")
        if lane != "center" and depth >= 3:
            template = rng.choice(content.COMMENTARY["wide_attack"])
        else:
            template = rng.choice(content.COMMENTARY["central_progression"])
        text = template.format(player=passer["name"], detail=runner["name"])
        explanation = content.TACTICAL_REASONS["build_lane"].format(
            build=build, lane=lane, line=defend_tactic["line"])

    progress_chance = clamp(base_progress + (stamina_factor - .8) * .18
                            + (attack_tactic["tempo"] == "slow") * .035, .34, .86)
    if rng.random() > progress_chance:
        text = rng.choice(content.COMMENTARY["turnover"])
        _add_event(match, {"kind": "turnover", "club_id": defending,
                           "attacking_club_id": attacking,
                           "actor_id": passer["id"], "target_id": runner["id"],
                           "text": text, "minute": minute, "phase": phase,
                           "zone": zone, "action": action, "pass_action": action,
                           "tactical_reason": content.TACTICAL_REASONS["line_closed"].format(
                               line=defend_tactic["line"]),
                           "threat_delta": -.04})
        return

    is_wide = zone.startswith(("L-", "R-"))
    pressure = int(clamp(press + (1 if is_wide and defend_tactic["width"] == "narrow" else 0), 0, 3))
    attack_chance = .52 + (depth - 2) * .095
    attack_chance += attacking_shape["box_presence"]
    if through_ball:
        attack_chance += .11
    if is_wide and attack_tactic["width"] == "wide":
        attack_chance += .04
    if attack_tactic["tempo"] == "fast":
        attack_chance += .025
    if rng.random() > clamp(attack_chance, .28, .82):
        if is_wide and rng.random() < (.18 if attack_tactic["width"] == "wide" else .1):
            attack_stats["corners"] += 1
            cross_text = rng.choice(content.COMMENTARY["blocked_cross_corner"])
            _add_event(match, {"kind": "corner", "club_id": attacking,
                               "actor_id": passer["id"], "text":
                               cross_text.format(player=passer["name"]),
                               "minute": minute, "phase": "final-third", "zone": zone,
                               "action": "cross", "pass_action": action,
                               "tactical_reason":
                               content.TACTICAL_REASONS["wide_cross"],
                               "threat_delta": .02})
        else:
            _add_event(match, {"kind": "blocked_attack", "club_id": attacking,
                               "actor_id": passer["id"], "text":
                               content.MATCH_LINES["blocked_attack"].format(player=passer["name"]),
                               "minute": minute, "phase": "final-third", "zone": zone,
                               "action": action, "pass_action": action,
                               "tactical_reason": explanation,
                               "threat_delta": -.01})
        return

    shot_action = "through_ball" if through_ball else (
        "cross" if is_wide and rng.random() < .44 else
        "cutback" if depth == 4 and rng.random() < .36 else "open_play")
    lane_name = "left" if zone.startswith("L-") else (
        "right" if zone.startswith("R-") else "center")
    xg = expected_goals(depth, lane_name, pressure, shot_action)
    finisher = runner if runner["position"] in ("FWD", "WNG") else passer
    passer_stats["key_passes"] += 1
    goalkeepers = [career["players"][pid] for pid in match["lineups"][defending]
                   if career["players"][pid]["position"] == "GK"]
    keeper = goalkeepers[0] if goalkeepers else max(
        (career["players"][pid] for pid in match["lineups"][defending]),
        key=lambda p: p.get("goalkeeping", 0))
    attack_stats["shots"] += 1
    attack_stats["chances"] += 1
    attack_stats["xg"] = round(float(attack_stats["xg"]) + xg, 3)
    _player_match_stats(match, finisher["id"])["shots"] += 1
    on_target = rng.random() < on_target_probability(xg, finisher, pressure)
    goal = on_target and rng.random() < conversion_probability(
        xg, finisher["finishing"], effective_goalkeeping(keeper))
    if on_target:
        attack_stats["on_target"] += 1
    if goal:
        attack_stats["goals"] += 1
        match["score"][attacking] += 1
        scorer_stats = _player_match_stats(match, finisher["id"])
        scorer_stats["goals"] += 1
        assist = None
        if rng.random() < .7:
            assist = _select_player(career, match, attacking, ("MID", "WNG"), "vision", rng)
            if assist["id"] == finisher["id"]:
                assist = None
        if assist:
            _player_match_stats(match, assist["id"])["assists"] += 1
            _record_link(career, match, assist["id"], finisher["id"])
        template = rng.choice(content.COMMENTARY["goal"])
        text = template.format(player=finisher["name"], detail=assist["name"] if assist else "")
        kind = "goal"
        result = "goal"
        threat_delta = 1.0 - xg
    elif on_target:
        defend_stats["saves"] += 1
        _player_match_stats(match, keeper["id"])["saves"] += 1
        text = rng.choice(content.COMMENTARY["save"])
        kind, result, threat_delta = "save", "saved", -xg
    else:
        template = rng.choice(content.COMMENTARY["miss"])
        text = template.format(player=finisher["name"], detail="")
        kind, result, threat_delta = "miss", "wide", -xg
    _add_event(match, {"kind": kind, "club_id": attacking,
                       "actor_id": finisher["id"],
                       "target_id": assist["id"] if goal and assist else None,
                       "keeper_id": keeper["id"], "text": text,
                       "minute": minute, "phase": "shot", "zone": zone,
                       "action": shot_action, "pass_action": action, "result": result,
                       "tactical_reason": content.TACTICAL_REASONS["shot"].format(
                           action=shot_action.replace("_", " "), zone=zone,
                           pressure=pressure, xg=xg),
                       "threat_delta": round(threat_delta, 3), "xg": xg,
                       "on_target": on_target})


def simulate_period(career: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
    """Advance one 15-minute window with a reproducible independent RNG."""
    if match["finished"]:
        return match
    for cid in (match["home"], match["away"]):
        _ai_adapt(match, cid)
    period_index = int(match["period"])
    match["current_period_start"] = len(match["events"])
    for cid in (match["home"], match["away"]):
        tactic = match["tactics"][cid]
        press = _tactical_index(tactic["press"])
        tempo = tactic["tempo"]
        base_load = 1.05 + press * .22 + {"slow": -.2, "standard": 0, "fast": .32}[tempo]
        for pid in match["lineups"][cid]:
            match["load"][pid] = max(25.0, float(match["load"].get(
                pid, career["players"][pid]["fitness"])) - base_load)
            _player_match_stats(match, pid)["minutes"] += 15
        count = {"slow": 3, "standard": 4, "fast": 5}[tempo]
        rng = random.Random(int(match["seed"] + period_index * 100_003
                                + stable_number(cid) * 307))
        count = int(clamp(count + rng.choice((-1, 0, 0, 1)), 2, 6))
        for possession_number in range(count):
            minute = min(89, period_index * 15 + rng.randint(1, 15))
            _simulate_possession(career, match, cid, rng, minute)
    match["period"] += 1
    match["minute"] = min(MATCH_MINUTES, match["period"] * 15)
    if match["period"] >= content.MATCH_PERIODS:
        match["finished"] = True
    validate_match(match)
    return match


def simulate_match(career: dict[str, Any], home: str, away: str,
                   match_seed: int | None = None,
                   round_index: int | None = None) -> dict[str, Any]:
    """Quick-sim path: same period engine and event ledger as managed matches."""
    match = new_match(career, home, away, round_index, match_seed)
    while not match["finished"]:
        simulate_period(career, match)
    return match


def validate_match(match: dict[str, Any]) -> None:
    """Assert score and event-derived match statistics have not drifted."""
    opponent_of = {match["home"]: match["away"], match["away"]: match["home"]}
    for cid in (match["home"], match["away"]):
        events = [event for event in match["events"] if event.get("club_id") == cid]
        goals = sum(event.get("kind") == "goal" for event in events)
        shots = [event for event in events
                 if event.get("kind") in ("goal", "save", "miss")]
        shot_count = len(shots)
        xg = round(sum(float(event.get("xg", 0.0)) for event in shots), 3)
        stats = match["stats"][cid]
        if goals != match["score"][cid] or goals != stats["goals"]:
            raise AssertionError(f"goal ledger mismatch for {cid}")
        if shot_count != stats["shots"] or xg != round(float(stats["xg"]), 3):
            raise AssertionError(f"shot ledger mismatch for {cid}")
        on_target = sum(bool(event.get("on_target")) for event in shots)
        corners = sum(event.get("kind") == "corner" for event in events)
        regains = sum(event.get("kind") == "high_regain" for event in events)
        through_balls = sum(event.get("pass_action", event.get("action")) == "through_ball"
                            and event.get("attacking_club_id", event.get("club_id")) == cid
                            for event in match["events"])
        saves = sum(event.get("kind") == "save"
                    and event.get("club_id") == opponent_of[cid]
                    for event in match["events"])
        if on_target != stats["on_target"] or goals > on_target:
            raise AssertionError(f"shot-on-target ledger mismatch for {cid}")
        if corners != stats["corners"] or regains != stats["high_regains"]:
            raise AssertionError(f"phase-stat ledger mismatch for {cid}")
        if through_balls != stats["through_balls"] or saves != stats["saves"]:
            raise AssertionError(f"chance ledger mismatch for {cid}")
        if stats["passes_attempted"] != stats["possessions"]:
            raise AssertionError(f"possession ledger mismatch for {cid}")
        if not 0 <= stats["passes_completed"] <= stats["passes_attempted"]:
            raise AssertionError(f"pass completion mismatch for {cid}")
    if match["score"][match["home"]] < 0 or match["score"][match["away"]] < 0:
        raise AssertionError("negative match score")


def training_effect(career: dict[str, Any], player_id: str, focus: str,
                   intensity: str = "normal") -> dict[str, float]:
    """Apply one authored training plan; returned values make the cost visible."""
    player = career["players"][player_id]
    if focus not in content.TRAINING_PLANS:
        raise ValueError(f"unknown training focus: {focus}")
    if intensity not in TRAINING_INTENSITIES:
        raise ValueError(f"unknown training intensity: {intensity}")
    factor = {"low": .68, "normal": 1.0, "high": 1.28}[intensity]
    personality = next((row for row in content.PERSONALITIES
                        if row["id"] == player["personality"]), content.PERSONALITIES[0])
    development = float(personality["growth"])
    gained: dict[str, float] = {}
    if not is_available(career, player):
        player["fitness"] = int(clamp(player["fitness"] + 5, 0, 100))
        return {"fitness": 5.0}

    if focus == "Recovery":
        fitness_gain = 14 * factor
        player["fitness"] = int(clamp(player["fitness"] + fitness_gain, 0, 100))
        player["sharpness"] = round(clamp(player["sharpness"] + 1.5, 0, 100), 1)
        player["morale"] = int(clamp(player["morale"] + .4, 0, 100))
        gained["fitness"] = round(fitness_gain, 2)
    else:
        focus_skills = {
            "Tactical": {"decisions": .24, "passing": .12, "familiarity": 2.7},
            "Finishing": {"finishing": .27, "composure": .19},
            "Defending": {"defending": .25, "positioning": .2, "tackling": .17},
            "Conditioning": {"stamina": .24, "work_rate": .16},
        }
        for skill, base in focus_skills[focus].items():
            amount = base * factor * (development if skill != "familiarity" else 1.0)
            current = float(player.get(skill, 50))
            ceiling = 100 if skill == "familiarity" else max(
                current, min(99, int(player["potential"]) + 8))
            player[skill] = round(clamp(current + amount, 0, ceiling), 2)
            gained[skill] = round(float(player[skill]) - current, 2)
        fitness_cost = {"low": 1.5, "normal": 4, "high": 8}[intensity]
        player["fitness"] = int(clamp(player["fitness"] - fitness_cost, 0, 100))
        player["sharpness"] = round(clamp(player["sharpness"] + 2.2 * factor, 0, 100), 1)
        gained["fitness"] = -float(fitness_cost)
    player["overall"] = player_overall(player)
    return gained


def prepare_week(career: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply one training microcycle to every club before its round begins."""
    if career["round"] >= content.SEASON_ROUNDS:
        return []
    if int(career.get("training_applied_round", -1)) == int(career["round"]):
        return []
    reports = []
    for club in content.CLUBS:
        cid = club["id"]
        state = career["clubs"][cid]
        if cid == career["club_id"]:
            focus = state["training"]["focus"]
            intensity = state["training"]["intensity"]
        else:
            roster = [career["players"][pid] for pid in state["roster"]]
            average_fitness = sum(p["fitness"] for p in roster) / max(1, len(roster))
            focus = "Recovery" if average_fitness < 72 else "Tactical"
            intensity = "low" if average_fitness < 62 else "normal"
        totals: dict[str, float] = {}
        for pid in state["roster"]:
            result = training_effect(career, pid, focus, intensity)
            for key, amount in result.items():
                totals[key] = totals.get(key, 0.0) + amount
        state["training"]["last_focus"] = focus
        reports.append({"club_id": cid, "focus": focus, "intensity": intensity,
                        "fitness_delta": round(totals.get("fitness", 0.0), 1),
                        "skill_work": round(sum(value for key, value in totals.items()
                                                 if key != "fitness"), 1)})
    career["training_applied_round"] = int(career["round"])
    career.setdefault("training_history", []).append({
        "season": career["season"], "round": career["round"] + 1,
        "club_id": career["club_id"],
        "focus": career["clubs"][career["club_id"]]["training"]["focus"],
    })
    career["training_history"] = career["training_history"][-80:]
    return reports


def _table_order(career: dict[str, Any], club_ids: list[str] | None = None) -> list[str]:
    eligible = club_ids if club_ids is not None else division_clubs(career)
    return sorted(eligible, key=lambda cid: (
        -career["table"][cid]["points"],
        -(career["table"][cid]["gf"] - career["table"][cid]["ga"]),
        -career["table"][cid]["gf"],
        club_by_id(cid)["name"].casefold()))


def table_rows(career: dict[str, Any]) -> list[list[str]]:
    rows = []
    for rank, cid in enumerate(_table_order(career), start=1):
        stats = career["table"][cid]
        gd = stats["gf"] - stats["ga"]
        rows.append([rank, club_by_id(cid)["name"], stats["played"], stats["won"],
                     stats["drawn"], stats["lost"], f"{stats['gf']}:{stats['ga']}",
                     f"{gd:+d}", stats["points"]])
    return rows


def current_fixture(career: dict[str, Any]) -> tuple[str, str] | None:
    if career["round"] >= content.SEASON_ROUNDS:
        return None
    for fixture in fixtures_for(career)[career["round"]]:
        if career["club_id"] in fixture:
            return fixture
    raise AssertionError(f"club {career['club_id']} has no fixture in round {career['round'] + 1}")


def _news(career: dict[str, Any], text: str, kind: str = "world") -> None:
    career.setdefault("news", []).append({"round": career.get("round", 0) + 1,
                                           "season": career.get("season", 1),
                                           "kind": kind, "text": text})
    career["news"] = career["news"][-80:]


def _confidence_after_result(career: dict[str, Any], club_id: str,
                             outcome: str, opponent: str) -> int:
    state = career["clubs"][club_id]
    delta = {"win": 2, "draw": 0, "loss": -3}[outcome]
    expected = int(state["expected_place"])
    opponent_expected = int(career["clubs"][opponent]["expected_place"])
    if outcome == "win" and expected < opponent_expected:
        delta += 1
    elif outcome == "loss" and expected < opponent_expected:
        delta -= 1
    if int(state["finance"]["cash"]) < 0:
        delta -= 2
    state["board_confidence"] = int(clamp(state["board_confidence"] + delta, 0, 100))
    return delta


def _update_rivalry(career: dict[str, Any], home: str, away: str,
                    home_goals: int, away_goals: int) -> None:
    configured = next((r for r in content.RIVALRIES
                       if {r["home"], r["away"]} == {home, away}), None)
    if not configured:
        return
    key = "|".join(sorted((home, away)))
    record = career["rivalries"].setdefault(key, {"meetings": 0, "home_wins": 0,
                                                   "away_wins": 0, "draws": 0,
                                                   "last_result": "not played"})
    record["meetings"] += 1
    if home_goals > away_goals:
        record["home_wins"] += 1
        record["last_result"] = f"{home} won {home_goals}-{away_goals}"
    elif away_goals > home_goals:
        record["away_wins"] += 1
        record["last_result"] = f"{away} won {away_goals}-{home_goals}"
    else:
        record["draws"] += 1
        record["last_result"] = f"Drew {home_goals}-{away_goals}"


def _injury_check(career: dict[str, Any], match: dict[str, Any],
                  rng: random.Random) -> list[str]:
    injuries = []
    for pid, record in match["player_stats"].items():
        minutes = int(record["minutes"])
        player = career["players"][pid]
        if minutes < 25 or not is_available(career, player):
            continue
        tactic = match["tactics"][player["club"]]
        press = _tactical_index(tactic["press"])
        fatigue = max(0, 82 - int(player["fitness"]))
        chance = clamp(.004 + fatigue * .00065 + press * .0028
                       + max(0, minutes - 60) * .00007, .004, .065)
        if rng.random() < chance:
            injury = rng.choice(content.INJURIES)
            duration = rng.randint(*injury["rounds"])
            player["injury"] = injury["name"]
            player["injury_until_round"] = int(career.get("career_week", career["round"])) + duration + 1
            injuries.append(content.NEWS_LINES["injury"].format(
                player=player["name"], injury=injury["name"], duration=duration))
    return injuries


def apply_match_result(career: dict[str, Any], match: dict[str, Any]) -> bool:
    """Reconcile a finished fixture once across table, people, money, and news."""
    if not match["finished"]:
        raise ValueError("cannot record a match before full time")
    if match.get("resolved") or match["id"] in career["played_ids"]:
        return False
    validate_match(match)
    home, away = match["home"], match["away"]
    hg, ag = int(match["score"][home]), int(match["score"][away])
    table = career["table"]
    home_line, away_line = table[home], table[away]
    home_line["played"] += 1
    away_line["played"] += 1
    home_line["gf"] += hg
    home_line["ga"] += ag
    away_line["gf"] += ag
    away_line["ga"] += hg
    if hg > ag:
        outcome_home, outcome_away = "win", "loss"
    elif ag > hg:
        outcome_home, outcome_away = "loss", "win"
    else:
        outcome_home = outcome_away = "draw"
    for cid, outcome in ((home, outcome_home), (away, outcome_away)):
        line = table[cid]
        if outcome == "win":
            line["won"] += 1
            line["points"] += 3
            career["clubs"][cid]["wins"] += 1
        elif outcome == "draw":
            line["drawn"] += 1
            line["points"] += 1
        else:
            line["lost"] += 1
        opponent = away if cid == home else home
        _confidence_after_result(career, cid, outcome, opponent)
        club_state = career["clubs"][cid]
        mood_delta = {"win": 3, "draw": 0, "loss": -3}[outcome]
        if match["tactics"][cid]["width"] == "wide" and match["stats"][cid]["corners"]:
            mood_delta += 1
        club_state["supporter_mood"] = int(clamp(club_state["supporter_mood"] + mood_delta, 0, 100))

    home_finance = career["clubs"][home]["finance"]
    away_finance = career["clubs"][away]["finance"]
    home_state = career["clubs"][home]
    home_club = club_by_id(home)
    attendance = int(home_state["attendance"] *
                     (.76 + home_state["supporter_mood"] * .003
                      + max(-.05, min(.05, (home_state["board_confidence"] - 60) * .001))))
    gate = max(0, round(attendance * 5.8 / 1000))
    home_finance["cash"] += gate - home_finance["weekly_wages"]
    away_finance["cash"] -= away_finance["weekly_wages"]
    prize = 7 if outcome_home == "win" else 3 if outcome_home == "draw" else 0
    home_finance["cash"] += prize
    away_finance["cash"] += 7 if outcome_away == "win" else 3 if outcome_away == "draw" else 0
    home_finance["transfer_budget"] = max(0, int(home_finance["transfer_budget"] + prize))
    away_finance["transfer_budget"] = max(0, int(away_finance["transfer_budget"]
                                                 + (7 if outcome_away == "win" else 3 if outcome_away == "draw" else 0)))

    for cid in (home, away):
        for pid, stats in match["player_stats"].items():
            player = career["players"].get(pid)
            if not player or player["club"] != cid:
                continue
            minutes = int(stats["minutes"])
            if minutes:
                player["career_apps"] += 1
                player["career_goals"] += int(stats["goals"])
                player["career_assists"] += int(stats["assists"])
            rating = 6.15 + int(stats["goals"]) * 1.0 + int(stats["assists"]) * .65
            rating += int(stats["key_passes"]) * .055 + int(stats["tackles"]) * .04
            rating += int(stats["saves"]) * .18
            if minutes == 0:
                rating -= .12
            rating = clamp(rating, 4.0, 10.0)
            player["form"] = round(clamp(float(player["form"]) * .72 + rating * .28, 1.0, 10.0), 2)
            result = outcome_home if cid == home else outcome_away
            mood = {"win": 2.4, "draw": .5, "loss": -1.6}[result]
            mood += (rating - 6.4) * .7
            if minutes >= 60:
                mood += .5
                player["trust"] = int(clamp(player["trust"] + 1, 0, 100))
            elif minutes == 0:
                mood -= .75
            player["morale"] = int(clamp(player["morale"] + mood, 0, 100))
            load = float(match["load"].get(pid, player["fitness"]))
            press = _tactical_index(match["tactics"][cid]["press"])
            player["fitness"] = int(clamp(load - (press * 1.2) + (3 if minutes == 0 else 0), 0, 100))

    injury_rng = random.Random(int(match["seed"] ^ 0x5A17C9))
    injury_news = _injury_check(career, match, injury_rng)
    winner = home if hg > ag else away if ag > hg else None
    result_text = f"{home_club['name']} {hg}–{ag} {club_by_id(away)['name']}"
    if winner:
        _news(career, content.NEWS_LINES["win"].format(
            result=result_text, winner=club_by_id(winner)["name"]), "result")
    else:
        _news(career, content.NEWS_LINES["draw"].format(result=result_text), "result")
    if injury_news:
        for line in injury_news:
            _news(career, line, "medical")
    for event in match["events"]:
        if event.get("kind") == "goal":
            scorer = career["players"].get(event.get("actor_id"), {})
            if scorer:
                _news(career, content.NEWS_LINES["goal"].format(
                    player=scorer["name"], result=result_text), "player")
    _update_rivalry(career, home, away, hg, ag)
    career.setdefault("chemistry", {}).update(match.get("chemistry", {}))
    if winner == career["club_id"] and {home, away} == {"BRP", "GLA"}:
        ts.unlock("derby-win", "Salt and Glass",
                  "Won the Brineport–Glasswind derby")
    career["played_ids"].append(match["id"])
    career["results"].append({"id": match["id"], "season": career["season"],
                              "division": division_id(career, home),
                              "round": match["round"] + 1, "home": home, "away": away,
                              "home_goals": hg, "away_goals": ag,
                              "stats": copy.deepcopy(match["stats"]),
                              "events": [e for e in match["events"]
                                         if e.get("kind") in ("goal", "save", "miss", "tactical_change")][-24:]})
    career["results"] = career["results"][-200:]
    match["resolved"] = True
    return True


def _match_seed(career: dict[str, Any], round_index: int,
                home: str, away: str) -> int:
    return int(career["seed"] + career["season"] * 1_000_003
               + round_index * 10_007 + stable_number(home + away))


def complete_user_match(career: dict[str, Any], match: dict[str, Any]) -> list[dict[str, Any]]:
    """Settle the user's match and every division's fixtures for this week."""
    if not match["finished"]:
        raise ValueError("finish the match before advancing the week")
    if int(match["round"]) != int(career["round"]):
        raise ValueError("match belongs to a different round")
    if not apply_match_result(career, match):
        return []
    resolved = [match]
    for division in content.DIVISIONS:
        for home, away in fixtures_for(career, division["id"])[career["round"]]:
            if {home, away} == {match["home"], match["away"]}:
                continue
            other = simulate_match(career, home, away,
                                   _match_seed(career, career["round"], home, away),
                                   career["round"])
            apply_match_result(career, other)
            resolved.append(other)
    career["round"] += 1
    career["career_week"] = int(career.get("career_week", 0)) + 1
    career["training_applied_round"] = -1
    career["live_match"] = None
    if career["round"] >= content.SEASON_ROUNDS:
        finish_season(career)
    else:
        round_results = [item for item in career["results"]
                         if item["season"] == career["season"]
                         and item["round"] == career["round"]]
        _news(career, content.NEWS_LINES["round_close"].format(
            round=career["round"], count=len(round_results),
            leader=club_by_id(_table_order(career)[0])["name"]), "digest")
    return resolved


def finish_season(career: dict[str, Any]) -> dict[str, Any]:
    if career["season_complete"]:
        return career["season_history"][-1]
    orders = {division["id"]: _table_order(career, division_clubs(career, division["id"]))
              for division in content.DIVISIONS}
    champions = {comp: order[0] for comp, order in orders.items()}
    user_division = division_id(career)
    user_order = orders[user_division]
    user_place = user_order.index(career["club_id"]) + 1
    division_tables = {
        comp: {cid: copy.deepcopy(career["table"][cid]) for cid in order}
        for comp, order in orders.items()
    }
    promoted = orders["tideway"][:content.PROMOTION_PLACES]
    relegated = orders["sable"][-content.PROMOTION_PLACES:]
    record = {"season": career["season"], "champion": champions[user_division],
              "champions": champions, "user_division": user_division,
              "user_place": user_place, "table": division_tables[user_division],
              "division_tables": division_tables,
              "movement": {"promoted": promoted, "relegated": relegated},
              "goals_for": career["table"][career["club_id"]]["gf"],
              "goals_against": career["table"][career["club_id"]]["ga"]}
    career["season_history"].append(record)
    career["season_complete"] = True
    prize = max(20, 100 - user_place * 12)
    finance = career["clubs"][career["club_id"]]["finance"]
    finance["cash"] += prize
    finance["transfer_budget"] += max(0, prize // 4)
    ranks = {cid: rank for comp, order in orders.items()
             for rank, cid in enumerate(order, start=1)}
    for cid, state in career["clubs"].items():
        rank = ranks[cid]
        expected = state["expected_place"]
        state["board_confidence"] = int(clamp(state["board_confidence"]
                                                + clamp(expected - rank, -3, 4) * 4, 0, 100))
    _news(career, content.NEWS_LINES["season_close"].format(
        season=career["season"], champion=club_by_id(champions[user_division])["name"],
        place=ordinal(user_place)), "season")
    for cid in promoted:
        _news(career, content.NEWS_LINES["promoted"].format(
            club=club_by_id(cid)["name"], place=ordinal(orders["tideway"].index(cid) + 1),
            division=division_name("tideway")), "promotion")
    if career["club_id"] in promoted:
        ts.unlock("promotion", "Up the Coast",
                  "Earned promotion from Tideway to the Sable Coast League")
    for cid in relegated:
        _news(career, content.NEWS_LINES["relegated"].format(
            club=club_by_id(cid)["name"], place=ordinal(orders["sable"].index(cid) + 1),
            division=division_name("sable")), "relegation")
    ts.unlock("season-finished", "Final Whistle",
              "Completed a full Sable Coast League season")
    return record


def ordinal(number: int) -> str:
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def academy_intake(career: dict[str, Any], club_id: str, season: int) -> str:
    """Generate one persistent prospect per club from editable name pools."""
    roster = career["clubs"][club_id]["roster"]
    position_counts = {position: 0 for position in POSITION_NAMES}
    for pid in roster:
        position_counts[career["players"][pid]["position"]] += 1
    rng = random.Random(int(career["seed"] + season * 912_367 + stable_number(club_id) * 7))
    lowest = min(position_counts.values())
    position = rng.choice([p for p, count in position_counts.items() if count == lowest])
    player_id = f"AC-S{season:02d}-{club_id}-01"
    while player_id in career["players"]:
        player_id += "X"
    raw = {"id": player_id, "club": club_id,
           "name": f"{rng.choice(content.FIRST_NAMES)} {rng.choice(content.SURNAMES)}",
           "position": position, "pace": rng.randint(43, 76),
           "passing": rng.randint(42, 76), "finishing": rng.randint(35, 75),
           "defending": rng.randint(38, 77), "stamina": rng.randint(48, 78),
           "age": rng.randint(16, 18), "value": rng.randint(8, 28),
           "morale": 70, "fitness": 100}
    player = make_player(raw)
    player["potential"] = rng.randint(min(84, max(player["overall"] + 4, 56)), 84)
    player["wage"] = max(.5, round(player["wage"] / 3, 1))
    player["wage_demand"] = round(player["wage"] * 1.35, 1)
    player["homegrown"] = True
    career["players"][player_id] = player
    career["clubs"][club_id]["roster"].append(player_id)
    return player_id


def begin_next_season(career: dict[str, Any]) -> list[str]:
    if not career["season_complete"]:
        raise ValueError("the current season is still in progress")
    season = int(career["season"]) + 1
    movement = career["season_history"][-1].get("movement", {})
    promoted = movement.get("promoted", [])
    relegated = movement.get("relegated", [])
    for cid in promoted:
        career["clubs"][cid]["division"] = "sable"
        career["clubs"][cid]["expected_place"] = max(3, int(career["clubs"][cid]["expected_place"]))
    for cid in relegated:
        career["clubs"][cid]["division"] = "tideway"
        career["clubs"][cid]["expected_place"] = min(3, int(career["clubs"][cid]["expected_place"]))
    youth = []
    for club in content.CLUBS:
        cid = club["id"]
        for pid in career["clubs"][cid]["roster"]:
            player = career["players"][pid]
            player["age"] = min(40, int(player["age"]) + 1)
            player["contract_years"] = max(0, int(player.get("contract_years", 0)) - 1)
            player["fitness"] = int(clamp(player["fitness"] + 8, 0, 100))
        youth.append(academy_intake(career, cid, season))
        career["clubs"][cid]["finance"]["weekly_wages"] = sum(
            career["players"][pid]["wage"] for pid in career["clubs"][cid]["roster"])
    career["season"] = season
    career["round"] = 0
    career["season_complete"] = False
    career["table"] = empty_table()
    career["fixtures"] = {
        division["id"]: generate_double_round_robin(
            division_clubs(career, division["id"]))
        for division in content.DIVISIONS
    }
    career["played_ids"] = []
    career["training_applied_round"] = -1
    career["live_match"] = None
    _news(career, content.NEWS_LINES["season_open"].format(
        season=season, count=len(youth)), "academy")
    for cid in promoted:
        _news(career, f"{club_by_id(cid)['name']} begin Season {season} in {division_name('sable')}.",
              "promotion")
    for cid in relegated:
        _news(career, f"{club_by_id(cid)['name']} begin Season {season} in {division_name('tideway')}.",
              "relegation")
    return youth


def simulate_full_season(career: dict[str, Any]) -> dict[str, Any]:
    """Headless integration path used to verify both leagues' full calendars."""
    while career["round"] < content.SEASON_ROUNDS:
        prepare_week(career)
        fixture = current_fixture(career)
        assert fixture is not None
        home, away = fixture
        match = simulate_match(career, home, away,
                               _match_seed(career, career["round"], home, away),
                               career["round"])
        complete_user_match(career, match)
    return career["season_history"][-1]


def role_fit(career: dict[str, Any], club_id: str, player_id: str) -> int:
    player = career["players"][player_id]
    current = [career["players"][pid] for pid in career["clubs"][club_id]["roster"]]
    same = sum(p["position"] == player["position"] for p in current)
    shortage = max(0, 3 - same)
    shape_need = content.FORMATIONS[career["clubs"][club_id]["tactics"]["in_shape"]]
    shape_need_count = sum(role == player["position"] for role in shape_need)
    base = 60 + shortage * 7 + min(8, shape_need_count * 2)
    player_skill = player_overall(player)
    team_median = sorted(player_overall(p) for p in current)[len(current) // 2]
    base += clamp((player_skill - team_median) * .42, -12, 18)
    return round(clamp(base, 20, 98))


def scout_target(career: dict[str, Any], player_id: str) -> dict[str, Any]:
    """Buy an uncertainty-bearing report; repeated looks narrow its ranges."""
    if player_id not in career["market"]:
        raise ValueError("that player is no longer available")
    report = career["scouting"].get(player_id, {"visits": 0})
    club = career["clubs"][career["club_id"]]
    cost = 2
    if club["finance"]["cash"] < cost:
        raise ValueError("the scout budget cannot cover a fresh report")
    club["finance"]["cash"] -= cost
    visits = min(3, int(report.get("visits", 0)) + 1)
    error = {1: .18, 2: .1, 3: .045}[visits]
    target = career["players"][player_id]
    rng = random.Random(int(career["seed"] + stable_number(player_id) * visits + 80_071))
    skill_estimates = {}
    for skill in ("pace", "passing", "finishing", "defending", "stamina", "technique"):
        truth = int(target[skill])
        margin = max(2, round(65 * error))
        estimate = int(clamp(truth + rng.randint(-margin, margin), 1, 99))
        skill_estimates[skill] = [max(1, estimate - margin), min(99, estimate + margin)]
    value = int(target["value"])
    wage = float(target["wage_demand"])
    report = {
        "visits": visits,
        "confidence": {1: "LOW", 2: "MED", 3: "HIGH"}[visits],
        "fee_range": [max(1, round(value * (1 - error))), round(value * (1 + error))],
        "wage_range": [max(.5, round(wage * (1 - error), 1)),
                       round(wage * (1 + error), 1)],
        "potential_range": [max(player_overall(target), round(target["potential"] - 18 * error)),
                            min(99, round(target["potential"] + 22 * error))],
        "skills": skill_estimates,
        "fit": role_fit(career, career["club_id"], player_id),
        "note": content.PLAYER_REPORT_NOTES.get(player_id, "No strong tendency is clear yet."),
    }
    career["scouting"][player_id] = report
    return report


def resolve_offer(career: dict[str, Any], player_id: str, fee: int,
                  wage: float) -> dict[str, Any]:
    """Resolve a transparent club offer with a player counter-range if refused."""
    club_id = career["club_id"]
    finance = career["clubs"][club_id]["finance"]
    if player_id not in career["market"]:
        return {"accepted": False, "reason": "That player has already left the market."}
    player = career["players"][player_id]
    wage = round(float(wage), 1)
    if len(career["clubs"][club_id]["roster"]) >= 24:
        return {"accepted": False, "reason": "The senior squad is full; make room first."}
    if fee < 0 or wage < 0:
        return {"accepted": False, "reason": "An offer cannot be negative."}
    if fee > finance["transfer_budget"] or fee > finance["cash"]:
        return {"accepted": False, "reason": "The fee is beyond the club's available funds."}
    if finance["weekly_wages"] + wage > finance["wage_budget"]:
        return {"accepted": False, "reason": "That wage would break the weekly wage ceiling."}

    personality = player["personality"]
    fee_floor = round(player["value"] * (.84 + (stable_number(player_id) % 12) / 100))
    wage_floor = round(player["wage_demand"] * (1.06 if personality == "ambitious" else .98), 1)
    if fee < fee_floor or wage < wage_floor:
        return {"accepted": False,
                "counter_fee": max(fee_floor, fee),
                "counter_wage": max(wage_floor, wage),
                "reason": (f"The agent counters at £{max(fee_floor, fee)}k and "
                           f"£{max(wage_floor, wage):.1f}k/week."),
                "gap": {"fee": max(0, fee_floor - fee), "wage": max(0, wage_floor - wage)}}

    finance["transfer_budget"] -= fee
    finance["cash"] -= fee
    previous_club = player.get("club")
    if previous_club and previous_club in career["clubs"]:
        career["clubs"][previous_club]["roster"].remove(player_id)
        career["clubs"][previous_club]["finance"]["weekly_wages"] -= player["wage"]
        career["clubs"][previous_club]["finance"]["cash"] += fee
        finance["weekly_wages"] += wage
    else:
        finance["weekly_wages"] += wage
    player["club"] = club_id
    player["wage"] = wage
    player["contract_years"] = 3
    player["morale"] = int(clamp(player["morale"] + 8, 0, 100))
    player["trust"] = int(clamp(player["trust"] + 7, 0, 100))
    player["injury_until_round"] = min(player["injury_until_round"], career["round"])
    career["clubs"][club_id]["roster"].append(player_id)
    if player_id in career["market"]:
        career["market"].remove(player_id)
    career.setdefault("transfers", []).append({"season": career["season"],
                                               "round": career["round"] + 1,
                                               "player_id": player_id,
                                               "from": previous_club or "Free agent",
                                               "to": club_id, "fee": fee, "wage": wage})
    _news(career, content.NEWS_LINES["signing"].format(
        player=player["name"], club=club_by_id(club_id)["name"],
        fee=fee, wage=f"{wage:.1f}"), "transfer")
    ts.unlock("first-signing", "New Boots", "Brought your first player into the club")
    return {"accepted": True, "player_id": player_id, "fee": fee, "wage": wage}


def sale_offer(career: dict[str, Any], player_id: str) -> dict[str, Any]:
    """List an unwanted player and accept a constrained, explainable offer."""
    club_id = career["club_id"]
    state = career["clubs"][club_id]
    player = career["players"].get(player_id)
    if not player or player["club"] != club_id:
        return {"accepted": False, "reason": "The player is not at your club."}
    if len(state["roster"]) <= 11:
        return {"accepted": False, "reason": "Keep at least eleven registered players."}
    if player_id in state["lineup"]:
        state["lineup"].remove(player_id)
    buyer = next((club["id"] for club in content.CLUBS
                  if club["id"] != club_id
                  and career["clubs"][club["id"]]["finance"]["transfer_budget"] >= player["value"] * .65), None)
    if not buyer:
        return {"accepted": False, "reason": "No club can meet a fair fee this week."}
    bid = max(1, round(player["value"] * .82))
    buyer_finance = career["clubs"][buyer]["finance"]
    if (buyer_finance["cash"] < bid or buyer_finance["weekly_wages"] + player["wage"]
            > buyer_finance["wage_budget"]):
        return {"accepted": False, "reason": "The interested club cannot make room in its budget."}
    state["roster"].remove(player_id)
    state["finance"]["cash"] += bid
    state["finance"]["transfer_budget"] += bid
    state["finance"]["weekly_wages"] -= player["wage"]
    career["clubs"][buyer]["finance"]["cash"] -= bid
    career["clubs"][buyer]["finance"]["transfer_budget"] -= bid
    career["clubs"][buyer]["finance"]["weekly_wages"] += player["wage"]
    player["club"] = buyer
    player["contract_years"] = 3
    career["clubs"][buyer]["roster"].append(player_id)
    transfer = {"season": career["season"], "round": career["round"] + 1,
                "player_id": player_id, "from": club_id, "to": buyer,
                "fee": bid, "wage": player["wage"]}
    career.setdefault("transfers", []).append(transfer)
    _news(career, content.NEWS_LINES["sale"].format(
        club=club_by_id(buyer)["name"], player=player["name"], fee=bid), "transfer")
    return {"accepted": True, "buyer": buyer, "fee": bid}


def _ensure_player_ids(career: dict[str, Any]) -> None:
    for player_id, player in career.get("players", {}).items():
        player.setdefault("id", player_id)
        player.setdefault("familiarity", 50)
        player.setdefault("injury_until_round", -1)
        player.setdefault("potential", player.get("overall", 50))
        player.setdefault("wage", 1.0)
        player.setdefault("wage_demand", round(player["wage"] * 1.2, 1))
        player.setdefault("career_apps", 0)
        player.setdefault("career_goals", 0)
        player.setdefault("career_assists", 0)


def migrate_save(data: dict[str, Any]) -> dict[str, Any]:
    """Keep an empty or older console save safe as the schema gains fields."""
    for key, value in SAVE_DEFAULTS.items():
        data.setdefault(key, copy.deepcopy(value))
    data["version"] = 2
    career = data.get("career")
    if isinstance(career, dict):
        career["version"] = 2
        career.setdefault("season", 1)
        career.setdefault("round", 0)
        career.setdefault("career_week", max(0, (int(career["season"]) - 1)
                                                 * content.SEASON_ROUNDS + int(career["round"])))
        career.setdefault("season_complete", False)
        career.setdefault("news", [])
        career.setdefault("rivalries", {})
        career.setdefault("chemistry", {})
        career.setdefault("scouting", {})
        career.setdefault("played_ids", [])
        career.setdefault("results", [])
        career.setdefault("season_history", [])
        career.setdefault("training_applied_round", -1)
        career.setdefault("live_match", None)
        career.setdefault("manager_name", "You")
        career.setdefault("clubs", {})
        career.setdefault("players", {})
        for player_id, seed in content.PLAYERS.items():
            if seed.get("club") and player_id not in career["players"]:
                career["players"][player_id] = make_player(seed)
        _ensure_player_ids(career)
        for club in content.CLUBS:
            cid = club["id"]
            roster = [pid for pid, player in career["players"].items()
                      if player.get("club") == cid]
            state = career["clubs"].setdefault(cid, {
                "roster": roster, "lineup": [], "division": club["division"],
                "tactics": default_tactics(cid),
                "training": {"focus": "Tactical", "intensity": "normal"},
                "finance": {"cash": int(club["budget"] * 5),
                            "transfer_budget": int(club["budget"]),
                            "wage_budget": 36,
                            "weekly_wages": sum(career["players"][pid]["wage"]
                                                 for pid in roster)},
                "board_confidence": 64, "supporter_mood": 63,
                "attendance": content.CLUB_IDENTITY[cid]["attendance"],
                "expected_place": content.CLUB_IDENTITY[cid]["expectation"],
                "board_patience": content.CLUB_IDENTITY[cid]["patience"],
                "wins": 0,
            })
            state.setdefault("roster", roster)
            state.setdefault("lineup", [])
            state.setdefault("division", club["division"])
            state.setdefault("tactics", default_tactics(cid))
            state.setdefault("training", {"focus": "Tactical", "intensity": "normal"})
            state.setdefault("board_confidence", 64)
            state.setdefault("supporter_mood", 63)
            state.setdefault("attendance", content.CLUB_IDENTITY[cid]["attendance"])
            state.setdefault("expected_place", content.CLUB_IDENTITY[cid]["expectation"])
            state.setdefault("board_patience", content.CLUB_IDENTITY[cid]["patience"])
            state.setdefault("wins", 0)
            if not state["lineup"]:
                state["lineup"] = best_lineup(career, cid, state["tactics"]["in_shape"])
        career.setdefault("table", {})
        for cid, zero in empty_table().items():
            career["table"].setdefault(cid, zero)
        career.setdefault("fixtures", copy.deepcopy(content.DIVISION_FIXTURES))
    return data


def _career_summary(career: dict[str, Any]) -> str:
    if not career:
        return ""
    if career.get("season_complete"):
        place = _table_order(career).index(career["club_id"]) + 1
        return f"S{career['season']} {ordinal(place)} / END"[:15]
    place = _table_order(career).index(career["club_id"]) + 1
    return f"S{career['season']} {ordinal(place)} W{career['round'] + 1:02d}"[:15]


def _persist(save_data: dict[str, Any], career: dict[str, Any] | None) -> None:
    save_data["version"] = 2
    save_data["career"] = career
    save_data["_summary"] = _career_summary(career) if career else ""
    ts.save(save_data)


def _pair(pair: int, bold: bool = False, dim: bool = False) -> int:
    attr = curses.color_pair(pair) if curses.has_colors() else 0
    if bold:
        attr |= curses.A_BOLD
    if dim:
        attr |= curses.A_DIM
    return attr


def _init_colors() -> None:
    try:
        if not curses.has_colors():
            return
        curses.start_color()
        try:
            curses.use_default_colors()
        except curses.error:
            pass
        pairs = (
            (1, curses.COLOR_YELLOW), (2, curses.COLOR_CYAN),
            (3, curses.COLOR_GREEN), (4, curses.COLOR_RED),
            (5, curses.COLOR_MAGENTA), (6, curses.COLOR_WHITE),
        )
        for number, foreground in pairs:
            try:
                curses.init_pair(number, foreground, -1)
            except curses.error:
                continue
    except curses.error:
        pass


def _restore_bezel_bottom_right(_stdscr, screen) -> None:
    """Keep cabinet edges visible after the game's inner window is refreshed."""
    if not getattr(screen, "framed", False) or not sys.stdout.isatty():
        return
    right = screen.ox + screen.cab_w - 1
    bottom = screen.oy + screen.cab_h - 1
    out = []
    for y in range(screen.oy + 3, bottom):
        out.extend((f"\x1b[{y + 1};{screen.ox + 1}H║",
                    f"\x1b[{y + 1};{right + 1}H║"))
    out.append(f"\x1b[{bottom + 1};{right + 1}H╝")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def _money(value: float | int) -> str:
    value = float(value)
    if abs(value) >= 1000:
        return f"£{value / 1000:.1f}m"
    return f"£{value:.0f}k"


def _wage(value: float | int) -> str:
    return f"£{float(value):.1f}k/w"


def _team_result(stats: dict[str, Any], cid: str) -> str:
    return f"{stats[cid]['shots']} shots · {float(stats[cid]['xg']):.2f} xG"


def _page_nav_index(page: str) -> int:
    return SECTION_PAGES.index(page) if page in SECTION_PAGES else 0


def _draw_section_nav(win, safe_width: int, page: str,
                      app: dict[str, Any], career: dict[str, Any] | None) -> None:
    if page not in SECTION_PAGES or not career:
        crumb = PAGE_BREADCRUMBS.get(page)
        if page == "match" and career:
            match = career.get("live_match")
            view = "FULL-TIME REPORT" if match and match.get("finished") else \
                app.get("match_view", "live").upper()
            crumb = f"MATCHDAY / {view}"
        if crumb:
            ui.draw_text(win, 0, 1, crumb, safe_width, _pair(3, bold=True))
        else:
            ui.draw_rule(win, 0, 1, safe_width, "─", _pair(2))
        return

    active = _page_nav_index(page)
    focused = int(clamp(app.get("nav_index", active), 0, MATCH_NAV_INDEX))
    x = 0
    for index, label in enumerate(SECTION_LABELS):
        text = f"{index + 1} {label}"
        selected = index == focused
        if selected:
            text = f"[{text}]"
        elif index == active:
            text = f"›{text}"
        attr = _pair(1 if selected and index == active else
                     2 if selected else 3 if index == active else 6,
                     bold=selected or index == active)
        ui.draw_text(win, x, 1, text, safe_width - x, attr)
        x += len(text)
        if index < len(SECTION_LABELS) - 1:
            ui.draw_text(win, x, 1, "  ", safe_width - x, _pair(6, dim=True))
            x += 2
    match_text = "M MATCH" if focused != MATCH_NAV_INDEX else "[M MATCH]"
    ui.draw_text(win, x, 1, "   ", safe_width - x, _pair(6, dim=True))
    x += 3
    ui.draw_text(win, x, 1, match_text, safe_width - x,
                 _pair(1 if focused == MATCH_NAV_INDEX else 6,
                       bold=focused == MATCH_NAV_INDEX))


def _draw_frame(win, career: dict[str, Any] | None, app: dict[str, Any]) -> ui.Rect:
    win.erase()
    height, width = win.getmaxyx()
    # Leave the subwindow's last column unused: ncurses can keep a deferred
    # wrap there, and a subsequent flush/replay may carry it into the bezel.
    safe_width = max(1, width - 1)
    if career:
        club = club_by_id(career["club_id"])
        state = career["clubs"][career["club_id"]]
        when = (f"S{career['season']} END" if career["season_complete"]
                else f"S{career['season']} · W{career['round'] + 1:02d}/{content.SEASON_ROUNDS:02d}")
        division = division_name(division_id(career))
        confidence = state["board_confidence"]
        funds = _money(state["finance"]["transfer_budget"])
        headers = (
            f"EKSE SLAAN BALL · {club['name']} · {division} · {when} · BOARD {confidence} · {funds}",
            f"EKSE SLAAN BALL · {club['name']} · {when} · BOARD {confidence}",
            f"EKSE SLAAN BALL · {club['name']} · {when} · BD {confidence}",
        )
        header = next((candidate for candidate in headers if len(candidate) <= safe_width),
                      headers[-1])
    else:
        header = "EKSE SLAAN BALL  /  SABLE COAST FOOTBALL PYRAMID"
    ui.draw_text(win, 0, 0, header, safe_width, _pair(1, bold=True))
    page = app.get("page", "home")
    _draw_section_nav(win, safe_width, page, app, career)
    body = ui.Rect(0, 2, safe_width, max(1, height - 4))
    message_y = max(2, height - 2)
    footer_y = max(2, height - 1)
    msg = app.get("message", "")
    if msg:
        ui.draw_text(win, 0, message_y, f"» {msg}", safe_width, _pair(1))
    footer = "←/→ browse · Enter open · 1–7 jump · M matchday · ? help · Q quit"
    if page == "team_talk":
        footer = "↑/↓ choose message  ·  Enter deliver & kick off  ·  Esc pause"
    elif page == "match_subs":
        footer = "Tab change side  ·  ↑/↓ select player  ·  Enter confirm pair  ·  Esc cancel"
    elif page == "match":
        match = career.get("live_match") if career else None
        if match and match.get("finished"):
            footer = "Tab view  ·  ↑/↓ Events  ·  Enter settle  ·  Esc report  ·  6 Table"
        else:
            footer = "Enter +15' · Tab views · ↑/↓ log · 1–3 tactics · 4 subs · Q sim · Esc"
    if page == "career_select":
        footer = "Up/Down choose club  Enter begin career  Q back"
    elif page == "help":
        footer = "1–7 jump · Tab next page · Esc return · Q quit"
    elif page == "offer":
        footer = "←/→ fee · ↑/↓ wage · C counter · Enter offer · Esc cancel"
    ui.draw_text(win, 0, footer_y, footer, safe_width, _pair(2, bold=True))
    return body


def _draw_hint(win, body: ui.Rect, text: str) -> None:
    if body.height > 0:
        ui.draw_text(win, 0, body.bottom - 1, text, body.width, _pair(2, dim=True))


def _draw_panel_heading(win, rect: ui.Rect, title: str) -> ui.Rect:
    if win.getmaxyx()[1] < 88:
        ui.draw_text(win, rect.x, rect.y, title.upper(), rect.width,
                     _pair(1, bold=True))
        if rect.height > 1:
            ui.draw_rule(win, rect.x, rect.y + 1, rect.width, "─", _pair(2))
        return ui.Rect(rect.x, rect.y + min(2, rect.height), rect.width,
                       max(0, rect.height - min(2, rect.height)))
    ui.draw_panel(win, rect, title, _pair(2), _pair(1, bold=True))
    return rect.inset(1)


def _season_rank(career: dict[str, Any], club_id: str) -> int:
    return _table_order(career).index(club_id) + 1


def _draw_home(win, body: ui.Rect, career: dict[str, Any], app: dict[str, Any]) -> None:
    left, right = ui.split_horizontal(body, .58, 1)
    if left.width < 31:
        left, right = ui.split_horizontal(body, .5, 1)
    club = club_by_id(career["club_id"])
    state = career["clubs"][career["club_id"]]
    y = body.y
    if career["season_complete"]:
        ui.draw_text(win, left.x, y, f"SEASON {career['season']} REVIEW", left.width,
                     _pair(1, bold=True))
        place = _season_rank(career, career["club_id"])
        champion = club_by_id(_table_order(career)[0])["name"]
        ui.draw_text(win, left.x, y + 1,
                     f"{division_name(division_id(career))}: {ordinal(place)} · {champion} win.",
                     left.width)
        ui.draw_text(win, left.x, y + 3, f"Record: {career['table'][career['club_id']]['won']}W "
                     f"{career['table'][career['club_id']]['drawn']}D "
                     f"{career['table'][career['club_id']]['lost']}L  "
                     f"GF {career['table'][career['club_id']]['gf']}  "
                     f"GA {career['table'][career['club_id']]['ga']}", left.width)
        ui.draw_text(win, left.x, y + 5, "Press Enter to begin the next season.", left.width,
                     _pair(3, bold=True))
        movement = career["season_history"][-1].get("movement", {})
        if career["club_id"] in movement.get("promoted", []):
            ui.draw_text(win, left.x, y + 7, "PROMOTED · next season in Sable Coast League",
                         left.width, _pair(3, bold=True))
        elif career["club_id"] in movement.get("relegated", []):
            ui.draw_text(win, left.x, y + 7, "RELEGATED · next season in Tideway Championship",
                         left.width, _pair(4, bold=True))
    else:
        fixture = current_fixture(career)
        opponent_id = next(cid for cid in fixture if cid != career["club_id"]) if fixture else ""
        if career.get("live_match"):
            live = career["live_match"]
            ui.draw_text(win, left.x, y, "MATCH IN PROGRESS", left.width, _pair(1, bold=True))
            ui.draw_text(win, left.x, y + 1,
                         f"{club_by_id(live['home'])['name']} {live['score'][live['home']]}–"
                         f"{live['score'][live['away']]} {club_by_id(live['away'])['name']}", left.width)
            if live["finished"]:
                ui.draw_text(win, left.x, y + 3, "Full time. M returns to the report.", left.width)
            else:
                ui.draw_text(win, left.x, y + 3,
                             f"{live['minute']}' · period {live['period']}/{content.MATCH_PERIODS}", left.width)
        elif fixture:
            is_home = fixture[0] == career["club_id"]
            ui.draw_text(win, left.x, y, "NEXT MATCH", left.width, _pair(1, bold=True))
            home_name, away_name = club_by_id(fixture[0])["name"], club_by_id(fixture[1])["name"]
            ui.draw_text(win, left.x, y + 1, f"{home_name}  v  {away_name}", left.width,
                         _pair(6, bold=True))
            ui.draw_text(win, left.x, y + 2,
                         f"{'HOME' if is_home else 'AWAY'} · Round {career['round'] + 1} · "
                         f"{club_by_id(opponent_id)['name']}", left.width, _pair(2))
            rivalry = next((row for row in content.RIVALRIES
                            if {row["home"], row["away"]} == set(fixture)), None)
            if rivalry:
                key = "|".join(sorted(fixture))
                record = career["rivalries"].get(key, {"meetings": 0, "last_result": "first meeting"})
                ui.draw_text(win, left.x, y + 4,
                             f"{rivalry['name']} · {record['meetings']} prior meetings", left.width,
                             _pair(5, bold=True))
                ui.draw_text(win, left.x, y + 5, record["last_result"], left.width, _pair(5, dim=True))
            else:
                ui.draw_text(win, left.x, y + 4,
                             f"Scouting note: {content.MANAGERS[opponent_id]['approach']} manager.",
                             left.width)
            tactic = state["tactics"]
            ui.draw_text(win, left.x, y + 7,
                         f"YOUR XI {len(lineup_for(career, career['club_id']))}/11 · "
                         f"{tactic['in_shape']} / {tactic['out_shape']}", left.width)
            ui.draw_text(win, left.x, y + 8,
                         f"Press {tactic['press']} · line {tactic['line']} · "
                         f"{tactic['width']} width · {tactic['build']} build", left.width)
            ui.draw_text(win, left.x, y + 10,
                         f"Training: {state['training']['focus']} / {state['training']['intensity']}",
                         left.width)
            ui.draw_text(win, left.x, y + 12,
                         f"Squad mood {round(sum(career['players'][pid]['morale'] for pid in state['roster']) / len(state['roster']))}"
                         f"  ·  Board confidence {state['board_confidence']}", left.width)
            ui.draw_text(win, left.x, y + 14, "M starts or resumes matchday.", left.width,
                         _pair(3, bold=True))

    inner_right = _draw_panel_heading(win, right, division_name(division_id(career)).upper())
    standings = table_rows(career)
    concise = [[row[0], row[1], row[2], row[7], row[8]] for row in standings]
    managed_name = club_by_id(career["club_id"])["name"]
    managed_row = next((index for index, row in enumerate(standings)
                        if row[1] == managed_name), 0)
    table = ui.TableView(["#", "Club", "P", "GD", "Pts"], concise,
                         selected=managed_row)
    table.draw(win, ui.Rect(inner_right.x, inner_right.y,
                            inner_right.width, min(8, inner_right.height)),
               header_attr=_pair(1, bold=True), selected_attr=_pair(3, bold=True))
    info_y = inner_right.y + min(9, inner_right.height)
    if info_y < body.bottom - 2:
        ui.draw_rule(win, right.x + 1, info_y, max(1, right.width - 2), "·", _pair(2))
        info_y += 1
        finance = state["finance"]
        ui.draw_text(win, inner_right.x, info_y, f"Cash  {_money(finance['cash'])}", inner_right.width)
        ui.draw_text(win, inner_right.x, info_y + 1,
                     f"Wages {_money(finance['weekly_wages'])}/w  /  {_money(finance['wage_budget'])} cap",
                     inner_right.width)
        ui.draw_text(win, inner_right.x, info_y + 2,
                     f"Support {state['supporter_mood']}  ·  "
                     f"Target {ordinal(state['expected_place'])}", inner_right.width)
        news_y = info_y + 4
        if career.get("news") and news_y < body.bottom:
            latest = career["news"][-1]
            ui.draw_text(win, inner_right.x, news_y, "LATEST", inner_right.width, _pair(1, bold=True))
            ui.draw_text(win, inner_right.x, news_y + 1,
                         latest["text"], inner_right.width, _pair(6))
    _draw_hint(win, body, "Pre-kickoff: review the XI, shape and weekly training plan")


def _player_rows(career: dict[str, Any], club_id: str) -> list[dict[str, Any]]:
    players = [career["players"][pid] for pid in career["clubs"][club_id]["roster"]]
    return sorted(players, key=lambda p: (p["position"], -p["overall"], p["name"]))


def _draw_squad(win, body: ui.Rect, career: dict[str, Any], app: dict[str, Any]) -> None:
    club_id = career["club_id"]
    state = career["clubs"][club_id]
    players = _player_rows(career, club_id)
    app["squad_index"] = int(clamp(app.get("squad_index", 0), 0, max(0, len(players) - 1)))
    left, right = ui.split_horizontal(body, .61, 1)
    roster_panel = _draw_panel_heading(win, left, f"SQUAD · {len(players)}")
    dossier = _draw_panel_heading(win, right, "PLAYER")
    rows = []
    for index, player in enumerate(players, start=1):
        starter = "XI" if player["id"] in state["lineup"] else ""
        injury = "!" if not is_available(career, player) else ""
        rows.append([index, player["name"], player["position"], player["overall"],
                     player["fitness"], player["morale"], starter + injury])
    table = ui.TableView(["#", "Player", "P", "OVR", "FIT", "MOR", ""],
                         rows, selected=app["squad_index"],
                         widths=[2, 17, 3, 4, 4, 4, 2])
    table_rect = ui.Rect(roster_panel.x, roster_panel.y,
                         roster_panel.width, max(1, roster_panel.height - 1))
    table.draw(win, table_rect, selected_attr=_pair(3, bold=True),
               header_attr=_pair(1, bold=True))
    if players:
        app["squad_index"] = table.selected
        selected = players[app["squad_index"]]
        app["selected_player_id"] = selected["id"]
        detail_lines = [
            selected["name"],
            f"{POSITION_NAMES[selected['position']]} · age {selected['age']}",
            f"Overall {selected['overall']} · potential {selected['potential']}",
            f"{selected['personality'].title()} · form {selected['form']:.1f}",
            f"Morale {selected['morale']} · trust {selected['trust']}",
            f"Fitness {selected['fitness']} · sharpness {selected['sharpness']}",
            f"{_wage(selected['wage'])} · {selected['contract_years']}y deal",
            f"{selected['career_apps']} apps · {selected['career_goals']} goals",
        ]
        y = dossier.y
        for line in detail_lines:
            if y >= body.bottom - 2:
                break
            ui.draw_text(win, dossier.x, y, line, dossier.width,
                         _pair(1, bold=line == selected["name"]))
            y += 1
        if selected.get("injury"):
            ui.draw_text(win, dossier.x, y + 1,
                         f"MED: {selected['injury']}", dossier.width, _pair(4, bold=True))
        elif selected["id"] in content.PLAYER_REPORT_NOTES:
            ui.draw_text(win, dossier.x, min(body.bottom - 2, y + 1),
                         content.PLAYER_REPORT_NOTES[selected["id"]], dossier.width, _pair(2))
    _draw_hint(win, body, "↑/↓ browse · X toggle starter · V list for sale · ! injured")


def _draw_tactics(win, body: ui.Rect, career: dict[str, Any], app: dict[str, Any]) -> None:
    state = career["clubs"][career["club_id"]]
    tactic = state["tactics"]
    left, right = ui.split_horizontal(body, .55, 1)
    plan = _draw_panel_heading(win, left, "MATCH PLAN")
    zones = _draw_panel_heading(win, right, "PITCH OCCUPATION")
    values = [
        ("I", "In possession", tactic["in_shape"]),
        ("O", "Out of possession", tactic["out_shape"]),
        ("P", "Press", tactic["press"]),
        ("L", "Defensive line", tactic["line"]),
        ("W", "Width", tactic["width"]),
        ("B", "Build-up", tactic["build"]),
        ("T", "Tempo", tactic["tempo"]),
    ]
    y = plan.y
    for key, label, value in values:
        if y >= body.bottom - 2:
            break
        ui.draw_text(win, plan.x, y, f"[{key}] {label:<20} {value.upper()}",
                     plan.width, _pair(1 if key in ("I", "O") else 2,
                                      bold=key == app.get("tactic_focus", "P")))
        y += 1
    selected_key = app.get("tactic_focus", "P")
    selected_value = tactic.get({"I": "in_shape", "O": "out_shape", "P": "press",
                                 "L": "line", "W": "width", "B": "build", "T": "tempo"}.get(selected_key, "press"), "mid")
    if y < body.bottom - 2:
        if selected_key in ("I", "O"):
            tradeoff = content.FORMATION_NOTES.get(selected_value,
                                                   "Choose a shape and read its trade-off.")
        else:
            tradeoff = content.INSTRUCTIONS.get(
                {"P": "press", "L": "line", "W": "width", "B": "build",
                 "T": "tempo"}.get(selected_key, "press"), {}).get(
                     selected_value, "Choose a plan and read its trade-off.")
        ui.draw_text(win, plan.x, y + 1,
                     tradeoff, plan.width, _pair(6))
    ui.draw_text(win, zones.x, zones.y, f"IP {tactic['in_shape']}   /   OOP {tactic['out_shape']}",
                 zones.width, _pair(1, bold=True))
    shape_lines = content.FORMATION_ART.get(tactic["in_shape"], content.FORMATION_ART["4-3-3"])
    y = zones.y + 2
    for line in shape_lines:
        ui.draw_text(win, zones.x, y, line, zones.width, _pair(3, bold=True))
        y += 2
    y += 1
    tactic_order = [
        ("press", tactic["press"]), ("line", tactic["line"]),
        ("width", tactic["width"]), ("build", tactic["build"]),
        ("tempo", tactic["tempo"]),
    ]
    for key, value in tactic_order:
        desc = content.INSTRUCTIONS[key][value]
        if y >= body.bottom - 2:
            break
        ui.draw_text(win, zones.x, y, f"{key.title()}: {desc}", zones.width,
                     _pair(6))
        y += 1
    _draw_hint(win, body, "I/O/P/L/W/B/T cycle · -/+ adjust · ←/→ menu")


def _draw_training(win, body: ui.Rect, career: dict[str, Any], app: dict[str, Any]) -> None:
    state = career["clubs"][career["club_id"]]
    left, right = ui.split_horizontal(body, .52, 1)
    plans = _draw_panel_heading(win, left, "WEEKLY PLAN")
    impact = _draw_panel_heading(win, right, "WHY IT MATTERS")
    focuses = list(content.TRAINING_PLANS)
    default_index = focuses.index(state["training"]["focus"])
    app["training_index"] = int(clamp(app.get("training_index", default_index), 0, len(focuses) - 1))
    for index, focus in enumerate(focuses):
        y = plans.y + index
        marker = "›" if index == app["training_index"] else " "
        chosen = "✓" if state["training"]["focus"] == focus else " "
        ui.draw_text(win, plans.x, y, f"{marker} {focus:<15} {chosen}", plans.width,
                     _pair(3 if state["training"]["focus"] == focus else 2,
                           bold=index == app["training_index"]))
        ui.draw_text(win, impact.x, y, content.TRAINING_PLANS[focus], impact.width)
    if plans.y + 7 < body.bottom - 1:
        focus = state["training"]["focus"]
        intensity = state["training"]["intensity"]
        average = sum(career["players"][pid]["fitness"]
                      for pid in state["roster"]) / max(1, len(state["roster"]))
        ui.draw_rule(win, plans.x, plans.y + 6, plans.width, "·", _pair(2))
        ui.draw_text(win, plans.x, plans.y + 7, f"Focus: {focus}", plans.width, _pair(1, bold=True))
        ui.draw_text(win, plans.x, plans.y + 8, f"Intensity: {intensity.title()} [I cycles]", plans.width)
        ui.draw_text(win, plans.x, plans.y + 9, f"Squad fitness average: {average:.0f}", plans.width)
        preview = {"low": "small gains / safer recovery",
                   "normal": "steady growth / manageable load",
                   "high": "larger gains / fatigue and injury exposure"}[intensity]
        ui.draw_text(win, impact.x, plans.y + 8, preview, impact.width, _pair(1))
        ui.draw_text(win, impact.x, plans.y + 10,
                     "The plan applies once when you start this week's matchday.",
                     impact.width, _pair(6))
    _draw_hint(win, body, "↑/↓ focus · Enter set · I intensity · applied at matchday")


def _draw_recruitment(win, body: ui.Rect, career: dict[str, Any], app: dict[str, Any]) -> None:
    if app.get("offer"):
        _draw_offer(win, body, career, app)
        return
    club_id = career["club_id"]
    market = [pid for pid in career["market"] if pid in career["players"]]
    if not market:
        ui.draw_text(win, body.x, body.y, "The market is quiet. Check again after the next round.",
                     body.width, _pair(1, bold=True))
        _draw_hint(win, body, "Players added here by the world become available to scout and sign")
        return
    app["market_index"] = int(clamp(app.get("market_index", 0), 0, len(market) - 1))
    left, right = ui.split_horizontal(body, .57, 1)
    shortlist = _draw_panel_heading(win, left, f"SCOUTING DESK · {len(market)}")
    dossier = _draw_panel_heading(win, right, "REPORT")
    rows = []
    for index, pid in enumerate(market, start=1):
        player = career["players"][pid]
        report = career["scouting"].get(pid)
        confidence = report.get("confidence", "?") if report else "?"
        rows.append([index, player["name"], player["position"], player["age"], confidence])
    list_view = ui.TableView(["#", "Target", "P", "Age", "Info"], rows,
                             selected=app["market_index"], widths=[2, 18, 3, 3, 5])
    list_view.draw(win, ui.Rect(shortlist.x, shortlist.y,
                                shortlist.width, max(1, shortlist.height - 1)),
                   selected_attr=_pair(3, bold=True), header_attr=_pair(1, bold=True))
    app["market_index"] = list_view.selected
    pid = market[app["market_index"]]
    app["selected_market_id"] = pid
    target = career["players"][pid]
    report = career["scouting"].get(pid)
    y = dossier.y
    lines = [
        (target["name"], 1),
        (f"{POSITION_NAMES[target['position']]} · age {target['age']} · OVR {target['overall']}", 0),
        (f"Potential {target['potential']} is not fully known.", 0),
        (f"Wage demand around {_wage(target['wage_demand'])}", 0),
        (f"Club fit {role_fit(career, club_id, pid)}/100", 2),
    ]
    if report:
        lines.extend([
            (f"SCOUT CONFIDENCE {report['confidence']}", 5),
            (f"Fee estimate {_money(report['fee_range'][0])}–{_money(report['fee_range'][1])}", 0),
            (f"Wage range {_wage(report['wage_range'][0])}–{_wage(report['wage_range'][1])}", 0),
            (f"Potential range {report['potential_range'][0]}–{report['potential_range'][1]}", 0),
            (report["note"], 2),
        ])
    else:
        lines.extend([
            (f"Estimated value {_money(target['value'])} · scout for a report", 0),
            ("The estimate is not an offer guarantee.", 6),
        ])
    finance = career["clubs"][club_id]["finance"]
    lines.extend([
        (f"Fee room {_money(finance['transfer_budget'])}", 1),
        (f"Wage room {_wage(max(0, finance['wage_budget'] - finance['weekly_wages']))}", 1),
    ])
    for text, pair in lines:
        if y >= body.bottom - 2:
            break
        ui.draw_text(win, dossier.x, y, text, dossier.width, _pair(pair, bold=pair == 1))
        y += 1
    _draw_hint(win, body, "↑/↓ target · S scout · O negotiate · V to Squad to list a player for sale")


def _draw_offer(win, body: ui.Rect, career: dict[str, Any], app: dict[str, Any]) -> None:
    offer = app["offer"]
    player = career["players"][offer["player_id"]]
    report = career["scouting"].get(player["id"], {})
    ui.draw_text(win, body.x, body.y, f"CONTRACT TABLE · {player['name']}", body.width,
                 _pair(1, bold=True))
    ui.draw_text(win, body.x, body.y + 2,
                 f"Scout range: {_money(report.get('fee_range', [player['value'], player['value']])[0])}–"
                 f"{_money(report.get('fee_range', [player['value'], player['value']])[-1])} fee; "
                 f"{_wage(report.get('wage_range', [player['wage_demand'], player['wage_demand']])[0])}–"
                 f"{_wage(report.get('wage_range', [player['wage_demand'], player['wage_demand']])[-1])} wage.",
                 body.width)
    ui.draw_text(win, body.x, body.y + 4,
                 f"[←/→] Fee: {_money(offer['fee'])}   [↑/↓] Wage: {_wage(offer['wage'])}",
                 body.width, _pair(3, bold=True))
    ui.draw_text(win, body.x, body.y + 6,
                 f"Budget: {_money(career['clubs'][career['club_id']]['finance']['transfer_budget'])}  ·  "
                 f"weekly wage ceiling {_wage(career['clubs'][career['club_id']]['finance']['wage_budget'])}",
                 body.width)
    if offer.get("counter"):
        ui.draw_text(win, body.x, body.y + 8, offer["counter"]["reason"], body.width, _pair(5, bold=True))
        ui.draw_text(win, body.x, body.y + 9, "C accepts the counter; or adjust either term again.",
                     body.width, _pair(6))
    if offer.get("message"):
        ui.draw_text(win, body.x, body.y + 11, offer["message"], body.width,
                     _pair(3 if offer.get("accepted") else 4, bold=True))


def _draw_table(win, body: ui.Rect, career: dict[str, Any], app: dict[str, Any]) -> None:
    table_rows_full = table_rows(career)
    ui.draw_text(win, body.x, body.y, division_name(division_id(career)).upper(),
                 body.width, _pair(1, bold=True))
    table_height = min(max(4, body.height - 7), len(table_rows_full) + 1)
    table = ui.TableView(["#", "Club", "P", "W", "D", "L", "GF:GA", "GD", "Pts"],
                         table_rows_full, selected=app.get("table_index", 0),
                         widths=[2, 23, 3, 3, 3, 3, 6, 4, 4])
    table.draw(win, ui.Rect(body.x, body.y + 1, body.width, table_height),
               selected_attr=_pair(3, bold=True), header_attr=_pair(1, bold=True))
    y = body.y + table_height + 2
    ui.draw_rule(win, body.x, y, body.width, "─", _pair(2))
    y += 1
    heading = "RECENT RESULTS" if career["season_complete"] else f"ROUND {career['round'] + 1} FIXTURES"
    ui.draw_text(win, body.x, y, heading, body.width, _pair(1, bold=True))
    y += 1
    current_division = division_id(career)
    fixtures = [r for r in career["results"]
                if r["season"] == career["season"]
                and r.get("division", current_division) == current_division]
    fixtures = fixtures[-min(4, max(1, body.bottom - y - 1)):]
    if not career["season_complete"]:
        fixtures = []
        for home, away in fixtures_for(career)[career["round"]]:
            home_result = next((r for r in career["results"] if r["id"] ==
                                f"S{career['season']}-W{career['round'] + 1:02d}-{home}-{away}"), None)
            if home_result:
                fixtures.append(home_result)
            else:
                fixtures.append({"home": home, "away": away,
                                 "home_goals": None, "away_goals": None})
    for item in fixtures:
        if y >= body.bottom - 1:
            break
        score = ("v" if item["home_goals"] is None
                 else f"{item['home_goals']}–{item['away_goals']}")
        text = f"{club_by_id(item['home'])['name']} {score} {club_by_id(item['away'])['name']}"
        ui.draw_text(win, body.x, y, text, body.width,
                     _pair(3 if item.get("home") == career["club_id"] or item.get("away") == career["club_id"] else 6))
        y += 1
    _draw_hint(win, body, "Top two in Tideway rise; bottom two in Sable Coast drop after the season")


def _draw_history(win, body: ui.Rect, career: dict[str, Any]) -> None:
    left, right = ui.split_horizontal(body, .57, 1)
    results_panel = _draw_panel_heading(win, left, "CAREER RESULTS")
    news_panel = _draw_panel_heading(win, right, "WORLD NEWS")
    result_rows = career["results"][-max(1, results_panel.height - 1):]
    y = results_panel.y
    for record in reversed(result_rows):
        if y >= body.bottom - 1:
            break
        text = (f"S{record['season']} W{record['round']:02d}  "
                f"{club_by_id(record['home'])['id']} {record['home_goals']}–"
                f"{record['away_goals']} {club_by_id(record['away'])['id']}")
        ui.draw_text(win, results_panel.x, y, text, results_panel.width)
        y += 1
    news = career.get("news", [])[-max(1, news_panel.height):]
    y = news_panel.y
    for entry in reversed(news):
        if y >= body.bottom - 1:
            break
        ui.draw_text(win, news_panel.x, y, entry["text"], news_panel.width,
                     _pair(1 if entry.get("kind") == "result" else 6))
        y += 1
    _draw_hint(win, body, "The ledger is generated from match, training, market and season events")


def _draw_help(win, body: ui.Rect) -> None:
    lines = [
        ("THE MANAGER'S DESK", 1),
        ("←/→ browse the section bar; Enter opens the focused page.", 0),
        ("Brackets show keyboard focus; › marks the page you are on.", 0),
        ("1-7 jump to Home, Squad, Plan, Training, Market, Table and Logs.", 0),
        ("M starts or resumes matchday; ? opens this guide.", 0),
        ("Before kickoff, choose and deliver a team talk.", 0),
        ("Match: Tab views; Event arrows browse; Enter +15'; 1-3 tactics; 4 Changes.", 0),
        ("Changes: Tab switches lists; arrows choose who comes off/on; Enter confirms.", 0),
        ("Squad: arrows select; X toggles a starter; V accepts a fair outgoing offer.", 0),
        ("Plan: I/O/P/L/W/B/T cycle settings; -/+ adjusts the focused one.", 0),
        ("Training: arrows choose focus, Enter sets it, I cycles intensity.", 0),
        ("Market: scout for uncertainty ranges; negotiate fee and weekly wage separately.", 0),
        ("Tactical keys alter the actions the match engine can produce, not a hidden win bonus.", 0),
        ("Talk responses change morale slightly; Live, Events and Stats read the same match ledger.", 0),
        ("Your career autosaves after each meaningful decision and match period.", 0),
        ("A report is a forecast, not a promise. The same plan can still lose a close match.", 0),
    ]
    for offset, (text, pair) in enumerate(lines):
        y = body.y + offset
        if y >= body.bottom - 1:
            break
        ui.draw_text(win, body.x, y, text, body.width, _pair(pair, bold=pair == 1))
    _draw_hint(win, body, "Esc returns to the last page · full controls are in manual.md")


def _wrap_words(text: str, width: int) -> list[str]:
    if width <= 0:
        return []
    lines: list[str] = []
    current = ""
    for word in str(text).split():
        if len(word) > width:
            if current:
                lines.append(current)
                current = ""
            lines.extend(word[offset:offset + width]
                         for offset in range(0, len(word), width))
        elif not current:
            current = word
        elif len(current) + len(word) + 1 <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_wrapped(win, x: int, y: int, width: int, bottom: int,
                  text: str, attr: int = 0) -> int:
    for line in _wrap_words(text, width):
        if y >= bottom:
            break
        ui.draw_text(win, x, y, line, width, attr)
        y += 1
    return y


def _draw_team_talk(win, body: ui.Rect, career: dict[str, Any],
                    app: dict[str, Any]) -> None:
    match = career["live_match"]
    talks = content.TEAM_TALKS
    index = int(clamp(app.get("talk_index", 0), 0, len(talks) - 1))
    talk = talks[index]
    home, away = match["home"], match["away"]
    title = (f"{club_by_id(home)['name']}  v  {club_by_id(away)['name']}  ·  "
             f"S{career['season']} W{career['round'] + 1:02d}")
    ui.draw_text(win, body.x, body.y, "BEFORE KICKOFF  /  TEAM TALK", body.width,
                 _pair(1, bold=True))
    if body.height > 1:
        ui.draw_text(win, body.x, body.y + 1, title, body.width, _pair(2))
    if body.height > 2:
        ui.draw_rule(win, body.x, body.y + 2, body.width, "─", _pair(2))
    left, right = ui.split_horizontal(
        ui.Rect(body.x, body.y + 3, body.width, max(1, body.height - 5)), .56, 1)
    message = _draw_panel_heading(win, left, "YOUR WORDS")
    room = _draw_panel_heading(win, right, "THE ROOM")
    y = message.y
    for option_index, option in enumerate(talks):
        if y >= body.bottom - 3:
            break
        marker = "›" if option_index == index else " "
        ui.draw_text(win, message.x, y, f"{marker} {option['label']}", message.width,
                     _pair(3 if option_index == index else 6,
                           bold=option_index == index))
        y += 1
    y += 1
    _draw_wrapped(win, message.x, y, message.width, body.bottom - 2,
                  f"“{talk['speech']}”", _pair(1))
    preview = _team_talk_preview(career, match, talk["id"])
    counts = {kind: [
        (career["players"][row["player_id"]]["name"].split()[-1]
         if room.width < 35 else career["players"][row["player_id"]]["name"])
        for row in preview
                     if row["reception"] == kind]
              for kind in ("lifted", "steady", "unsettled")}
    y = room.y
    for kind, label, pair in (("lifted", "LIFTED", 3),
                              ("steady", "STEADY", 2),
                              ("unsettled", "UNSETTLED", 5)):
        names = counts[kind]
        if not names:
            continue
        if y >= body.bottom - 2:
            break
        ui.draw_text(win, room.x, y, f"{label}  {len(names)}", room.width,
                     _pair(pair, bold=True))
        y = _draw_wrapped(win, room.x, y + 1, room.width, body.bottom - 2,
                          ", ".join(names), _pair(6))


def _draw_match_tabs(win, body: ui.Rect, selected: str) -> None:
    x = body.x
    y = body.y
    for view, label in (("live", "LIVE"), ("events", "EVENTS"), ("stats", "STATS")):
        text = f"[{label}]" if view == selected else f" {label} "
        if x + len(text) <= body.right:
            ui.draw_text(win, x, y, text, len(text),
                         _pair(3 if view == selected else 6, bold=view == selected))
        x += len(text) + 1


def _draw_match_live(win, area: ui.Rect, career: dict[str, Any],
                     match: dict[str, Any]) -> None:
    club_id = career["club_id"]
    left, right = ui.split_horizontal(area, .40, 1)
    ui.draw_text(win, left.x, left.y, "MATCH PULSE", left.width, _pair(1, bold=True))
    tactic = match["tactics"][club_id]
    field_players = [career["players"][pid] for pid in match["lineups"][club_id]
                     if career["players"][pid]["position"] != "GK"]
    tired = min(field_players,
                key=lambda player: float(match["load"].get(
                    player["id"], player["fitness"])), default=None)
    load = int(match["load"].get(tired["id"], tired["fitness"])) if tired else 0
    pulse = [
        f"Changes {match['substitutions'][club_id]}/5",
        f"Lowest load · {tired['name']} {load}" if tired else "No load recorded",
        f"IP {tactic['in_shape']} / OOP {tactic['out_shape']}",
        f"{tactic['press']} press · {tactic['line']} line",
        f"{tactic['width']} width · {tactic['build']} build",
    ]
    for offset, text in enumerate(pulse, start=1):
        if left.y + offset >= left.bottom:
            break
        ui.draw_text(win, left.x, left.y + offset, text, left.width,
                     _pair(5 if offset == 2 and load < 65 else 3 if offset == 1 else 6))

    ui.draw_text(win, right.x, right.y, "LATEST MOMENT", right.width,
                 _pair(1, bold=True))
    events = [event for event in match["events"]
              if event.get("kind") not in ("kickoff", "team_talk")]
    event = events[-1] if events else None
    if event is None:
        _draw_wrapped(win, right.x, right.y + 2, right.width,
                      right.bottom, "No on-pitch event yet. Enter begins the first 15-minute window.",
                      _pair(6))
    else:
        club = event.get("club_id")
        club_tag = club if club else "MATCH"
        label = f"{int(event.get('minute', 0)):02d}'  {str(event.get('kind', 'event')).upper()}  {club_tag}"
        ui.draw_text(win, right.x, right.y + 1, label, right.width, _pair(3, bold=True))
        y = _draw_wrapped(win, right.x, right.y + 2, right.width,
                          right.bottom, event.get("text", ""), _pair(1)) + 1
        why = event.get("tactical_reason", "")
        if why and y < right.bottom:
            ui.draw_text(win, right.x, y, "WHY", right.width, _pair(2, bold=True))
            _draw_wrapped(win, right.x, y + 1, right.width, right.bottom,
                          why, _pair(6))


def _draw_match_events(win, area: ui.Rect, match: dict[str, Any],
                       event_index: int = 0) -> None:
    events = list(reversed(match["events"]))
    if not events:
        ui.draw_text(win, area.x, area.y, "No recorded events yet.", area.width, _pair(6))
        return

    index = int(clamp(event_index, 0, len(events) - 1))
    left, right = ui.split_horizontal(area, .54, 1)
    ui.draw_text(win, left.x, left.y, f"CHRONOLOGY · {len(events)}", left.width,
                 _pair(1, bold=True))
    visible_rows = max(1, left.height - 1)
    start = min(index, max(0, len(events) - visible_rows))
    for row, event_offset in enumerate(range(start, min(len(events), start + visible_rows)),
                                       start=1):
        event = events[event_offset]
        kind = str(event.get("kind", "event")).replace("_", " ").upper()
        club = event.get("club_id") or "MATCH"
        minute = int(event.get("minute", 0))
        marker = "›" if event_offset == index else " "
        attr = (_pair(3 if event.get("kind") == "goal" else 5
                      if event.get("kind") == "team_talk" else 2,
                      bold=event_offset == index))
        ui.draw_text(win, left.x, left.y + row,
                     f"{marker} {minute:02d}' {kind} {club}", left.width, attr)

    selected = events[index]
    kind = str(selected.get("kind", "event")).replace("_", " ").upper()
    club = selected.get("club_id") or "MATCH"
    minute = int(selected.get("minute", 0))
    ui.draw_text(win, right.x, right.y, f"{minute:02d}' {kind} · {club}",
                 right.width, _pair(3 if selected.get("kind") == "goal" else 1,
                                    bold=True))
    y = _draw_wrapped(win, right.x, right.y + 2, right.width, right.bottom,
                      selected.get("text", ""), _pair(6))
    reason = selected.get("tactical_reason", "")
    if reason and y < right.bottom:
        ui.draw_text(win, right.x, y, "WHY", right.width, _pair(2, bold=True))
        _draw_wrapped(win, right.x, y + 1, right.width, right.bottom,
                      reason, _pair(6))


def _draw_match_stats(win, area: ui.Rect, career: dict[str, Any],
                      match: dict[str, Any]) -> None:
    home, away = match["home"], match["away"]
    left_width = max(17, min(area.width - 18, int(area.width * .48)))
    ui.draw_text(win, area.x, area.y, "MATCH DATA", left_width, _pair(1, bold=True))
    ui.draw_text(win, area.x + left_width, area.y, home, 7, _pair(3, bold=True))
    ui.draw_text(win, area.x + left_width + 8, area.y, away, 7, _pair(3, bold=True))
    rows = (
        ("Shots (on target)", lambda cid: f"{match['stats'][cid]['shots']} ({match['stats'][cid]['on_target']})"),
        ("Expected goals", lambda cid: f"{float(match['stats'][cid]['xg']):.2f}"),
        ("Corners", lambda cid: str(match["stats"][cid]["corners"])),
        ("Passes complete", lambda cid: str(match["stats"][cid]["passes_completed"])),
        ("High regains", lambda cid: str(match["stats"][cid]["high_regains"])),
        ("Through balls", lambda cid: str(match["stats"][cid]["through_balls"])),
        ("Saves", lambda cid: str(match["stats"][cid]["saves"])),
        ("Possession share", lambda cid: "—"),
    )
    total_possessions = (int(match["stats"][home]["possessions"])
                         + int(match["stats"][away]["possessions"]))
    for offset, (label, value) in enumerate(rows, start=1):
        y = area.y + offset
        if y >= area.bottom:
            return
        if label == "Possession share":
            values = [int(match["stats"][cid]["possessions"]) for cid in (home, away)]
            display = [f"{round(value / total_possessions * 100)}%" if total_possessions else "0%"
                       for value in values]
        else:
            display = [value(cid) for cid in (home, away)]
        ui.draw_text(win, area.x, y, label, left_width, _pair(6))
        ui.draw_text(win, area.x + left_width, y, display[0], 7, _pair(1))
        ui.draw_text(win, area.x + left_width + 8, y, display[1], 7, _pair(1))

    y = area.y + len(rows) + 2
    if y < area.bottom:
        ui.draw_text(win, area.x, y, "PLAYER IMPACT", area.width, _pair(1, bold=True))
        y += 1
    for cid in (home, away):
        if y >= area.bottom:
            break
        contributions = []
        for player_id, stats in match["player_stats"].items():
            player = career["players"].get(player_id)
            if not player or player.get("club") != cid:
                continue
            impact = (int(stats.get("goals", 0)) * 3 + int(stats.get("assists", 0)) * 2
                      + int(stats.get("key_passes", 0)) + int(stats.get("tackles", 0))
                      + int(stats.get("saves", 0)))
            if impact:
                contributions.append((impact, player["name"], stats))
        contributions.sort(reverse=True)
        if contributions:
            _, name, stats = contributions[0]
            ui.draw_text(win, area.x, y,
                         f"{cid}  {name}: {stats.get('goals', 0)} G, "
                         f"{stats.get('assists', 0)} A, {stats.get('key_passes', 0)} KP",
                         area.width, _pair(6))
        else:
            ui.draw_text(win, area.x, y, f"{cid}  No recorded player contribution yet.",
                         area.width, _pair(6))
        y += 1


def _draw_match(win, body: ui.Rect, career: dict[str, Any], app: dict[str, Any]) -> None:
    match = career["live_match"]
    home, away = match["home"], match["away"]
    home_name, away_name = club_by_id(home)["name"], club_by_id(away)["name"]
    ui.draw_text(win, body.x, body.y,
                 f"{home_name}  {match['score'][home]}–{match['score'][away]}  {away_name}",
                 body.width, _pair(1, bold=True))
    if body.height > 1:
        left_stats, right_stats = match["stats"][home], match["stats"][away]
        phase = ("FULL TIME" if match["finished"] else
                 "HALF-TIME" if match["period"] == 3 else f"{match['minute']:>2}'")
        summary = (f"{phase} · {match['period']}/{content.MATCH_PERIODS}  "
                   f"Shots {left_stats['shots']}-{right_stats['shots']}  "
                   f"xG {float(left_stats['xg']):.2f}-{float(right_stats['xg']):.2f}  "
                   f"Corners {left_stats['corners']}-{right_stats['corners']}")
        ui.draw_text(win, body.x, body.y + 1, summary, body.width, _pair(2))
    if body.height > 2:
        ui.draw_rule(win, body.x, body.y + 2, body.width, "─", _pair(2))
    view = app.get("match_view", "live")
    if view not in MATCH_VIEWS:
        view = "live"
    tabs = ui.Rect(body.x, body.y + 3, body.width, 1)
    _draw_match_tabs(win, tabs, view)
    area = ui.Rect(body.x, body.y + 5, body.width, max(1, body.height - 5))
    if view == "events":
        _draw_match_events(win, area, match, app.get("event_index", 0))
    elif view == "stats":
        _draw_match_stats(win, area, career, match)
    else:
        _draw_match_live(win, area, career, match)


def _draw_substitutions(win, body: ui.Rect, career: dict[str, Any],
                        app: dict[str, Any]) -> None:
    match = career["live_match"]
    club_id = career["club_id"]
    lineup = [career["players"][pid] for pid in match["lineups"][club_id]]
    out_index = int(clamp(app.get("sub_out_index", 0), 0, max(0, len(lineup) - 1)))
    outgoing = lineup[out_index] if lineup else None
    bench = _sub_candidates(career, match, club_id, outgoing["id"] if outgoing else None)
    in_index = int(clamp(app.get("sub_in_index", 0), 0, max(0, len(bench) - 1)))
    incoming = bench[in_index] if bench else None
    ui.draw_text(win, body.x, body.y,
                 f"MATCH CHANGES  ·  {match['substitutions'][club_id]}/5 used  ·  {match['minute']}'",
                 body.width, _pair(1, bold=True))
    left, right = ui.split_horizontal(ui.Rect(body.x, body.y + 2, body.width,
                                               max(1, body.height - 4)), .51, 1)
    on_panel = _draw_panel_heading(win, left, "ON PITCH · SELECT WHO COMES OFF")
    bench_panel = _draw_panel_heading(win, right, "AVAILABLE · SELECT WHO COMES ON")
    out_rows = [[">" if app.get("sub_focus", "out") == "out" and index == out_index else "",
                 p["name"], p["position"], int(match["load"].get(p["id"], p["fitness"]))]
                for index, p in enumerate(lineup)]
    incoming_rows = [[">" if app.get("sub_focus", "out") == "in" and index == in_index else "",
                      p["name"], p["position"], p["fitness"]]
                     for index, p in enumerate(bench)]
    if out_rows:
        ui.TableView(["", "Player", "P", "LOAD"], out_rows,
                     selected=out_index, widths=[2, 15, 4, 5]).draw(
                         win, ui.Rect(on_panel.x, on_panel.y, on_panel.width,
                                      max(1, on_panel.height)),
                         selected_attr=_pair(3 if app.get("sub_focus", "out") == "out" else 2,
                                             bold=app.get("sub_focus", "out") == "out"),
                         header_attr=_pair(1, bold=True))
    if incoming_rows:
        ui.TableView(["", "Player", "P", "FIT"], incoming_rows,
                     selected=in_index, widths=[2, 15, 4, 4]).draw(
                         win, ui.Rect(bench_panel.x, bench_panel.y, bench_panel.width,
                                      max(1, bench_panel.height)),
                         selected_attr=_pair(3 if app.get("sub_focus", "out") == "in" else 2,
                                             bold=app.get("sub_focus", "out") == "in"),
                         header_attr=_pair(1, bold=True))
    else:
        reason = ("No eligible reserve goalkeeper." if outgoing and outgoing["position"] == "GK"
                  else "No eligible outfield substitute.")
        ui.draw_text(win, bench_panel.x, bench_panel.y, reason, bench_panel.width,
                     _pair(5, bold=True))
    if outgoing and incoming and body.bottom - 3 >= body.y:
        fit = round(role_skill(incoming, outgoing["position"]))
        role_note = (f"{incoming['position']} cover for {outgoing['position']}"
                     if incoming["position"] != outgoing["position"] else
                     f"like-for-like {outgoing['position']}")
        lines = (f"PAIR  {outgoing['name']} ({outgoing['position']})  →  "
                 f"{incoming['name']} ({incoming['position']})",
                 f"{role_note} · role fit {fit}/100 · fitness {incoming['fitness']}/100")
        for offset, text in enumerate(lines):
            ui.draw_text(win, body.x, body.bottom - 3 + offset, text, body.width,
                         _pair(5 if incoming["position"] != outgoing["position"] else 2,
                               bold=offset == 0))


def _draw_offer_details(career: dict[str, Any], player_id: str) -> tuple[int, float]:
    player = career["players"][player_id]
    report = career["scouting"].get(player_id)
    fee_range = report.get("fee_range", [player["value"], player["value"]]) if report else [player["value"], player["value"]]
    wage_range = report.get("wage_range", [player["wage_demand"], player["wage_demand"]]) if report else [player["wage_demand"], player["wage_demand"]]
    return round(sum(fee_range) / 2), round(sum(wage_range) / 2, 1)


def _begin_offer(career: dict[str, Any], app: dict[str, Any]) -> None:
    player_id = app.get("selected_market_id")
    if not player_id:
        return
    fee, wage = _draw_offer_details(career, player_id)
    app["offer"] = {"player_id": player_id, "fee": fee, "wage": wage}
    app["page"] = "offer"
    app["message"] = "Set the transfer fee and weekly wage separately; the scout range is uncertain."


def _team_talk_preview(career: dict[str, Any], match: dict[str, Any],
                       talk_id: str) -> list[dict[str, Any]]:
    talk = next((item for item in content.TEAM_TALKS if item["id"] == talk_id), None)
    if talk is None:
        raise ValueError(f"unknown team talk: {talk_id}")
    club_id = match["player_club"]
    preview = []
    for player_id in match["lineups"][club_id]:
        player = career["players"][player_id]
        nominal = int(talk["response"].get(player.get("personality", ""), 0))
        after = int(clamp(int(player.get("morale", 60)) + nominal, 0, 100))
        delta = after - int(player.get("morale", 60))
        reception = "lifted" if delta > 0 else "unsettled" if delta < 0 else "steady"
        preview.append({"player_id": player_id, "morale_delta": delta,
                        "reception": reception})
    return preview


def _deliver_team_talk(career: dict[str, Any], match: dict[str, Any],
                       talk_id: str) -> tuple[bool, str]:
    if match.get("team_talk") is not None:
        return False, "The team talk has already been delivered."
    if int(match.get("period", 0)) != 0 or match.get("finished"):
        return False, "The team talk is only available before kickoff."
    talk = next((item for item in content.TEAM_TALKS if item["id"] == talk_id), None)
    if talk is None:
        return False, f"Unknown team talk: {talk_id}"

    responses = _team_talk_preview(career, match, talk_id)
    counts = {"lifted": 0, "steady": 0, "unsettled": 0}
    for response in responses:
        player = career["players"][response["player_id"]]
        player["morale"] = int(clamp(
            int(player.get("morale", 60)) + int(response["morale_delta"]), 0, 100))
        counts[response["reception"]] += 1

    summary = (f"{talk['label']}: {counts['lifted']} lifted, "
               f"{counts['steady']} steady, {counts['unsettled']} unsettled.")
    match["team_talk"] = {"id": talk_id, "club_id": match["player_club"],
                          "minute": 0, "responses": responses, "summary": summary}
    event = {"kind": "team_talk", "club_id": match["player_club"],
             "text": summary, "minute": 0, "period": 0,
             "phase": "pre-match", "action": "team-talk",
             "zone": "pre-match", "tactical_reason": talk["speech"]}
    _add_event(match, event)
    # The recorded order should reflect the tunnel talk, then the opening plan.
    match["events"].insert(0, match["events"].pop())
    return True, summary


def _needs_team_talk(match: dict[str, Any] | None) -> bool:
    return bool(match and int(match.get("period", 0)) == 0
                 and match.get("team_talk") is None and not match.get("finished"))


def _start_matchday(career: dict[str, Any], app: dict[str, Any]) -> None:
    if career["season_complete"]:
        app["message"] = "The season is complete. Press Enter at Home to begin the next one."
        return
    if career.get("live_match"):
        app["page"] = "team_talk" if _needs_team_talk(career["live_match"]) else "match"
        return
    prepare_week(career)
    fixture = current_fixture(career)
    if not fixture:
        app["message"] = "No fixture remains this season."
        return
    home, away = fixture
    career["live_match"] = new_match(career, home, away,
                                     career["round"],
                                     _match_seed(career, career["round"], home, away))
    app["page"] = "team_talk"
    app["talk_index"] = 0
    app["message"] = "Matchday. Set the tone before the opening whistle."


def _cycle_choice(current: str, choices: tuple[str, ...], direction: int = 1) -> str:
    index = choices.index(current) if current in choices else 1
    return choices[(index + direction) % len(choices)]


def _change_tactic(tactic: dict[str, str], key: str, direction: int = 1) -> str:
    if key in ("in_shape", "out_shape"):
        shapes = tuple(content.FORMATIONS)
        tactic[key] = _cycle_choice(tactic[key], shapes, direction)
        return f"{key.replace('_', ' ')} set to {tactic[key]}"
    options = content.INSTRUCTIONS.get(key, {})
    values = tuple(options)
    tactic[key] = _cycle_choice(tactic[key], values, direction)
    return f"{key.title()} {tactic[key]}: {options[tactic[key]]}"


def _sub_candidates(career: dict[str, Any], match: dict[str, Any],
                    club_id: str, outgoing_id: str | None = None) -> list[dict[str, Any]]:
    lineup = match["lineups"][club_id]
    outgoing = career["players"].get(outgoing_id) if outgoing_id else None
    outgoing_is_keeper = bool(outgoing and outgoing["position"] == "GK")
    candidates = [career["players"][player_id]
                  for player_id in career["clubs"][club_id]["roster"]
                  if player_id not in lineup
                  and is_available(career, career["players"][player_id])
                  and (career["players"][player_id]["position"] == "GK")
                      == outgoing_is_keeper]
    role = outgoing["position"] if outgoing else "MID"
    return sorted(candidates,
                  key=lambda player: (-role_skill(player, role),
                                      -int(player.get("fitness", 0)), player["name"]))


def _open_substitutions(career: dict[str, Any], match: dict[str, Any],
                        app: dict[str, Any]) -> None:
    club_id = career["club_id"]
    if int(match["substitutions"][club_id]) >= 5:
        app["message"] = "All five substitutions have been used."
        return
    if match["period"] == 0 or match["finished"]:
        app["message"] = "Changes are available after play begins and before full time."
        return
    lineup = [career["players"][player_id] for player_id in match["lineups"][club_id]]
    if not lineup:
        app["message"] = "There is no player on the pitch to replace."
        return
    outfield = [index for index, player in enumerate(lineup)
                if player["position"] != "GK"]
    choices = outfield or list(range(len(lineup)))
    out_index = min(choices, key=lambda index: (
        float(match["load"].get(lineup[index]["id"], lineup[index]["fitness"])),
        lineup[index]["name"]))
    bench = _sub_candidates(career, match, club_id, lineup[out_index]["id"])
    if not bench:
        app["message"] = "No medically cleared player can replace that role. Choose another player to come off."
        return
    app["sub_out_index"] = out_index
    app["sub_in_index"] = 0
    app["sub_focus"] = "out"
    app["page"] = "match_subs"


def _apply_substitution(career: dict[str, Any], match: dict[str, Any],
                        incoming_id: str, outgoing_id: str) -> tuple[bool, str]:
    cid = match["player_club"]
    if match.get("finished") or match["period"] >= content.MATCH_PERIODS or match["period"] == 0:
        return False, "Substitutions are available after play has begun and before full time."
    if int(match["substitutions"][cid]) >= 5:
        return False, "All five substitutions have been used."
    if incoming_id not in career["clubs"][cid]["roster"]:
        return False, "That player is not in your squad."
    if outgoing_id not in match["lineups"][cid]:
        return False, "Choose a player who is currently on the pitch."
    if incoming_id in match["lineups"][cid]:
        return False, "That player is already on the pitch."
    incoming = career["players"].get(incoming_id)
    outgoing = career["players"].get(outgoing_id)
    if not incoming or not outgoing:
        return False, "The selected player record is unavailable."
    if not is_available(career, incoming):
        return False, f"{incoming['name']} is not medically cleared."
    if (incoming["position"] == "GK") != (outgoing["position"] == "GK"):
        return False, "A goalkeeper can only replace the goalkeeper, and an outfield player an outfield player."

    match["lineups"][cid].remove(outgoing_id)
    match["lineups"][cid].append(incoming_id)
    match["substitutions"][cid] += 1
    _player_match_stats(match, incoming_id)
    text = content.MATCH_LINES["substitution"].format(
        incoming=incoming["name"], outgoing=outgoing["name"], minute=match["minute"])
    change = {"minute": int(match["minute"]), "period": int(match["period"]),
              "incoming_id": incoming_id, "outgoing_id": outgoing_id}
    match.setdefault("substitution_history", []).append(change)
    _add_event(match, {"kind": "substitution", "club_id": cid,
                       "actor_id": incoming_id, "target_id": outgoing_id,
                       "text": text, "minute": match["minute"],
                       "period": match["period"], "phase": "touchline",
                       "action": "substitution",
                       "tactical_reason": content.TACTICAL_REASONS["substitution"].format(
                           position=outgoing["position"])})
    return True, text


def _advance_season_from_ui(career: dict[str, Any], app: dict[str, Any]) -> None:
    youth = begin_next_season(career)
    names = ", ".join(career["players"][pid]["name"] for pid in youth[:2])
    app["message"] = f"Season {career['season']} begins. New academy players: {names}."


def _draw_page(win, body: ui.Rect, career: dict[str, Any] | None,
               app: dict[str, Any]) -> None:
    page = app.get("page", "home")
    if page == "career_select":
        _draw_new_career(win, body, app)
    elif page == "help":
        _draw_help(win, body)
    elif page == "offer" and career:
        _draw_recruitment(win, body, career, app)
    elif page == "home" and career:
        _draw_home(win, body, career, app)
    elif page == "squad" and career:
        _draw_squad(win, body, career, app)
    elif page == "tactics" and career:
        _draw_tactics(win, body, career, app)
    elif page == "training" and career:
        _draw_training(win, body, career, app)
    elif page == "market" and career:
        _draw_recruitment(win, body, career, app)
    elif page == "table" and career:
        _draw_table(win, body, career, app)
    elif page == "history" and career:
        _draw_history(win, body, career)
    elif page == "team_talk" and career and career.get("live_match"):
        _draw_team_talk(win, body, career, app)
    elif page == "match_subs" and career and career.get("live_match"):
        _draw_substitutions(win, body, career, app)
    elif page == "match" and career and career.get("live_match"):
        _draw_match(win, body, career, app)
    else:
        ui.draw_text(win, body.x, body.y, "Choose a club to start your career.", body.width,
                     _pair(1, bold=True))


def _draw_new_career(win, body: ui.Rect, app: dict[str, Any]) -> None:
    clubs = content.CLUBS
    app["club_index"] = int(clamp(app.get("club_index", 0), 0, len(clubs) - 1))
    left, right = ui.split_horizontal(body, .56, 1)
    panel = _draw_panel_heading(win, left, "CHOOSE YOUR CLUB")
    description = _draw_panel_heading(win, right, "CLUB PROFILE")
    rows = [[index + 1, club["name"],
             "SBL" if club["division"] == "sable" else "TDW", _money(club["budget"]),
             ordinal(content.CLUB_IDENTITY[club["id"]]["expectation"])]
            for index, club in enumerate(clubs)]
    view = ui.TableView(["#", "Club", "Tier", "Fund", "Target"], rows,
                        selected=app["club_index"], widths=[2, 17, 6, 7, 7])
    view.draw(win, ui.Rect(panel.x, panel.y, panel.width, panel.height),
              selected_attr=_pair(3, bold=True), header_attr=_pair(1, bold=True))
    app["club_index"] = view.selected
    club = clubs[app["club_index"]]
    manager = content.MANAGERS[club["id"]]
    identity = content.CLUB_IDENTITY[club["id"]]
    lines = [
        (club["name"], 1),
        (division_name(club["division"]), 1),
        (club["ground"], 2),
        (club["style"], 0),
        (f"Manager: {manager['name']} · {manager['approach']}", 0),
        (f"Board target: top {identity['expectation']} in this tier", 0),
        (f"Patience: {identity['patience']}/100", 0),
        (identity["supporter_style"], 5),
        (f"Transfer fund: {_money(club['budget'])}", 3),
        ("Roster and tactics are yours to reshape.", 0),
    ]
    y = description.y
    for line, pair in lines:
        if y >= body.bottom - 2:
            break
        ui.draw_text(win, description.x, y, line, description.width,
                     _pair(pair, bold=pair == 1))
        y += 1
    _draw_hint(win, body, "12 clubs · two tiers · arrows select · Enter starts a seeded career")


def _handle_offer_key(key: int, career: dict[str, Any], app: dict[str, Any]) -> bool:
    offer = app.get("offer")
    if not offer:
        return False
    if key in (27, curses.KEY_BACKSPACE):
        app["offer"] = None
        app["page"] = "market"
        app["nav_index"] = SECTION_PAGES.index("market")
        app["message"] = "Negotiation closed without an offer."
    elif key == curses.KEY_LEFT:
        offer["fee"] = max(0, int(offer["fee"]) - 10)
    elif key == curses.KEY_RIGHT:
        offer["fee"] = int(offer["fee"]) + 10
    elif key == curses.KEY_UP:
        offer["wage"] = round(float(offer["wage"]) + .1, 1)
    elif key == curses.KEY_DOWN:
        offer["wage"] = max(0, round(float(offer["wage"]) - .1, 1))
    elif key in (ord("c"), ord("C")) and offer.get("counter"):
        offer["fee"] = int(offer["counter"]["counter_fee"])
        offer["wage"] = float(offer["counter"]["counter_wage"])
        offer["counter"] = None
        offer["message"] = "Counter terms selected. Press Enter to submit."
    elif key in (10, 13, curses.KEY_ENTER):
        result = resolve_offer(career, offer["player_id"],
                               int(offer["fee"]), float(offer["wage"]))
        if result["accepted"]:
            app["message"] = f"Deal done: {career['players'][offer['player_id']]['name']} joins the squad."
            app["offer"] = None
            app["page"] = "market"
            app["nav_index"] = SECTION_PAGES.index("market")
        else:
            offer["message"] = result["reason"]
            offer["accepted"] = False
            offer["counter"] = result if result.get("counter_fee") is not None else None
            if offer.get("counter"):
                app["message"] = "The agent returned terms. C accepts; arrows can adjust the counter."
            else:
                app["message"] = result["reason"]
    return True


def _handle_team_talk_key(key: int, career: dict[str, Any],
                          app: dict[str, Any]) -> bool:
    match = career.get("live_match")
    if not match:
        app["page"] = "home"
        app["nav_index"] = 0
        return True
    if key == 27:
        app["page"] = "home"
        app["nav_index"] = 0
        app["message"] = "Match paused before kickoff. M returns to the team talk."
    elif key in (curses.KEY_UP, ord("k")):
        app["talk_index"] = max(0, int(app.get("talk_index", 0)) - 1)
    elif key in (curses.KEY_DOWN, ord("j")):
        app["talk_index"] = min(len(content.TEAM_TALKS) - 1,
                                 int(app.get("talk_index", 0)) + 1)
    elif key in (10, 13, curses.KEY_ENTER):
        index = int(clamp(app.get("talk_index", 0), 0, len(content.TEAM_TALKS) - 1))
        delivered, message = _deliver_team_talk(
            career, match, content.TEAM_TALKS[index]["id"])
        app["message"] = message
        if delivered:
            app["page"] = "match"
            app["match_view"] = "live"
    return True


def _handle_substitution_key(key: int, career: dict[str, Any],
                             app: dict[str, Any]) -> bool:
    match = career.get("live_match")
    if not match:
        app["page"] = "home"
        app["nav_index"] = 0
        return True
    if key in (27, ord("q"), ord("Q")):
        app["page"] = "match"
        app["message"] = "No change made."
        return True
    if key in (9, getattr(curses, "KEY_BTAB", -99)):
        app["sub_focus"] = "in" if app.get("sub_focus", "out") == "out" else "out"
        return True

    club_id = career["club_id"]
    lineup = [career["players"][pid] for pid in match["lineups"][club_id]]
    out_index = int(clamp(app.get("sub_out_index", 0), 0, max(0, len(lineup) - 1)))
    outgoing = lineup[out_index] if lineup else None
    bench = _sub_candidates(career, match, club_id, outgoing["id"] if outgoing else None)
    in_index = int(clamp(app.get("sub_in_index", 0), 0, max(0, len(bench) - 1)))
    focus = app.get("sub_focus", "out")
    if key in (curses.KEY_UP, ord("k")):
        if focus == "in":
            app["sub_in_index"] = max(0, in_index - 1)
        else:
            app["sub_out_index"] = max(0, out_index - 1)
            new_out = lineup[app["sub_out_index"]] if lineup else None
            new_bench = _sub_candidates(
                career, match, club_id, new_out["id"] if new_out else None)
            app["sub_in_index"] = min(in_index, max(0, len(new_bench) - 1))
    elif key in (curses.KEY_DOWN, ord("j")):
        if focus == "in":
            app["sub_in_index"] = min(max(0, len(bench) - 1), in_index + 1)
        else:
            app["sub_out_index"] = min(max(0, len(lineup) - 1), out_index + 1)
            new_out = lineup[app["sub_out_index"]] if lineup else None
            new_bench = _sub_candidates(
                career, match, club_id, new_out["id"] if new_out else None)
            app["sub_in_index"] = min(in_index, max(0, len(new_bench) - 1))
    elif key in (10, 13, curses.KEY_ENTER):
        outgoing = lineup[out_index] if lineup else None
        if not outgoing or not bench:
            app["message"] = "Select an eligible player on both sides before confirming."
            return True
        incoming = bench[in_index]
        changed, message = _apply_substitution(
            career, match, incoming["id"], outgoing["id"])
        app["message"] = message
        if changed:
            app["page"] = "match"
            app["match_view"] = "events"
    return True


def _handle_match_key(key: int, career: dict[str, Any], app: dict[str, Any]) -> bool:
    match = career.get("live_match")
    if not match:
        app["page"] = "home"
        app["nav_index"] = 0
        return True
    if key == 9:
        view = app.get("match_view", "live")
        app["match_view"] = MATCH_VIEWS[(MATCH_VIEWS.index(view) + 1) % len(MATCH_VIEWS)] \
            if view in MATCH_VIEWS else MATCH_VIEWS[0]
        return True
    if app.get("match_view") == "events" and key in (
            curses.KEY_UP, ord("k"), curses.KEY_DOWN, ord("j")):
        event_count = len(match.get("events", []))
        current = int(clamp(app.get("event_index", 0), 0,
                            max(0, event_count - 1)))
        direction = -1 if key in (curses.KEY_UP, ord("k")) else 1
        app["event_index"] = int(clamp(current + direction, 0,
                                       max(0, event_count - 1)))
        return True
    if match["finished"]:
        if key in (10, 13, curses.KEY_ENTER):
            resolved = complete_user_match(career, match)
            app["page"] = "home"
            app["nav_index"] = 0
            app["message"] = (f"Round settled: {len(resolved)} matches, table and player states updated."
                              if resolved else "This round was already recorded.")
        elif key == 27:
            app["page"] = "home"
            app["nav_index"] = 0
            app["message"] = "Full-time report saved. M returns to this match."
        elif key == ord("6"):
            app["page"] = "table"
            app["nav_index"] = SECTION_PAGES.index("table")
        return True
    if key in (10, 13, curses.KEY_ENTER, ord(" ")):
        simulate_period(career, match)
        app["message"] = ("Full time. Review the score and xG, then settle the round."
                          if match["finished"] else
                          f"The first {match['minute']} minutes are in the ledger. Press Enter for the next phase.")
    elif key in (ord("q"), ord("Q")):
        while not match["finished"]:
            simulate_period(career, match)
        app["message"] = "Quick-sim complete. The same event engine generated this full-time report."
    elif key == ord("1"):
        app["message"] = _change_tactic(match["tactics"][career["club_id"]], "press")
    elif key == ord("2"):
        app["message"] = _change_tactic(match["tactics"][career["club_id"]], "line")
    elif key == ord("3"):
        app["message"] = _change_tactic(match["tactics"][career["club_id"]], "width")
    elif key == ord("4"):
        _open_substitutions(career, match, app)
    elif key == 27:
        app["page"] = "home"
        app["nav_index"] = 0
        app["message"] = "Match paused. M resumes; the current score and period are saved."
    return True


def _route_key(key: int, career: dict[str, Any] | None,
               save_data: dict[str, Any], app: dict[str, Any]) -> bool:
    """Handle one key; return False only when the player exits cleanly."""
    page = app.get("page", "home")
    if key in (curses.KEY_RESIZE, -1):
        return True
    if page == "team_talk" and career:
        _handle_team_talk_key(key, career, app)
        _persist(save_data, career)
        return True
    if page == "match_subs" and career:
        _handle_substitution_key(key, career, app)
        _persist(save_data, career)
        return True
    if page == "match" and career:
        _handle_match_key(key, career, app)
        _persist(save_data, career)
        return True
    if page == "offer" and career:
        _handle_offer_key(key, career, app)
        _persist(save_data, career)
        return True
    if page == "career_select":
        if key in (27, ord("q"), ord("Q")):
            return False
        if key in (curses.KEY_UP, ord("k")):
            app["club_index"] = max(0, app.get("club_index", 0) - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            app["club_index"] = min(len(content.CLUBS) - 1, app.get("club_index", 0) + 1)
        elif ord("1") <= key <= ord("6"):
            app["club_index"] = key - ord("1")
            return _create_selected_career(save_data, app)
        elif key in (10, 13, curses.KEY_ENTER):
            return _create_selected_career(save_data, app)
        _persist(save_data, career)
        return True
    if page == "help":
        if key == 27:
            app["page"] = app.pop("previous_page", "home")
        elif key in (ord("q"), ord("Q")):
            return False
        elif key == 9:
            index = (_page_nav_index(app.get("previous_page", "home")) + 1) % len(SECTION_PAGES)
            app["page"] = SECTION_PAGES[index]
            app["nav_index"] = index
        elif ord("1") <= key <= ord("7"):
            index = key - ord("1")
            app["page"] = SECTION_PAGES[index]
            app["nav_index"] = index
        elif key in (ord("m"), ord("M")) and career:
            app["nav_index"] = MATCH_NAV_INDEX
            _start_matchday(career, app)
        _persist(save_data, career)
        return True
    if key == 27:
        app["page"] = "home"
        app["nav_index"] = 0
        _persist(save_data, career)
        return True
    if key in (ord("q"), ord("Q")):
        _persist(save_data, career)
        return False
    if key in (curses.KEY_LEFT, curses.KEY_RIGHT):
        current_focus = int(clamp(app.get("nav_index", _page_nav_index(page)),
                                  0, MATCH_NAV_INDEX))
        direction = -1 if key == curses.KEY_LEFT else 1
        app["nav_index"] = (current_focus + direction) % (MATCH_NAV_INDEX + 1)
        _persist(save_data, career)
        return True
    if key in (10, 13, curses.KEY_ENTER):
        focus = int(clamp(app.get("nav_index", _page_nav_index(page)),
                          0, MATCH_NAV_INDEX))
        current = _page_nav_index(page)
        if focus == MATCH_NAV_INDEX and career:
            _start_matchday(career, app)
            _persist(save_data, career)
            return True
        if focus != current and focus < len(SECTION_PAGES):
            app["page"] = SECTION_PAGES[focus]
            app["message"] = ""
            _persist(save_data, career)
            return True
    if key == ord("?"):
        app["previous_page"] = page
        app["page"] = "help"
    elif key == 9:
        index = (_page_nav_index(page) + 1) % len(SECTION_PAGES)
        app["page"] = SECTION_PAGES[index]
        app["nav_index"] = index
    elif ord("1") <= key <= ord("7"):
        index = key - ord("1")
        app["page"] = SECTION_PAGES[index]
        app["nav_index"] = index
    elif page == "home" and key in (10, 13, curses.KEY_ENTER) and career and career["season_complete"]:
        _advance_season_from_ui(career, app)
    elif key in (ord("m"), ord("M")) and career:
        app["nav_index"] = MATCH_NAV_INDEX
        _start_matchday(career, app)
        if app.get("page") in SECTION_PAGES:
            app["nav_index"] = _page_nav_index(app["page"])
    elif page == "squad" and career:
        players = _player_rows(career, career["club_id"])
        if key in (curses.KEY_UP, ord("k")):
            app["squad_index"] = max(0, app.get("squad_index", 0) - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            app["squad_index"] = min(max(0, len(players) - 1), app.get("squad_index", 0) + 1)
        elif key in (ord("x"), ord("X")) and players:
            selected = players[app.get("squad_index", 0)]
            app["message"] = toggle_starter(career, career["club_id"], selected["id"])
        elif key in (ord("v"), ord("V")) and players:
            selected = players[app.get("squad_index", 0)]
            result = sale_offer(career, selected["id"])
            app["message"] = (f"Offer accepted: {_money(result['fee'])} from "
                              f"{club_by_id(result['buyer'])['name']}."
                              if result["accepted"] else result["reason"])
    elif page == "tactics" and career:
        tactic = career["clubs"][career["club_id"]]["tactics"]
        names = {"i": "in_shape", "o": "out_shape", "p": "press", "l": "line",
                 "w": "width", "b": "build", "t": "tempo"}
        letter = chr(key).lower() if 0 <= key < 256 else ""
        if letter in names:
            tactic_key = names[letter]
            app["tactic_focus"] = letter.upper()
            app["message"] = _change_tactic(tactic, tactic_key)
            if tactic_key == "in_shape":
                career["clubs"][career["club_id"]]["lineup"] = best_lineup(
                    career, career["club_id"], tactic["in_shape"])
        elif key in (ord("-"), ord("+"), ord("=")):
            selected_key = app.get("tactic_focus", "P").lower()
            direction = -1 if key == ord("-") else 1
            if selected_key in names:
                app["message"] = _change_tactic(tactic, names[selected_key], direction)
                if selected_key == "i":
                    career["clubs"][career["club_id"]]["lineup"] = best_lineup(
                        career, career["club_id"], tactic["in_shape"])
    elif page == "training" and career:
        state = career["clubs"][career["club_id"]]["training"]
        focus_list = list(content.TRAINING_PLANS)
        if key in (curses.KEY_UP, ord("k")):
            app["training_index"] = max(0, app.get("training_index", 0) - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            app["training_index"] = min(len(focus_list) - 1,
                                        app.get("training_index", 0) + 1)
        elif key in (10, 13, curses.KEY_ENTER):
            state["focus"] = focus_list[app.get("training_index", 0)]
            app["message"] = f"Weekly focus set to {state['focus']}; it applies when matchday starts."
        elif key in (ord("i"), ord("I")):
            state["intensity"] = _cycle_choice(state["intensity"], TRAINING_INTENSITIES)
            app["message"] = f"Training intensity set to {state['intensity']}."
    elif page == "market" and career:
        market = [pid for pid in career["market"] if pid in career["players"]]
        if key in (curses.KEY_UP, ord("k")):
            app["market_index"] = max(0, app.get("market_index", 0) - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            app["market_index"] = min(max(0, len(market) - 1), app.get("market_index", 0) + 1)
        elif market:
            selected_id = market[min(app.get("market_index", 0), len(market) - 1)]
            app["selected_market_id"] = selected_id
            if key in (ord("s"), ord("S")):
                try:
                    report = scout_target(career, selected_id)
                    app["message"] = f"{report['confidence']} report: role fit {report['fit']}/100; ranges remain uncertain."
                except ValueError as exc:
                    app["message"] = str(exc)
            elif key in (ord("o"), ord("O"), 10, 13, curses.KEY_ENTER):
                _begin_offer(career, app)
            elif key in (ord("v"), ord("V")):
                app["page"] = "squad"
                app["nav_index"] = SECTION_PAGES.index("squad")
                app["message"] = "Use V on the selected squad player to list them and take a fair incoming bid."
    elif page == "table" and career:
        if key in (curses.KEY_UP, ord("k")):
            app["table_index"] = max(0, int(app.get("table_index", 0)) - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            app["table_index"] = min(len(table_rows(career)) - 1,
                                      int(app.get("table_index", 0)) + 1)
    elif page == "history" and career:
        if key in (curses.KEY_UP, ord("k")):
            app["history_index"] = max(0, int(app.get("history_index", 0)) - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            app["history_index"] = min(max(0, len(career["news"]) - 1),
                                       int(app.get("history_index", 0)) + 1)
    _persist(save_data, career)
    return True


def _create_selected_career(save_data: dict[str, Any], app: dict[str, Any]) -> bool:
    club_id = content.CLUBS[app.get("club_index", 0)]["id"]
    seed = random.SystemRandom().randrange(1, 2_000_000_000)
    career = new_career(club_id, seed)
    save_data["career"] = career
    save_data["version"] = 2
    save_data["_summary"] = _career_summary(career)
    ts.save(save_data)
    app["career"] = career
    app["page"] = "home"
    app["nav_index"] = 0
    app["message"] = f"You take charge at {club_by_id(club_id)['name']}. The squad, board and season are ready."
    app["data"] = save_data
    return True


def _run(stdscr) -> int:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    _init_colors()
    stdscr.keypad(True)
    save_data = migrate_save(ts.load(SAVE_DEFAULTS))
    career = save_data.get("career") if isinstance(save_data.get("career"), dict) else None
    if career:
        _ensure_player_ids(career)
        for cid, state in career.get("clubs", {}).items():
            if not state.get("lineup") and state.get("roster"):
                state["lineup"] = best_lineup(career, cid)
    app: dict[str, Any] = {
        "page": ("team_talk" if career and _needs_team_talk(career.get("live_match"))
                 else "match" if career and career.get("live_match") else
                 "home" if career else "career_select"),
        "nav_index": (MATCH_NAV_INDEX if career and career.get("live_match") else 0),
        "club_index": 0, "squad_index": 0, "market_index": 0,
        "match_view": "live",
        "message": "Choose a club and build a football life around its people.",
    }
    app["career"] = career
    app["data"] = save_data
    win, screen = ts.tv_curses(stdscr, "Ekse Slaan Ball")
    _restore_bezel_bottom_right(stdscr, screen)
    win.clear()
    win.keypad(True)
    while True:
        body = _draw_frame(win, career, app)
        _draw_page(win, body, career, app)
        win.noutrefresh()
        curses.doupdate()
        _restore_bezel_bottom_right(stdscr, screen)
        key = win.getch()
        if key == curses.KEY_RESIZE:
            win, screen = ts.tv_curses(stdscr, "Ekse Slaan Ball")
            _restore_bezel_bottom_right(stdscr, screen)
            win.clear()
            win.keypad(True)
            continue
        result = _route_key(key, career, save_data, app)
        career = app.get("career", career)
        if not result:
            return 0


def main() -> int:
    try:
        return int(curses.wrapper(_run) or 0)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
