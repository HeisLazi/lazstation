#!/usr/bin/env python3
"""Ekse Slaan Ball: a deterministic, explainable football management career.

Authored clubs, players, formations, fixtures, and narrative live in
``content.py``. The functions below contain the simulation rules so they can
be exercised headlessly without curses, a save file, or a terminal.
"""
from __future__ import annotations

import copy
import curses
import json
import math
import os
import random
import sys
from dataclasses import dataclass, replace
from itertools import combinations
from pathlib import Path
from typing import Any

# The game launcher executes this file from ``games/touchline`` and exposes
# only the shared SDK on PYTHONPATH. The headless engine is imported as the
# ``games.touchline`` package, so make the repository root importable before
# loading any engine modules in direct-script mode.
if not __package__:
    _repository_root = str(Path(__file__).resolve().parents[2])
    if _repository_root not in sys.path:
        sys.path.insert(0, _repository_root)

import termstation_sdk as ts
import termstation_ui as ui

from games.touchline.esb.career_adapter import (
    LEGACY_ENGINE_ID,
    SPATIAL_ENGINE_ID,
    CareerMatchSession,
    VersionedCareerSave,
    load_preparation_state,
    migrate_v2_save,
    resume_spatial_career_match,
    settle_spatial_career_match,
    start_spatial_career_match,
)
from games.touchline.esb.career_matchday import (
    FORMATION_SLOT_IDS,
    MATCHDAY_PROFILE_STYLES,
    MATCHDAY_RULES,
    PROFILE_MAPPING_VERSION,
    SLOT_ROLES,
    build_team_sheet,
    career_tactic,
    default_formation_positions,
    formation_slots,
    legal_formation_positions,
    tactical_runtimes,
)
from games.touchline.esb.ids import PlayerId
from games.touchline.esb.match import (
    BallPhysics,
    MatchPhase,
    MatchPeriod,
    Pitch,
    RestartKind,
    limits_from_profile,
    step_match,
    substitute,
)
from games.touchline.esb.model import Position2D
from games.touchline.esb.world.preparation import (
    SelectionStatus,
    prepared_profile,
    selection_assessment,
)

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
SPATIAL_MATCH_VIEWS = ("live", "pitch", "events", "stats", "players")
SECTION_PAGES = ("home", "squad", "tactics", "training", "market", "table", "history")
SECTION_LABELS = ("HOME", "SQUAD", "PLAN", "TRAIN", "MARKET", "TABLE", "LOGS")
MATCH_NAV_INDEX = len(SECTION_PAGES)
PAGE_BREADCRUMBS = {
    "career_select": "NEW CAREER / CHOOSE A CLUB",
    "help": "HELP / GAME CONTROLS",
    "team_talk": "MATCHDAY / TEAM TALK · PRE-KICKOFF",
    "match_subs": "MATCHDAY / CHANGES · SELECT A PAIR",
    "match_setup": "MATCHDAY / SHAPE & FREE PLACEMENT",
    "spatial_match": "MATCHDAY / LIVE SPATIAL SIM",
    "spatial_report": "CAREER / LAST SPATIAL MATCH REPORT",
    "spatial_subs": "MATCHDAY / CHANGES · QUEUE AT NEXT STOPPAGE",
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
    adapter_save = None
    if isinstance(data, dict) and data.get("format") == "esb.core-record":
        record_keys = {"format", "schema_version", "record_type", "payload"}
        sdk_defaults = {"version", "career"}
        if set(data) - record_keys - sdk_defaults:
            raise ValueError("versioned career save has unexpected top-level fields")
        record = {key: data[key] for key in record_keys if key in data}
        adapter_save = VersionedCareerSave.from_json(json.dumps(
            record, ensure_ascii=False, allow_nan=False, sort_keys=True))
        data = adapter_save.legacy_save
        data["_career_adapter_state"] = adapter_save
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
        if (not career["season_complete"]
                and not (isinstance(adapter_save, VersionedCareerSave)
                         and adapter_save.spatial_match_json is not None)):
            current = current_fixture(career)
            if current is not None and any(
                isinstance(result, dict)
                and result.get("engine_id") == "touchline.spatial.v1"
                and result.get("season") == career["season"]
                and result.get("round") == career["round"] + 1
                and (result.get("home"), result.get("away")) == tuple(current)
                for result in career.get("results", [])
            ):
                raise ValueError(
                    "the spatial fixture is settled but its career round is not; "
                    "finish the round through the career adapter before legacy play resumes"
                )
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
    adapter_save = save_data.get("_career_adapter_state")
    if not isinstance(adapter_save, VersionedCareerSave):
        ts.save(save_data)
        return
    legacy_payload = {key: copy.deepcopy(value) for key, value in save_data.items()
                      if key != "_career_adapter_state"}
    match = career.get("live_match") if isinstance(career, dict) else None
    spatial_json = adapter_save.spatial_match_json
    if spatial_json is not None:
        if match is not None:
            raise ValueError("career cannot persist simultaneous legacy and spatial matches")
        spatial_session = CareerMatchSession.from_json(spatial_json)
        current_match_engine_id = SPATIAL_ENGINE_ID
        current_match_id = str(spatial_session.binding.match_id)
    elif match is None:
        current_match_engine_id = None
        current_match_id = None
    else:
        match_id = match.get("id") if isinstance(match, dict) else None
        if not isinstance(match_id, str):
            raise ValueError("active legacy match has no stable ID for save metadata")
        current_match_engine_id = LEGACY_ENGINE_ID
        current_match_id = match_id
    labels = dict(adapter_save.historical_engine_labels)
    if isinstance(career, dict):
        for result in career.get("results", []):
            if isinstance(result, dict) and isinstance(result.get("id"), str):
                result_engine = result.get("engine_id")
                labels.setdefault(result["id"],
                                  result_engine if isinstance(result_engine, str)
                                  else LEGACY_ENGINE_ID)
        for played_id in career.get("played_ids", []):
            if isinstance(played_id, str):
                labels.setdefault(played_id, LEGACY_ENGINE_ID)
    updated_adapter = replace(
        adapter_save,
        legacy_save_json=json.dumps(legacy_payload, ensure_ascii=False, allow_nan=False,
                                    sort_keys=True, separators=(",", ":")),
        current_match_engine_id=current_match_engine_id,
        current_match_id=current_match_id,
        spatial_match_json=spatial_json,
        historical_engine_labels=tuple(sorted(labels.items())),
    )
    save_data["_career_adapter_state"] = updated_adapter
    ts.save(json.loads(updated_adapter.to_json()))


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
    out.append(f"\x1b[{bottom + 1};{screen.ox + 1}H"
               f"╚{'═' * max(0, screen.cab_w - 2)}╝")
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
        footer = "Tab OFF/ON list · ↑/↓ select · Enter confirm · Esc cancel"
    elif page == "match_setup":
        footer = "↑/↓ or 1–9,0,A select · wasd place · F shape · T plan · Enter · Esc"
    elif page == "spatial_subs":
        if app.get("spatial_keeper_user_required"):
            footer = "GK required · Tab OFF/ON · ↑/↓ select · Enter apply · Esc"
        else:
            footer = "Tab OFF/ON list · ↑/↓ select · Enter queue/apply · Esc back"
    elif page == "spatial_match":
        phase = app.get("spatial_match_phase")
        zoom_hint = (f" · Z {'full' if app.get('spatial_pitch_zoom') else 'zoom'}"
                     if app.get("match_view") == "pitch" else "")
        if phase is MatchPhase.FINISHED:
            footer = "Tab review · ↑/↓ browse · Enter settle · Esc home" + zoom_hint
        elif phase is MatchPhase.ABANDONED:
            footer = "Abandoned · no result policy · Tab review · Esc save/leave" + zoom_hint
        elif app.get("spatial_keeper_user_required"):
            footer = "Keeper change required · S choose GK · Q stops here · Esc" + zoom_hint
        elif app.get("spatial_keeper_replacement"):
            footer = "Opponent keeper pending · Space watch · Q quick · Tab · Esc" + zoom_hint
        elif app.get("match_view") == "pitch":
            zoom_hint = "Z full" if app.get("spatial_pitch_zoom") else "Z zoom"
            footer = (f"Space pause · . step · +/- · {zoom_hint} · S subs · Q sim · Esc home"
                      if app.get("spatial_watching") else
                      f"Space watch · . step · +/- · {zoom_hint} · S subs · Q sim · Esc home")
        elif app.get("match_view") in ("events", "stats", "players"):
            label = "↑↓ browse · M all" if app.get("match_view") == "events" else "↑↓ list"
            footer = (f"Space watch · . step · +/- · S subs · {label} · Tab · Esc home"
                      if not app.get("spatial_watching") else
                      f"Space pause · +/- · S subs · {label} · Tab · Esc home")
        else:
            footer = ("Space pause · . step · +/- · Q sim · S subs · Tab views · Z pitch · Esc"
                      if app.get("spatial_watching") else
                      "Space watch · . step · +/- · Q sim · S subs · Tab views · Z pitch · Esc")
    elif page == "spatial_report":
        footer = "↑/↓ inspect · Esc home · M next match"
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


def _latest_managed_spatial_result(career: dict[str, Any]) -> dict[str, Any] | None:
    results = career.get("results", [])
    club_id = career.get("club_id")
    if not isinstance(results, list) or not isinstance(club_id, str):
        return None
    return next((record for record in reversed(results)
                 if isinstance(record, dict)
                 and record.get("engine_id") == SPATIAL_ENGINE_ID
                 and club_id in (record.get("home"), record.get("away"))), None)


def _spatial_home_hint(app: dict[str, Any]) -> str:
    adapter = app.get("_save_data", {}).get("_career_adapter_state")
    if not isinstance(adapter, VersionedCareerSave) or adapter.spatial_match_json is None:
        career = app.get("career")
        result = _latest_managed_spatial_result(career) if isinstance(career, dict) else None
        if result is not None:
            home, away = club_by_id(result["home"])["name"], club_by_id(result["away"])["name"]
            return (f"Last: {home} {result['home_goals']}–{result['away_goals']} {away} "
                    "· R match report")
        return "Pre-kickoff: review the XI, shape and weekly training plan"
    try:
        session = resume_spatial_career_match(adapter)
        if session.match.phase is MatchPhase.FINISHED:
            return "Spatial match full time · M opens the saved match report"
        if session.match.phase is MatchPhase.ABANDONED:
            return "Spatial match abandoned · M opens its saved event record"
        return "Live match paused · M reopens the saved pitch and chronology"
    except (TypeError, ValueError):
        return "Saved spatial match needs review · M opens matchday"


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
                         f"ATT {tactic['in_shape']} / DEF {tactic['out_shape']}", left.width)
            ui.draw_text(win, left.x, y + 8,
                         f"Press {tactic['press']} · line {tactic['line']}", left.width)
            ui.draw_text(win, left.x, y + 9,
                         f"Width {tactic['width']} · Build {tactic['build']}", left.width)
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
    _draw_hint(win, body, _spatial_home_hint(app))


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


def _draw_spatial_report(win, body: ui.Rect, career: dict[str, Any],
                         app: dict[str, Any]) -> None:
    record = _latest_managed_spatial_result(career)
    if record is None:
        ui.draw_text(win, body.x, body.y, "NO SPATIAL MATCH REPORT SAVED", body.width,
                     _pair(4, bold=True))
        ui.draw_text(win, body.x, body.y + 2,
                     "Finish and settle a spatial match to add its report to the career ledger.",
                     body.width, _pair(6))
        return

    home_id, away_id = str(record["home"]), str(record["away"])
    home_name, away_name = club_by_id(home_id)["name"], club_by_id(away_id)["name"]
    ui.draw_text(win, body.x, body.y,
                 f"MATCH REPORT · S{record['season']} ROUND {record['round']} · "
                 f"{str(record.get('division', '')).upper()}",
                 body.width, _pair(2, bold=True))
    ui.draw_text(win, body.x, body.y + 1,
                 f"{home_name}  {record['home_goals']}–{record['away_goals']}  {away_name}",
                 body.width, _pair(1, bold=True))

    rows: list[tuple[str, int]] = []
    rows.append((f"ENGINE {record.get('engine_id', 'unknown')} · "
                 f"RULESET {record.get('ruleset_id', 'unknown')} · "
                 f"v{record.get('ruleset_version', '?')}", 6))
    rows.append(("GOAL CHRONOLOGY", 1))
    goals = record.get("goal_lineages", [])
    if isinstance(goals, list) and goals:
        for goal in goals:
            if not isinstance(goal, dict):
                continue
            own_goal_id = goal.get("own_goal_id")
            scorer_id = own_goal_id or goal.get("scorer_id")
            scorer = _player_name(career, scorer_id) if scorer_id else "Unknown scorer"
            label = f"OWN GOAL · {scorer}" if own_goal_id else f"GOAL · {scorer}"
            assist_id = goal.get("assist_id")
            if assist_id:
                label += f" · assist {_player_name(career, assist_id)}"
            rows.append((label, 3))
    else:
        rows.append(("No goals recorded.", 6))

    rows.append(("GOAL BUILD-UP · CAUSE AND PASS LINEAGE", 1))
    lineage_events = record.get("lineage_events", [])
    if isinstance(lineage_events, list) and lineage_events:
        for event in lineage_events:
            if not isinstance(event, dict):
                continue
            payload = event.get("payload", {})
            actor_id = event.get("actor_id") or (
                payload.get("actor_id") if isinstance(payload, dict) else None)
            actor = _player_name(career, actor_id) if actor_id else "Match"
            kind = str(event.get("kind", "event")).replace("_", " ").upper()
            rows.append((f"#{event.get('sequence', '?')}  {kind} · {actor}", 6))
    else:
        rows.append(("No goal lineage events recorded.", 6))

    minutes = record.get("stats", {}).get("minutes", {})
    appearances = []
    if isinstance(minutes, dict):
        for player_id, played in minutes.items():
            try:
                played_value = float(played)
            except (TypeError, ValueError):
                continue
            if played_value > 0:
                player = career.get("players", {}).get(str(player_id), {})
                club_id = player.get("club") if isinstance(player, dict) else None
                side = "H" if club_id == home_id else "A" if club_id == away_id else "?"
                appearances.append((side, played_value, _player_name(career, player_id)))
    appearances.sort(key=lambda item: (item[0], -item[1], item[2]))
    rows.append((f"PLAYING TIME · {len(appearances)} APPEARANCES", 1))
    rows.extend((f"{side}  {name} · {played:g} min", 6)
                for side, played, name in appearances)

    visible_top = body.y + 3
    visible_rows = max(0, body.bottom - visible_top - 1)
    last_start = max(0, len(rows) - visible_rows)
    start = int(clamp(app.get("spatial_report_scroll", 0), 0, last_start))
    app["spatial_report_scroll"] = start
    for offset, (line, pair) in enumerate(rows[start:start + visible_rows]):
        ui.draw_text(win, body.x, visible_top + offset, line, body.width,
                     _pair(pair, bold=pair == 1))


def _draw_help(win, body: ui.Rect) -> None:
    lines = [
        ("THE MANAGER'S DESK", 1),
        ("←/→ browse the section bar; Enter opens the focused page.", 0),
        ("Brackets show keyboard focus; › marks the page you are on.", 0),
        ("1-7 jump to Home, Squad, Plan, Training, Market, Table and Logs.", 0),
        ("M starts or resumes matchday; ? opens this guide.", 0),
        ("After a spatial fixture, R opens its saved match report from Home.", 0),
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


def _player_name(career: dict[str, Any], player_id: object) -> str:
    player = career.get("players", {}).get(str(player_id))
    return str(player.get("name", str(player_id))) if isinstance(player, dict) else str(player_id)


def _pitch_world_positions(positions: dict[str, Position2D], team_id: str,
                           pitch: Pitch = Pitch()) -> dict[str, Position2D]:
    if team_id == "home":
        return dict(positions)
    return {slot: Position2D(pitch.length_m - item.x_m, item.y_m)
            for slot, item in positions.items()}


def _pitch_map_cell(position: Position2D, pitch: Pitch,
                    width: int, height: int,
                    bounds: tuple[float, float, float, float] | None = None
                    ) -> tuple[int, int] | None:
    """Map pitch metres onto the same interior cells used by the terminal renderer."""
    width = max(5, width)
    height = max(3, height)
    x_min, x_max, y_min, y_max = bounds or (
        0.0, pitch.length_m, 0.0, pitch.width_m)
    if (position.x_m < x_min or position.x_m > x_max
            or position.y_m < y_min or position.y_m > y_max):
        return None
    col = round((position.x_m - x_min) / max(0.001, x_max - x_min) * (width - 1))
    row = round((position.y_m - y_min) / max(0.001, y_max - y_min) * (height - 1))
    return min(width - 2, max(1, col)), min(height - 2, max(1, row))


def _spatial_player_cycle_ids(match, selected_id: str,
                              viewport: tuple[int, int] | None,
                              bounds: tuple[float, float, float, float] | None = None
                              ) -> list[PlayerId]:
    """Cycle inside the selected map cell when it contains a visible cluster."""
    player_ids = list(match.play.players)
    selected = next((player_id for player_id in player_ids
                     if str(player_id) == selected_id), None)
    if selected is None or viewport is None:
        return player_ids
    width, height = viewport
    selected_cell = _pitch_map_cell(
        match.play.players[selected].motion.position, match.play.pitch,
        width, height, bounds)
    clustered = [player_id for player_id in player_ids
                 if _pitch_map_cell(
                     match.play.players[player_id].motion.position,
                     match.play.pitch, width, height, bounds) == selected_cell]
    return clustered if len(clustered) > 1 else player_ids


def _spatial_pitch_focus_bounds(match, selected_id: str | None,
                                viewport: tuple[int, int] | None = None
                                ) -> tuple[float, float, float, float]:
    """Return a compact local view sized for a text-cell pitch map."""
    pitch = match.play.pitch
    state = next((state for player_id, state in match.play.players.items()
                  if selected_id is not None and str(player_id) == selected_id), None)
    focus = state.motion.position if state else match.play.ball.position
    map_width, map_height = viewport or (60, 12)
    terminal_aspect = max(
        1.0, max(1, map_width - 2) / max(1, map_height - 2))
    span_x = min(36.0, pitch.length_m)
    # Terminal rows are roughly twice as tall as they are wide. The minimum
    # cross-pitch span keeps the camera useful on short 80x24 map areas.
    span_y = min(pitch.width_m,
                 max(16.0, span_x * 2 / terminal_aspect))
    x_min = min(max(0.0, focus.x_m - span_x / 2), pitch.length_m - span_x)
    y_min = min(max(0.0, focus.y_m - span_y / 2), pitch.width_m - span_y)
    return (x_min, x_min + span_x, y_min, y_min + span_y)


SPATIAL_HOME_MARKERS = "1234567890ACDEFGHIJKLMNOPQRSTUVWXYZ"


def _draw_pitch_map(win, area: ui.Rect, pitch: Pitch,
                    players: list[tuple[str, Position2D, str]],
                    ball: Position2D | None = None,
                    *, selected_id: str | None = None,
                    highlighted_id: str | None = None,
                    player_symbols: dict[str, str] | None = None,
                    bounds: tuple[float, float, float, float] | None = None
                    ) -> dict[str, int]:
    """Render the live pitch as a persistent text map, with actors overlaid."""
    width = max(5, area.width)
    height = area.height
    if area.height < 5:
        return {}
    grid = [[" " for _ in range(width)] for _ in range(height)]
    horizontal_frame = "─" if bounds is None else "┄"
    vertical_frame = "│" if bounds is None else "┆"
    for x in range(width):
        grid[0][x] = horizontal_frame
        grid[-1][x] = horizontal_frame
    for y in range(height):
        grid[y][0] = vertical_frame
        grid[y][-1] = vertical_frame
    if bounds is None:
        grid[0][0], grid[0][-1] = "┌", "┐"
        grid[-1][0], grid[-1][-1] = "└", "┘"
    else:
        grid[0][0], grid[0][-1] = "╭", "╮"
        grid[-1][0], grid[-1][-1] = "╰", "╯"
    mid_y = (height - 1) // 2
    x_min, x_max, y_min, y_max = bounds or (
        0.0, pitch.length_m, 0.0, pitch.width_m)
    if bounds is None:
        mid_x = (width - 1) // 2
        for y in range(1, height - 1):
            grid[y][mid_x] = "│"
        grid[mid_y][mid_x] = "+"
        # The centre ring and penalty boxes stay visible even when the playing
        # actors are sparse. Scale their radii from the rulebook pitch geometry.
        ring_dx = max(2, round(9.15 / pitch.length_m * (width - 2)))
        ring_dy = max(1, round(9.15 / pitch.width_m * (height - 2)))
        for dx, dy, mark in ((-ring_dx, 0, "o"), (ring_dx, 0, "o"),
                             (0, -ring_dy, "o"), (0, ring_dy, "o")):
            x, y = mid_x + dx, mid_y + dy
            if 1 <= x < width - 1 and 1 <= y < height - 1:
                grid[y][x] = mark

        def draw_boxes(depth_m: float, width_m: float) -> None:
            depth = max(1, round(depth_m / pitch.length_m * (width - 2)))
            half_width = max(1, round(width_m / pitch.width_m * (height - 2)))
            top = max(1, mid_y - half_width)
            bottom = min(height - 2, mid_y + half_width)
            left_inner, right_inner = 1 + depth, width - 2 - depth
            for row in range(top + 1, bottom):
                grid[row][left_inner] = grid[row][right_inner] = "│"
            for col in range(1, left_inner):
                grid[top][col] = grid[bottom][col] = "─"
            for col in range(right_inner + 1, width - 1):
                grid[top][col] = grid[bottom][col] = "─"
            grid[top][0], grid[bottom][0] = "├", "├"
            grid[top][left_inner], grid[bottom][left_inner] = "┤", "┤"
            grid[top][right_inner], grid[bottom][right_inner] = "├", "├"
            grid[top][-1], grid[bottom][-1] = "┤", "┤"

        draw_boxes(16.5, 40.3)
        draw_boxes(5.5, 18.32)
        grid[mid_y][1], grid[mid_y][-2] = "[", "]"
    elif x_min <= pitch.length_m / 2 <= x_max:
        mid_x, _ = _pitch_map_cell(
            Position2D(pitch.length_m / 2, y_min), pitch, width, height, bounds)
        for y in range(1, height - 1):
            grid[y][mid_x] = "│"
    if bounds is not None:
        def draw_horizontal(y_m: float, start_x_m: float, end_x_m: float,
                            mark: str = "─") -> None:
            if not y_min <= y_m <= y_max:
                return
            start = max(x_min, 0.0, min(start_x_m, end_x_m))
            end = min(x_max, pitch.length_m, max(start_x_m, end_x_m))
            if start > end:
                return
            start_cell = _pitch_map_cell(
                Position2D(start, y_m), pitch, width, height, bounds)
            end_cell = _pitch_map_cell(
                Position2D(end, y_m), pitch, width, height, bounds)
            if start_cell is None or end_cell is None:
                return
            row = start_cell[1]
            for col in range(min(start_cell[0], end_cell[0]),
                             max(start_cell[0], end_cell[0]) + 1):
                grid[row][col] = mark

        def draw_vertical(x_m: float, start_y_m: float, end_y_m: float,
                          mark: str = "│") -> None:
            if not x_min <= x_m <= x_max:
                return
            start = max(y_min, 0.0, min(start_y_m, end_y_m))
            end = min(y_max, pitch.width_m, max(start_y_m, end_y_m))
            if start > end:
                return
            start_cell = _pitch_map_cell(
                Position2D(x_m, start), pitch, width, height, bounds)
            end_cell = _pitch_map_cell(
                Position2D(x_m, end), pitch, width, height, bounds)
            if start_cell is None or end_cell is None:
                return
            col = start_cell[0]
            for row in range(min(start_cell[1], end_cell[1]),
                             max(start_cell[1], end_cell[1]) + 1):
                grid[row][col] = mark

        # Draw real field landmarks that intersect the camera, clipping each
        # segment to its world-space viewport instead of inventing a local box.
        half_y = pitch.width_m / 2
        draw_horizontal(0.0, 0.0, pitch.length_m)
        draw_horizontal(pitch.width_m, 0.0, pitch.length_m)
        draw_vertical(0.0, 0.0, pitch.width_m)
        draw_vertical(pitch.length_m, 0.0, pitch.width_m)
        draw_vertical(pitch.length_m / 2, 0.0, pitch.width_m)
        penalty_half = 40.32 / 2
        goal_area_half = 18.32 / 2
        for start_x, end_x, half_width in (
                (0.0, 16.5, penalty_half),
                (pitch.length_m - 16.5, pitch.length_m, penalty_half),
                (0.0, 5.5, goal_area_half),
                (pitch.length_m - 5.5, pitch.length_m, goal_area_half)):
            draw_horizontal(half_y - half_width, start_x, end_x)
            draw_horizontal(half_y + half_width, start_x, end_x)
            inner_x = end_x if start_x == 0.0 else start_x
            draw_vertical(inner_x, half_y - half_width, half_y + half_width)
        for spot_x in (11.0, pitch.length_m - 11.0):
            spot = _pitch_map_cell(
                Position2D(spot_x, half_y), pitch, width, height, bounds)
            if spot is not None:
                grid[spot[1]][spot[0]] = "."
        center_x = pitch.length_m / 2
        center_radius = 9.15
        circle_points = ((center_x - center_radius, half_y),
                         (center_x + center_radius, half_y),
                         (center_x, half_y - center_radius),
                         (center_x, half_y + center_radius))
        for x_m, y_m in circle_points:
            point = _pitch_map_cell(
                Position2D(x_m, y_m), pitch, width, height, bounds)
            if point is not None:
                grid[point[1]][point[0]] = "o"
        center = _pitch_map_cell(
            Position2D(center_x, half_y), pitch, width, height, bounds)
        if center is not None:
            grid[center[1]][center[0]] = "+"

        # Small, evenly spaced pitch-coordinate ticks make the crop scale
        # legible even when the goal and halfway lines are outside the view.
        first_x_tick = math.ceil(x_min / 5) * 5
        for tick in range(first_x_tick, int(x_max) + 1, 5):
            cell = _pitch_map_cell(
                Position2D(float(tick), y_min), pitch, width, height, bounds)
            if cell is not None:
                grid[1][cell[0]] = "┬"
        first_y_tick = math.ceil(y_min / 5) * 5
        for tick in range(first_y_tick, int(y_max) + 1, 5):
            cell = _pitch_map_cell(
                Position2D(x_min, float(tick)), pitch, width, height, bounds)
            if cell is not None:
                grid[cell[1]][1] = "├"
    symbols = {"home": SPATIAL_HOME_MARKERS,
               "away": "abcdefghijklmnopqrstuvwxyz"}
    seen = {"home": 0, "away": 0}
    occupied: dict[tuple[int, int], list[tuple[str, str, str]]] = {}
    for team_id, position, player_id in players:
        if team_id not in symbols:
            continue
        cell = _pitch_map_cell(position, pitch, width, height, bounds)
        if cell is None:
            continue
        col, row = cell
        symbol = (player_symbols or {}).get(
            player_id, symbols[team_id][seen[team_id] % len(symbols[team_id])])
        seen[team_id] += 1
        if player_id == selected_id:
            symbol = "@"
        elif player_id == highlighted_id:
            symbol = "!"
        occupied.setdefault((row, col), []).append((team_id, symbol, player_id))
    cluster_sizes: dict[str, int] = {}
    for (row, col), actors in occupied.items():
        for _team, _symbol, player_id in actors:
            cluster_sizes[player_id] = len(actors)
        carrier_here = any(player_id == selected_id for _team, _symbol, player_id in actors)
        highlighted_here = any(player_id == highlighted_id
                               for _team, _symbol, player_id in actors)
        grid[row][col] = ("@" if carrier_here else "!" if highlighted_here
                          else actors[0][1] if len(actors) == 1 else "+")
    if ball is not None:
        cell = _pitch_map_cell(ball, pitch, width, height, bounds)
        if cell is not None:
            col, row = cell
        else:
            col = row = -1
        if cell is not None and not (selected_id and any(player_id == selected_id
                                                         for _team, _symbol, player_id
                                                         in occupied.get((row, col), ()))):
            grid[row][col] = "*"
    for row, chars in enumerate(grid):
        ui.draw_text(win, area.x, area.y + row, "".join(chars), area.width,
                     _pair(1 if row == mid_y else 6))
    return cluster_sizes


def _draw_match_setup(win, body: ui.Rect, career: dict[str, Any], app: dict[str, Any]) -> None:
    setup = app.get("match_setup", {})
    fixture = current_fixture(career)
    if not fixture or not setup:
        ui.draw_text(win, body.x, body.y, "MATCHDAY SETUP UNAVAILABLE", body.width,
                     _pair(4, bold=True))
        ui.draw_text(win, body.x, body.y + 2, app.get("message", "Fixture data is missing."),
                     body.width, _pair(2))
        return
    home_id, away_id = fixture
    home_name, away_name = club_by_id(home_id)["name"], club_by_id(away_id)["name"]
    ui.draw_text(win, body.x, body.y, f"MATCHDAY · {home_name} v {away_name}",
                 body.width, _pair(1, bold=True))
    ui.draw_text(win, body.x, body.y + 1,
                 f"Round {career['round'] + 1} · 105×68m · PLAN "
                 f"{dict(MATCHDAY_PROFILE_STYLES)[setup['style_id']]} · attacks →",
                 body.width, _pair(2))
    # Erase the old home-table row explicitly before drawing the pitch. This
    # row was exposed when curses retained a previous sparse-frame cell.
    ui.draw_text(win, body.x, body.y + 2, " " * body.width, body.width, _pair(6))
    team_id = setup["team_id"]
    user_positions = legal_formation_positions(team_id, setup["positions"])
    players: list[tuple[str, Position2D, str]] = []
    for slot, player_id in zip(formation_slots(setup["shape"]), setup["lineup_ids"]):
        world_positions = _pitch_world_positions({slot: user_positions[slot]}, team_id)
        players.append((team_id, world_positions[slot], player_id))
    opponent_id = away_id if setup["club_id"] == home_id else home_id
    opponent_team = "away" if team_id == "home" else "home"
    opponent_shape = str(career["clubs"][opponent_id].get("spatial_formation_v1", {}).get(
        "shape", career["clubs"][opponent_id].get("tactics", {}).get("in_shape", "4-3-3")))
    opponent_lineup = _matchday_lineup(career, opponent_id, opponent_shape)
    opponent_positions, _ = _draft_formation(
        career, opponent_id, opponent_team, opponent_shape, opponent_lineup)
    world_opponent = _pitch_world_positions(opponent_positions, opponent_team)
    for slot, player_id in zip(formation_slots(opponent_shape), opponent_lineup):
        players.append((opponent_team, world_opponent[slot], player_id))
    pitch_height = min(19, max(5, body.height - 7))
    target_pitch_width = max(17, (pitch_height - 2) * 3 + 2)
    side_min_width = min(33, max(0, body.width - 18))
    pitch_width = min(target_pitch_width,
                      max(17, body.width - side_min_width - 1))
    pitch_area = ui.Rect(body.x, body.y + 3, pitch_width, pitch_height)
    side_area = ui.Rect(body.x + pitch_width + 2, body.y + 3,
                        max(0, body.width - pitch_width - 2), pitch_height)
    selected = int(clamp(setup.get("selected_slot", 0), 0, 10))
    _draw_pitch_map(win, pitch_area, Pitch(), players,
                    selected_id=setup["lineup_ids"][selected])
    player = career["players"][setup["lineup_ids"][selected]]
    selected_slot = formation_slots(setup["shape"])[selected]
    assigned_role = SLOT_ROLES[selected_slot].value.replace("_", " ")
    selected_position = user_positions[selected_slot]
    rows = (
        f"SHAPE · YOU {setup['shape']} · OPP {opponent_shape}",
        f"SELECTED @{selected + 1}/11 · {player['name']} · {assigned_role}",
        f"SLOT {selected_slot} · natural {player['position']} · "
        f"local x/y {selected_position.x_m:.1f}/{selected_position.y_m:.1f}m",
        "w Y-2m · s Y+2m · a X-2m · d X+2m",
    )
    for offset, text in enumerate(rows):
        if offset >= side_area.height:
            break
        ui.draw_text(win, side_area.x, side_area.y + offset, text,
                     side_area.width, _pair(1 if offset in (0, 1) else 2,
                                            bold=offset in (0, 1)))
    if side_area.height >= len(rows) + 11:
        home_symbols = SPATIAL_HOME_MARKERS
        for index, (slot, player_id) in enumerate(zip(
                formation_slots(setup["shape"]), setup["lineup_ids"])):
            role = _spatial_role_code(SLOT_ROLES[slot].value)
            name = ui.clip(career["players"][player_id]["name"],
                           max(0, side_area.width - len(role) - 5))
            ui.draw_text(win, side_area.x, side_area.y + len(rows) + index,
                         f"{home_symbols[index]} {role} · {name}",
                         side_area.width,
                         _pair(3 if index == selected else 6,
                               bold=index == selected))


def _match_clock(tick: int | None, tick_ms: int) -> str:
    total_ms = max(0, (tick or 0) * tick_ms)
    minute, remainder_ms = divmod(total_ms, 60_000)
    second, subsecond_ms = divmod(remainder_ms, 1_000)
    return f"{minute:02d}:{second:02d}.{subsecond_ms // 100}"


@dataclass
class _MatchFeedItem:
    """A display-only event row; source events stay unchanged in MatchState."""

    source: object
    repeat_count: int = 1
    through_tick: int | None = None

    @property
    def kind(self) -> str:
        return self.source.kind

    @property
    def match_tick(self) -> int | None:
        return self.source.match_tick

    @property
    def payload(self) -> dict[str, Any]:
        return self.source.payload


def _spatial_event_line(event, career: dict[str, Any], tick_ms: int) -> str:
    tick = event.match_tick or 0
    timestamp = _match_clock(tick, tick_ms)
    repeat_count = getattr(event, "repeat_count", 1)
    if repeat_count > 1:
        end_time = _match_clock(getattr(event, "through_tick", tick), tick_ms)
        timestamp = f"{timestamp}–{end_time}"
    payload = event.payload
    actor_id = payload.get("actor_id")
    actor = _player_name(career, actor_id) if actor_id else ""
    kind = event.kind.replace("_", " ").upper()
    if repeat_count > 1:
        kind += f" ×{repeat_count}"
    if event.kind == "goal":
        own_goal_id = payload.get("own_goal_player_id")
        if own_goal_id:
            return f"{timestamp} OWN GOAL · {_player_name(career, own_goal_id)}"
        assist_id = payload.get("assist_player_id")
        detail = f"GOAL · {actor}"
        if assist_id:
            detail += f" (assist { _player_name(career, assist_id) })"
        return f"{timestamp} {detail}"
    receiver_id = payload.get("receiver_id") or payload.get("intended_receiver_id")
    if receiver_id and event.kind in ("pass", "pass_complete", "pass_intercepted"):
        actor += f" → {_player_name(career, receiver_id)}"
    if event.kind == "restart_awarded":
        kind = str(payload.get("kind", "restart")).replace("_", " ").upper()
    return f"{timestamp} {kind}{' · ' + actor if actor else ''}"


def _spatial_sidebar_event_line(event, career: dict[str, Any], tick_ms: int,
                                width: int) -> str:
    """Keep a compact live-feed label and its actor visible in narrow panels."""
    tick = event.match_tick or 0
    timestamp = _match_clock(tick, tick_ms)
    labels = {
        "goal": "GOAL", "pass": "PASS", "pass_complete": "PASS",
        "pass_intercepted": "INTERCEPT", "shot": "SHOT", "save": "SAVE",
        "deflection": "DEFLECT", "rebound": "REBOUND",
        "possession_controlled": "CONTROL", "possession_regained": "REGAIN",
        "restart_awarded": "AWARD", "restart_taken": "TAKE",
        "offside": "OFFSIDE", "foul": "FOUL", "red_card": "RED",
        "yellow_card": "YELLOW", "substitution": "SUB",
    }
    label = labels.get(event.kind, event.kind.replace("_", " ").upper())
    repeat_count = getattr(event, "repeat_count", 1)
    if repeat_count > 1:
        end_time = _match_clock(getattr(event, "through_tick", tick), tick_ms)
        timestamp = f"{timestamp}–{end_time}"
        label += f" ×{repeat_count}"
    payload = event.payload
    actor_id = (payload.get("own_goal_player_id") if event.kind == "goal"
                else payload.get("actor_id"))
    actor = _player_name(career, actor_id) if actor_id else ""
    receiver_id = payload.get("receiver_id") or payload.get("intended_receiver_id")
    if receiver_id and event.kind in ("pass", "pass_complete", "pass_intercepted"):
        actor += f"→{_player_name(career, receiver_id)}"
    prefix = f"{timestamp} {label}"
    if actor:
        prefix += " · "
        return prefix + ui.clip(actor, max(0, width - len(prefix)))
    return ui.clip(prefix, width)


def _key_match_events(events):
    """Compact detail rows and sustained actions without mutating the event ledger."""
    visible = []
    sustained: dict[tuple[str, str], _MatchFeedItem] = {}
    for index, event in enumerate(events):
        if event.kind == "move":
            continue
        if event.kind == "ball_contact" and index + 1 < len(events):
            following = events[index + 1]
            actor = event.payload.get("actor_id")
            next_actor = following.payload.get("actor_id")
            if (following.kind in ("possession_controlled", "possession_regained")
                    and following.match_tick == event.match_tick
                    and actor is not None and actor == next_actor):
                continue
        actor_id = event.payload.get("actor_id")
        if event.kind in ("press", "carry") and actor_id is not None \
                and event.match_tick is not None:
            key = (event.kind, str(actor_id))
            previous = sustained.get(key)
            if (len(sustained) == 1 and previous is not None
                    and previous.through_tick is not None
                    and 0 <= event.match_tick - previous.through_tick <= 1):
                previous.repeat_count += 1
                previous.through_tick = event.match_tick
                continue
            # Only combine adjacent visible actions. A different actor or
            # action ends the run so summary rows cannot overlap in time.
            sustained.clear()
            item = _MatchFeedItem(event, through_tick=event.match_tick)
            sustained[key] = item
            visible.append(item)
        else:
            # Goals, passes, control changes, fouls, and other state changes
            # split a sustained-action run so the grouped row cannot span a
            # meaningful event in the chronological feed.
            sustained.clear()
            visible.append(_MatchFeedItem(event))
    return visible


def _draw_spatial_chronology(win, area: ui.Rect, events, career: dict[str, Any],
                             tick_ms: int, app: dict[str, Any]) -> None:
    show_movement = bool(app.get("show_movement_events", False))
    visible_events = list(events) if show_movement else _key_match_events(events)
    selected = int(clamp(app.get("event_index", len(visible_events) - 1), 0,
                         max(0, len(visible_events) - 1)))
    count = f"{selected + 1}/{len(visible_events)}" if visible_events else "0/0"
    mode = "ALL" if show_movement else "KEY"
    movement_note = ("M key" if show_movement else
                     f"M all · {len(events) - len(visible_events)} detail rows hidden")
    ui.draw_text(win, area.x, area.y,
                 f"CHRONOLOGY · {mode} {count} · {movement_note}",
                 area.width, _pair(1, bold=True))
    rows = max(0, area.height - 1)
    begin = max(0, min(selected - rows + 1, len(visible_events) - rows))
    for offset, event in enumerate(visible_events[begin:begin + rows]):
        line = _spatial_event_line(event, career, tick_ms)
        ui.draw_text(win, area.x, area.y + offset + 1, line, area.width,
                     _pair(1 if event.kind in ("goal", "red_card") else 6,
                           bold=event.kind == "goal"))
    if not visible_events and rows:
        ui.draw_text(win, area.x, area.y + 1,
                     "No key event yet · M shows all player movement.",
                     area.width, _pair(6))


def _spatial_player_statistics(match) -> dict[str, dict[str, int]]:
    """Project career-facing totals from the authoritative match events."""
    totals: dict[str, dict[str, int]] = {}

    def credit(player_id: object, key: str) -> None:
        if player_id is None:
            return
        player_key = str(player_id)
        values = totals.setdefault(player_key, {})
        values[key] = values.get(key, 0) + 1

    team_by_player: dict[str, str] = {}
    for team_id, sheet in (("home", match.input_snapshot.home_sheet),
                           ("away", match.input_snapshot.away_sheet)):
        for item in sheet.starters:
            team_by_player[str(item.profile.player_id)] = team_id
        for item in sheet.substitutes:
            team_by_player[str(item.player_id)] = team_id
    passes: dict[str, object] = {}
    for event in match.events:
        payload = event.payload
        actor_id = payload.get("actor_id")
        if event.kind == "pass":
            passes[str(event.event_id)] = actor_id
            credit(actor_id, "pass_attempts")
        elif event.kind in ("possession_controlled", "possession_regained"):
            passer = passes.get(str(event.parent_event_id))
            if (passer is not None
                    and team_by_player.get(str(passer)) == team_by_player.get(str(actor_id))):
                credit(passer, "passes_completed")
        elif event.kind == "shot":
            credit(actor_id, "shots")
        elif event.kind == "goal":
            credit(actor_id, "goals")
            credit(payload.get("assist_player_id"), "assists")
    return totals


def _spatial_player_inspector(match, career: dict[str, Any], player_id: str) -> str:
    """Summarize a selected player's live position, events and match output."""
    state = next((state for key, state in match.play.players.items()
                  if str(key) == player_id), None)
    if state is None:
        return "Selected player is no longer active."
    totals = _spatial_player_statistics(match).get(player_id, {})
    last_event = next((event for event in reversed(match.events)
                       if event.kind != "move" and player_id in {
                           str(event.payload.get(key))
                           for key in ("actor_id", "receiver_id", "intended_receiver_id",
                                       "target_id", "goalkeeper_id", "own_goal_player_id",
                                       "assist_player_id")
                           if event.payload.get(key) is not None
                       }), None)
    if last_event is None:
        last_action = "LAST —"
    else:
        tick_ms = match.rules.tick_duration_ms
        total_seconds = (last_event.match_tick or 0) * tick_ms // 1_000
        label = {"possession_controlled": "CONTROL", "possession_regained": "REGAIN",
                 "pass_complete": "PASS", "pass_intercepted": "INTERCEPT",
                 "restart_awarded": "RESTART"}.get(
                     last_event.kind, last_event.kind.replace("_", " ").upper())
        last_action = f"LAST {label} {total_seconds // 60:02d}:{total_seconds % 60:02d}"
    symbol = _spatial_player_symbols(match).get(player_id, "?")
    name = ui.clip(state.profile.display_name, 12)
    position = state.motion.position
    role = _spatial_role_code(state.profile.primary_role.value)
    return (f"SEL {symbol} {name} {role} x{position.x_m:.1f}/y{position.y_m:.1f}m "
            f"G{totals.get('goals', 0)} A{totals.get('assists', 0)} "
            f"S{totals.get('shots', 0)} · {last_action}")


def _draw_spatial_stats(win, area: ui.Rect, match, career: dict[str, Any],
                        team_names: dict[str, str], app: dict[str, Any]) -> None:
    visible_rows = max(0, area.height - 2)
    scroll = max(0, int(app.get("spatial_roster_scroll", 0)))
    statistics = _spatial_player_statistics(match)
    for index, team_id in enumerate(("home", "away")):
        width = area.width // 2 - 1 if index == 0 else area.width - area.width // 2 - 1
        x = area.x if index == 0 else area.x + area.width // 2 + 1
        roster = match.teams[team_id]
        ids = [player_id for player_id, state in match.play.players.items()
               if state.team_id == team_id]
        ids.extend(player_id for player_id in roster.sent_off_ids if player_id not in ids)
        ids.extend(player_id for player_id in roster.substituted_off_ids if player_id not in ids)
        ids.extend(profile.player_id for profile in roster.substitutes if profile.player_id not in ids)
        start = min(scroll, max(0, len(ids) - visible_rows))
        end = min(len(ids), start + visible_rows)
        ui.draw_text(win, x, area.y + 1,
                     f"{team_id.upper()} · {start + 1}-{end}/{len(ids)}",
                     _pair(1, bold=True))
        for offset, player_id in enumerate(ids[start:end], start=1):
            values = statistics.get(str(player_id), {})
            line = (f"{_player_name(career, player_id)[:16]:16} "
                    f"{values.get('goals', 0):>2} {values.get('assists', 0):>2} "
                    f"{values.get('shots', 0):>2} {values.get('pass_attempts', 0):>2} "
                    f"{values.get('passes_completed', 0):>2}")
            ui.draw_text(win, x, area.y + offset + 1, line, width,
                         _pair(3 if values.get("goals", 0) else 6))
    ui.draw_text(win, area.x, area.y,
                 "G goals · A assists · S shots · PA/PC pass attempts/completed",
                 area.width, _pair(2))


def _spatial_player_symbols(match) -> dict[str, str]:
    symbols = {"home": SPATIAL_HOME_MARKERS,
               "away": "abcdefghijklmnopqrstuvwxyz"}
    output: dict[str, str] = {}
    for team_id, sheet in (("home", match.input_snapshot.home_sheet),
                           ("away", match.input_snapshot.away_sheet)):
        ids = ([item.profile.player_id for item in sheet.starters]
               + [item.player_id for item in sheet.substitutes])
        output.update((str(player_id), symbols[team_id][index % len(symbols[team_id])])
                      for index, player_id in enumerate(ids))
    return output


def _spatial_role_code(role: str) -> str:
    return {
        "goalkeeper": "GK", "center_back": "CB", "fullback": "FB",
        "defensive_midfielder": "DM", "central_midfielder": "CM",
        "wide_forward": "WF", "striker": "ST",
    }.get(role, role.upper()[:2])


def _draw_spatial_players(win, area: ui.Rect, match, career: dict[str, Any],
                          team_names: dict[str, str], app: dict[str, Any]) -> None:
    visible_rows = max(0, area.height - 1)
    scroll = max(0, int(app.get("spatial_roster_scroll", 0)))
    for index, team_id in enumerate(("home", "away")):
        width = area.width // 2 - 1 if index == 0 else area.width - area.width // 2 - 1
        x = area.x if index == 0 else area.x + area.width // 2 + 1
        title = team_names[team_id]
        roster = match.teams[team_id]
        active = [player_id for player_id, state in match.play.players.items()
                  if state.team_id == team_id]
        benched = [profile.player_id for profile in roster.substitutes
                   if profile.player_id not in active]
        withdrawn = [player_id for player_id in roster.substituted_off_ids
                     if player_id not in active and player_id not in benched]
        dismissed = [player_id for player_id in roster.sent_off_ids
                     if player_id not in active and player_id not in benched
                     and player_id not in withdrawn]
        ids = active + benched + withdrawn + dismissed
        start = min(scroll, max(0, len(ids) - visible_rows))
        end = min(len(ids), start + visible_rows)
        ui.draw_text(win, x, area.y,
                     f"{team_id.upper()} · {title} · {start + 1}-{end}/{len(ids)}",
                     width, _pair(1, bold=True))
        sheet = (match.input_snapshot.home_sheet if team_id == "home"
                 else match.input_snapshot.away_sheet)
        sheet_ids = ([item.profile.player_id for item in sheet.starters]
                     + [item.player_id for item in sheet.substitutes])
        profile_by_id = {item.profile.player_id: item.profile for item in sheet.starters}
        profile_by_id.update({item.player_id: item for item in sheet.substitutes})
        symbols = (SPATIAL_HOME_MARKERS if team_id == "home"
                   else "abcdefghijklmnopqrstuvwxyz")
        key_by_id = {player_id: symbols[index % len(symbols)]
                     for index, player_id in enumerate(sheet_ids)}
        for offset, player_id in enumerate(ids[start:end], start=1):
            marker = "@" if match.play.possession_id == player_id else key_by_id.get(player_id, "?")
            state = match.play.players.get(player_id)
            label = ("ON" if state else "SENT OFF" if player_id in dismissed else
                     "OFF" if player_id in withdrawn else "BENCH")
            profile = state.profile if state else profile_by_id.get(player_id)
            role = profile.primary_role.value if profile else "SUB"
            role_code = _spatial_role_code(role)
            line = f"{marker} {_player_name(career, player_id)} · {role_code} · {label}"
            ui.draw_text(win, x, area.y + offset, line, width,
                         _pair(3 if marker == "@" else 6))


def _draw_spatial_match(win, body: ui.Rect, career: dict[str, Any], app: dict[str, Any]) -> None:
    try:
        adapter = app.get("_save_data", {}).get("_career_adapter_state")
        if not isinstance(adapter, VersionedCareerSave):
            raise ValueError("versioned career match checkpoint is missing")
        session = resume_spatial_career_match(adapter)
    except (ValueError, TypeError) as exc:
        ui.draw_text(win, body.x, body.y, "SPATIAL MATCH CHECKPOINT ERROR", body.width,
                     _pair(4, bold=True))
        ui.draw_text(win, body.x, body.y + 2, str(exc), body.width, _pair(2))
        return
    match = session.match
    app["spatial_match_phase"] = match.phase
    app["spatial_keeper_replacement"] = match.keeper_replacement_team_id
    app["spatial_keeper_user_required"] = (
        match.keeper_replacement_team_id == _spatial_user_team(session, career)
        if match.keeper_replacement_team_id is not None else False
    )
    binding = session.binding
    home_id, away_id = str(binding.home_club_id), str(binding.away_club_id)
    clock_minute, remainder_ms = divmod(
        match.play.clock.tick * match.rules.tick_duration_ms, 60_000)
    clock_second = remainder_ms // 1_000
    period = {
        MatchPeriod.FIRST_HALF: "1H",
        MatchPeriod.SECOND_HALF: "2H",
        MatchPeriod.EXTRA_TIME_FIRST: "ET1",
        MatchPeriod.EXTRA_TIME_SECOND: "ET2",
    }.get(match.period, "FT")
    score = f"{club_by_id(home_id)['name']} {match.home_score}–{match.away_score} {club_by_id(away_id)['name']}"
    phase_text = ("FULL TIME" if match.phase is MatchPhase.FINISHED else
                  f"{period} {clock_minute:02d}:{clock_second:02d} · "
                  f"{match.phase.value.replace('_', ' ')}")
    if match.phase is MatchPhase.ABANDONED:
        phase_text = f"MATCH ABANDONED · {match.finished_reason or 'competition stopped'}"
    elif match.keeper_replacement_team_id is not None:
        phase_text = f"{period} {clock_minute:02d}' · REQUIRED GOALKEEPER CHANGE"
    restart = match.restart
    if restart is not None:
        phase_text += f" · {restart.kind.value.replace('_', ' ')} to {restart.team_id}"
    if match.phase is not MatchPhase.FINISHED:
        phase_text += (f" · WATCH ×{app.get('spatial_watch_ticks', 25)} ticks/update"
                       if app.get("spatial_watching") else " · PAUSED")
    ui.draw_text(win, body.x, body.y, score, body.width, _pair(1, bold=True))
    ui.draw_text(win, body.x, body.y + 1, f"{phase_text} · {len(match.events)} events",
                 body.width, _pair(2))
    events = list(match.events)
    view = app.get("match_view", "live")
    if view != "pitch":
        app["spatial_pitch_bounds"] = None
    view_labels = {"live": "LIVE", "pitch": "PITCH", "events": "EVENTS",
                   "stats": "STATS", "players": "PLAYERS"}
    view_strip = "VIEWS · " + "  ".join(
        f"[{label}]" if key == view else label for key, label in view_labels.items()
    ) + " · Tab cycles"
    ui.draw_text(win, body.x, body.y + 2, view_strip, body.width, _pair(3, bold=True))
    runtime_state = career.get("spatial_matchday_runtime_v1", {})
    queued = (runtime_state.get("queued_substitution")
              if isinstance(runtime_state, dict) else None)
    queued = queued if isinstance(queued, dict) else None
    if queued:
        queued_text = (f"CHANGE QUEUED · {_player_name(career, queued.get('incoming_id'))} for "
                       f"{_player_name(career, queued.get('outgoing_id'))} · next stoppage")
        ui.draw_text(win, body.x, body.y + 3, queued_text,
                     body.width, _pair(3, bold=True))
    content_y = body.y + (4 if queued else 3)
    content_area = ui.Rect(body.x, content_y, body.width,
                           max(1, body.bottom - content_y))
    if view == "events":
        _draw_spatial_chronology(win, content_area, events, career,
                                 match.rules.tick_duration_ms, app)
    elif view == "stats":
        _draw_spatial_stats(win, content_area, match, career,
                            {"home": club_by_id(home_id)["name"],
                             "away": club_by_id(away_id)["name"]}, app)
    elif view == "players":
        _draw_spatial_players(win, content_area, match, career,
                              {"home": club_by_id(home_id)["name"],
                               "away": club_by_id(away_id)["name"]}, app)
    elif view == "pitch":
        symbols = _spatial_player_symbols(match)
        highlighted_id = next((player_id for player_id in match.play.players
                               if str(player_id) == str(app.get("spatial_selected_player_id", ""))),
                              None)
        focus_ball = bool(app.get("spatial_pitch_focus_ball"))
        camera_player_id = None if focus_ball else (
            str(highlighted_id) if highlighted_id is not None else None)
        pitch_height = max(6, content_area.height - 3)
        # Terminal cells are about twice as tall as wide; four map columns per
        # interior row keeps the 2:1 football pitch close to its real shape.
        side_min_width = min(24, max(0, content_area.width - 36))
        pitch_max_width = max(0, content_area.width - 1 - side_min_width)
        pitch_width = min(pitch_max_width,
                          max(35, (pitch_height - 2) * 4 + 2))
        side_width = max(0, content_area.width - pitch_width - 1)
        pitch_area = ui.Rect(content_area.x, content_area.y,
                             pitch_width, pitch_height)
        side_area = ui.Rect(content_area.x + pitch_width + 1, content_area.y,
                            side_width, pitch_height)
        app["spatial_pitch_viewport"] = (pitch_area.width, pitch_area.height)
        bounds = (_spatial_pitch_focus_bounds(
            match, camera_player_id,
            (pitch_area.width, pitch_area.height))
                  if app.get("spatial_pitch_zoom") else None)
        app["spatial_pitch_bounds"] = bounds
        players = [(state.team_id, state.motion.position, str(player_id))
                   for player_id, state in match.play.players.items()]
        cluster_sizes = _draw_pitch_map(
            win, pitch_area, match.play.pitch, players, match.play.ball.position,
            selected_id=str(match.play.possession_id) if match.play.possession_id else None,
            highlighted_id=str(highlighted_id) if highlighted_id else None,
            player_symbols=symbols,
            bounds=bounds,
        )
        home_arrow = "→" if match.play.attack_right_by_team["home"] else "←"
        away_arrow = "←" if home_arrow == "→" else "→"
        ball = (f"@ {_player_name(career, match.play.possession_id)[:12]}"
                if match.play.possession_id else
                f"{match.restart.kind.value.replace('_', ' ')} restart"
                if match.restart else "* free ball")
        if bounds is not None:
            focus_width = round(bounds[1] - bounds[0])
            focus_height = round(bounds[3] - bounds[2])
            focus_name = ("BALL" if focus_ball or highlighted_id is None else
                          _player_name(career, highlighted_id)[:12])
            ball_cell = _pitch_map_cell(
                match.play.ball.position, match.play.pitch, pitch_area.width,
                pitch_area.height, bounds)
            if ball_cell is None:
                ball_x = match.play.ball.position.x_m
                ball_y = match.play.ball.position.y_m
                direction = ("←" if ball_x < bounds[0] else "→" if ball_x > bounds[1] else "")
                direction += ("↑" if ball_y < bounds[2] else "↓" if ball_y > bounds[3] else "")
                ball_note = f"BALL OFF {direction}"
            else:
                ball_note = "BALL IN VIEW"
            focus_text = (f"FOCUS {focus_width}×{focus_height}m · {focus_name} · "
                          f"X≈{bounds[0]:.0f}–{bounds[1]:.0f} "
                          f"Y≈{bounds[2]:.0f}–{bounds[3]:.0f}m · "
                          f"{ball_note} · Z full")
        else:
            focus_text = (f"FULL PITCH {match.play.pitch.length_m:g}×"
                          f"{match.play.pitch.width_m:g}m · HOME {home_arrow} · "
                          f"AWAY {away_arrow} · {ball}")
            ball_note = f"BALL {ball}"
        ui.draw_text(win, content_area.x, content_area.bottom - 3, focus_text,
                     content_area.width, _pair(2))
        inspector = (_spatial_player_inspector(match, career, str(highlighted_id))
                     if highlighted_id else
                     "Select by marker key · [ ] next player (cluster first)")
        ui.draw_text(win, content_area.x, content_area.bottom - 2, inspector,
                     content_area.width, _pair(3))
        ui.draw_text(win, content_area.x, content_area.bottom - 1,
                     "@ carrier · * ball · ! select · + cluster · [ ] next · B camera · 5m",
                     content_area.width, _pair(2))
        if side_area.width > 0:
            if highlighted_id and highlighted_id in match.play.players:
                state = match.play.players[highlighted_id]
                symbol = symbols.get(str(highlighted_id), "?")
                selected_name = ui.clip(_player_name(career, highlighted_id), 14)
                role = _spatial_role_code(state.profile.primary_role.value)
                position = state.motion.position
                totals = _spatial_player_statistics(match).get(str(highlighted_id), {})
                last_action = inspector.partition(" · LAST ")[2] or "—"
                selection_rows = [
                    f"SEL {symbol} {selected_name} {role} "
                    f"X{position.x_m:.1f} Y{position.y_m:.1f}",
                    f"G{totals.get('goals', 0)} A{totals.get('assists', 0)} "
                    f"S{totals.get('shots', 0)} · LAST {last_action}",
                ]
            else:
                selection_rows = ["No player selected", "Use [ ] to cycle"]
            overview_rows = ([
                "PITCH · CLOSE · BALL" if focus_ball else
                "PITCH · CLOSE · PLAYER" if highlighted_id else "PITCH · CLOSE · BALL",
                f"FOCUS {focus_width}×{focus_height}m X{bounds[0]:.0f}–{bounds[1]:.0f}",
                f"Y{bounds[2]:.0f}–{bounds[3]:.0f}m · {ball_note}",
            ] if bounds is not None else [
                "PITCH · FULL",
                f"{match.play.pitch.length_m:g}×{match.play.pitch.width_m:g}m HOME {home_arrow}",
                f"AWAY {away_arrow} · {ball}",
            ])
            side_rows = [
                *overview_rows,
                *selection_rows,
                "@ carrier · * ball · ! selected",
                "Keys 1–9,0,A,C–Z / a–k select",
                "B ball/player · Z full/zoom",
                "LATEST EVENTS",
            ]
            for offset, line in enumerate(side_rows[:side_area.height]):
                ui.draw_text(win, side_area.x, side_area.y + offset, line,
                             side_area.width, _pair(1 if offset in (0, 8) else 2,
                                                    bold=offset in (0, 8)))
            key_events = _key_match_events(events)
            event_rows = max(0, side_area.height - len(side_rows))
            for offset, event in enumerate(key_events[-event_rows:] if event_rows else ()):
                line = _spatial_sidebar_event_line(
                    event, career, match.rules.tick_duration_ms, side_area.width)
                ui.draw_text(win, side_area.x, side_area.y + len(side_rows) + offset,
                             line, side_area.width,
                             _pair(1 if event.kind in ("goal", "red_card") else 6,
                                   bold=event.kind == "goal"))
            if event_rows and not key_events:
                ui.draw_text(win, side_area.x, side_area.y + len(side_rows),
                             "No key events yet", side_area.width, _pair(6))
    else:
        pitch_height = min(19, max(7, content_area.height))
        pitch_width = min(int(body.width * 0.62), body.width - 24,
                          max(35, (pitch_height - 2) * 3 + 2))
        side_width = body.width - pitch_width - 1
        pitch_area = ui.Rect(content_area.x, content_area.y, pitch_width, pitch_height)
        side_area = ui.Rect(content_area.x + pitch_width + 1, content_area.y,
                            side_width, pitch_height)
        app["spatial_pitch_viewport"] = (pitch_area.width, pitch_area.height)
        players = [(state.team_id, state.motion.position, str(player_id))
                   for player_id, state in match.play.players.items()]
        cluster_sizes = _draw_pitch_map(
            win, pitch_area, match.play.pitch, players, match.play.ball.position,
            selected_id=str(match.play.possession_id) if match.play.possession_id else None,
            highlighted_id=next((str(player_id) for player_id in match.play.players
                                 if str(player_id) == str(
                                     app.get("spatial_selected_player_id", ""))), None),
            player_symbols=_spatial_player_symbols(match),
        )
        carrier_id = match.play.possession_id
        carrier = ("@ " + _player_name(career, carrier_id) if carrier_id else
                   "kickoff spot" if match.restart and match.restart.kind is RestartKind.KICKOFF
                   else "restart ball" if match.restart else "* free ball")
        key_events = _key_match_events(events)
        selected_id = next((player_id for player_id in match.play.players
                            if str(player_id) == str(
                                app.get("spatial_selected_player_id", ""))), None)
        if selected_id is not None:
            selected_profile = match.play.players[selected_id].profile
            marker = "@" if selected_id == carrier_id else "!"
            cluster = cluster_sizes.get(str(selected_id), 1)
            selection = (f"Selected {marker} "
                         f"{_spatial_player_symbols(match).get(str(selected_id), '?')}: "
                         f"{selected_profile.display_name} · "
                         f"{selected_profile.primary_role.value.replace('_', ' ')}"
                         + (f" · {cluster} here" if cluster > 1 else ""))
        else:
            selection = "Keys 1-9,0,A,C-Z / a-k · [ ] next"
        home_arrow = "→" if match.play.attack_right_by_team["home"] else "←"
        away_arrow = "←" if home_arrow == "→" else "→"
        move_count = sum(event.kind == "move" for event in events)
        side_rows = [
            "LIVE BALL",
            f"Carrier: {carrier}",
            f"Flight: {match.play.ball.horizontal_speed_mps:.1f}m/s · "
            f"{match.play.ball.height_m:.1f}m high",
            f"Attack: HOME {home_arrow} / AWAY {away_arrow}",
            "@ carrier · * ball",
            "! inspect + cluster",
            selection,
            "LATEST KEY EVENTS",
        ]
        for offset, line in enumerate(side_rows):
            if offset < side_area.height:
                ui.draw_text(win, side_area.x, side_area.y + offset, line,
                             side_area.width, _pair(1 if offset in (0, 7) else 2,
                                                    bold=offset in (0, 7)))
        event_rows = max(0, side_area.height - len(side_rows))
        for offset, event in enumerate(key_events[-event_rows:] if event_rows else ()):
            line = _spatial_sidebar_event_line(
                event, career, match.rules.tick_duration_ms, side_area.width)
            ui.draw_text(win, side_area.x, side_area.y + len(side_rows) + offset,
                         line, side_area.width,
                         _pair(1 if event.kind in ("goal", "red_card") else 6,
                               bold=event.kind == "goal"))
        if move_count and event_rows and not key_events:
            ui.draw_text(win, side_area.x, side_area.y + len(side_rows),
                         f"{move_count} movements; no key event yet",
                         side_area.width, _pair(6))


def _draw_spatial_substitutions(win, body: ui.Rect,
                                career: dict[str, Any], app: dict[str, Any]) -> None:
    adapter = app.get("_save_data", {}).get("_career_adapter_state")
    if not isinstance(adapter, VersionedCareerSave) or adapter.spatial_match_json is None:
        ui.draw_text(win, body.x, body.y, "No active spatial match.", body.width, _pair(4))
        return
    session = resume_spatial_career_match(adapter)
    user_team = ("home" if str(session.binding.home_club_id) == career["club_id"] else "away")
    roster = session.match.teams[user_team]
    keeper_required = session.match.keeper_replacement_team_id == user_team
    active_ids = [player_id for player_id in roster.starting_ids
                  if player_id in session.match.play.players]
    active_ids.extend(sorted((player_id for player_id, state in session.match.play.players.items()
                              if state.team_id == user_team and player_id not in active_ids),
                             key=str))
    bench = [profile for profile in roster.eligible_bench()
             if not keeper_required or profile.primary_role.value == "goalkeeper"]
    out_index = int(clamp(app.get("spatial_sub_out_index", 0), 0,
                          max(0, len(active_ids) - 1)))
    in_index = int(clamp(app.get("spatial_sub_in_index", 0), 0,
                         max(0, len(bench) - 1)))
    outgoing = active_ids[out_index] if active_ids else None
    incoming = bench[in_index] if bench else None
    queued = career.get("spatial_matchday_runtime_v1", {}).get("queued_substitution")
    minute = int(session.match.play.clock.tick * session.match.rules.tick_duration_ms / 60_000)
    ui.draw_text(win, body.x, body.y,
                 f"CHANGES · {roster.substitutions_made}/{session.match.rules.substitutions_allowed} used · {minute}'",
                 body.width, _pair(1, bold=True))
    phase = session.match.phase.value.replace("_", " ")
    ui.draw_text(win, body.x, body.y + 1,
                 ("A goalkeeper must enter now; choose any active outfield player to leave."
                  if keeper_required else
                  f"Current phase: {phase}. In-play requests queue until an engine stoppage or interval."),
                 body.width, _pair(2))
    split_y = body.y + 3
    left_width = max(1, body.width // 2 - 1)
    footer_y = body.bottom - 1
    reserved_rows = 1 if queued and footer_y > split_y else 0
    first_row = split_y + 1
    visible_rows = max(0, body.bottom - first_row - reserved_rows)

    def visible_window(count: int, selected_index: int) -> tuple[int, int]:
        if not count or not visible_rows:
            return 0, 0
        start = max(0, min(selected_index, count - visible_rows))
        return start, min(count, start + visible_rows)

    active_start, active_end = visible_window(len(active_ids), out_index)
    bench_start, bench_end = visible_window(len(bench), in_index)
    active_range = (f" {active_start + 1}–{active_end}/{len(active_ids)}"
                    if len(active_ids) > visible_rows else "")
    bench_range = (f" {bench_start + 1}–{bench_end}/{len(bench)}"
                   if len(bench) > visible_rows else "")
    ui.draw_text(win, body.x, split_y, f"ON PITCH · OFF{active_range}",
                 left_width, _pair(1, bold=True))
    right_x = body.x + left_width + 1
    right_width = body.width - left_width - 1
    ui.draw_text(win, right_x, split_y, f"BENCH · ON{bench_range}",
                 right_width, _pair(1, bold=True))
    for row, index in enumerate(range(active_start, active_end), start=first_row):
        player_id = active_ids[index]
        marker = ">" if app.get("spatial_sub_focus", "out") == "out" and index == out_index else " "
        name = _player_name(career, player_id)
        profile = session.match.play.players[player_id].profile
        note = " · BALL" if session.match.play.possession_id == player_id else ""
        ui.draw_text(win, body.x, row,
                     f"{marker}{name} · {_spatial_role_code(profile.primary_role.value)}{note}",
                     left_width, _pair(3 if marker == ">" else 6))
    for row, index in enumerate(range(bench_start, bench_end), start=first_row):
        profile = bench[index]
        marker = ">" if app.get("spatial_sub_focus", "out") == "in" and index == in_index else " "
        ui.draw_text(win, right_x, row,
                     f"{marker}{profile.display_name} · {_spatial_role_code(profile.primary_role.value)}",
                     right_width, _pair(3 if marker == ">" else 6))
    if queued and footer_y > split_y:
        ui.draw_text(win, body.x, footer_y,
                     f"QUEUED · {_player_name(career, queued.get('incoming_id'))} for "
                     f"{_player_name(career, queued.get('outgoing_id'))} at next legal stoppage",
                     body.width, _pair(3, bold=True))


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


def _adapter_with_career(adapter: VersionedCareerSave,
                         career: dict[str, Any]) -> VersionedCareerSave:
    payload = adapter.legacy_save
    payload["career"] = copy.deepcopy(career)
    return replace(adapter, legacy_save_json=json.dumps(
        payload, ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(",", ":")))


def _adapter_with_spatial_checkpoint(adapter: VersionedCareerSave,
                                     session: CareerMatchSession,
                                     career: dict[str, Any]) -> VersionedCareerSave:
    return replace(_adapter_with_career(adapter, career),
                   spatial_match_json=session.to_json())


def _runtime_adapter(save_data: dict[str, Any], career: dict[str, Any]) -> VersionedCareerSave:
    adapter = save_data.get("_career_adapter_state")
    if isinstance(adapter, VersionedCareerSave):
        adapter = _adapter_with_career(adapter, career)
    else:
        adapter = migrate_v2_save({"version": 2, "career": career})
    save_data["_career_adapter_state"] = adapter
    return adapter


def _spatial_session(save_data: dict[str, Any]) -> CareerMatchSession | None:
    adapter = save_data.get("_career_adapter_state")
    if not isinstance(adapter, VersionedCareerSave) or adapter.spatial_match_json is None:
        return None
    return resume_spatial_career_match(adapter)


def _prepared_match_profiles(
    adapter: VersionedCareerSave, career: dict[str, Any], club_id: str,
) -> tuple[dict[str, Any], tuple[PlayerId, ...]]:
    preparation = load_preparation_state(adapter)
    if preparation is None or str(preparation.club_id) != club_id:
        return {}, ()
    registered = set(map(str, career["clubs"][club_id]["roster"]))
    prepared_ids = {str(profile.player_id) for profile in preparation.profiles}
    if registered != prepared_ids:
        raise ValueError("P09 preparation profiles do not match the selected club roster")
    profiles: dict[str, Any] = {}
    unavailable: list[PlayerId] = []
    for profile in preparation.profiles:
        player_id = profile.player_id
        profiles[str(player_id)] = prepared_profile(preparation, player_id)
        if selection_assessment(preparation, player_id).status is not SelectionStatus.SELECTABLE:
            unavailable.append(player_id)
    return profiles, tuple(unavailable)


def _matchday_lineup(career: dict[str, Any], club_id: str, shape: str,
                     unavailable: tuple[PlayerId, ...] = ()) -> list[str]:
    unavailable_ids = {str(player_id) for player_id in unavailable}
    candidates = list(lineup_for(career, club_id, shape))
    candidates.extend(best_lineup(career, club_id, shape))
    candidates.extend(career["clubs"][club_id]["roster"])
    selected: list[str] = []
    for player_id in candidates:
        if player_id in selected or player_id in unavailable_ids:
            continue
        player = career["players"].get(player_id)
        if player is None or not is_available(career, player):
            continue
        selected.append(player_id)
        if len(selected) == 11:
            break
    return selected


def _draft_formation(career: dict[str, Any], club_id: str, team_id: str,
                     shape: str, lineup_ids: list[str], *,
                     style_id: str | None = None) -> tuple[dict[str, Position2D], str]:
    slots = formation_slots(shape)
    defaults = default_formation_positions(shape)
    club = career["clubs"][club_id]
    saved = club.get("spatial_formation_v1")
    positions = dict(defaults)
    if (isinstance(saved, dict) and saved.get("schema_version") == 1
            and saved.get("shape") == shape and isinstance(saved.get("positions"), dict)):
        for slot, player_id in zip(slots, lineup_ids):
            raw = saved["positions"].get(player_id)
            if (isinstance(raw, (list, tuple)) and len(raw) == 2
                    and all(type(value) in (int, float) and math.isfinite(value)
                            for value in raw)):
                positions[slot] = Position2D(float(raw[0]), float(raw[1]))
    legacy_press = club.get("tactics", {}).get("press", "mid")
    default_style = "press" if legacy_press == "high" else "compact"
    if club_id == career["club_id"]:
        default_style = "possession"
    saved_style = saved.get("style_id") if isinstance(saved, dict) else None
    selected_style = style_id or saved_style or default_style
    if selected_style not in dict(MATCHDAY_PROFILE_STYLES):
        selected_style = default_style
    return legal_formation_positions(team_id, positions), str(selected_style)


def _save_spatial_formation(career: dict[str, Any], club_id: str, team_id: str,
                            shape: str, lineup_ids: list[str],
                            positions: dict[str, Position2D], style_id: str) -> None:
    slots = formation_slots(shape)
    legal = legal_formation_positions(team_id, positions)
    career["clubs"][club_id]["lineup"] = list(lineup_ids)
    career["clubs"][club_id].setdefault("tactics", {})["in_shape"] = shape
    career["clubs"][club_id]["spatial_formation_v1"] = {
        "schema_version": 1,
        "shape": shape,
        "positions": {
            player_id: [legal[slot].x_m, legal[slot].y_m]
            for slot, player_id in zip(slots, lineup_ids)
        },
        "slot_bindings": {
            slot: player_id for slot, player_id in zip(slots, lineup_ids)
        },
        "style_id": style_id,
    }


def _start_spatial_match(save_data: dict[str, Any], career: dict[str, Any],
                         app: dict[str, Any]) -> None:
    setup = app.get("match_setup")
    if not isinstance(setup, dict):
        app["message"] = "Matchday setup is missing. Press M from Home to prepare the fixture."
        return
    adapter = _runtime_adapter(save_data, career)
    fixture = current_fixture(career)
    if fixture is None:
        app["message"] = "No fixture remains this season."
        return
    home_id, away_id = fixture
    managed_id = career["club_id"]
    managed_team = "home" if managed_id == home_id else "away"
    opponent_id = away_id if managed_id == home_id else home_id
    user_shape = str(setup["shape"])
    user_lineup = list(setup["lineup_ids"])
    user_positions = dict(setup["positions"])
    user_style = str(setup["style_id"])
    opponent_team = "away" if managed_team == "home" else "home"
    opponent_club = career["clubs"][opponent_id]
    opponent_shape = str(opponent_club.get("spatial_formation_v1", {}).get(
        "shape", opponent_club.get("tactics", {}).get("in_shape", "4-3-3")))
    opponent_profiles, opponent_unavailable = _prepared_match_profiles(
        adapter, career, opponent_id)
    opponent_lineup = _matchday_lineup(
        career, opponent_id, opponent_shape, opponent_unavailable)
    opponent_positions, opponent_style = _draft_formation(
        career, opponent_id, opponent_team, opponent_shape, opponent_lineup)
    user_profiles, user_unavailable = _prepared_match_profiles(adapter, career, managed_id)
    eligible_user_lineup = _matchday_lineup(career, managed_id, user_shape, user_unavailable)
    if len(user_lineup) != 11 or set(user_lineup) != set(eligible_user_lineup):
        # Keep the user's selected XI if it remains legal. A changed preparation
        # state instead gets an explicit refreshed XI before kickoff.
        allowed = {pid for pid in _matchday_lineup(
            career, managed_id, user_shape, user_unavailable)}
        if len(user_lineup) != 11 or not set(user_lineup) <= allowed:
            user_lineup = eligible_user_lineup
            setup["lineup_ids"] = list(user_lineup)
            app["message"] = "Unavailable players were removed from the XI; review it and press Enter again."
            return
    if len(user_lineup) != 11 or len(opponent_lineup) != 11:
        app["message"] = "A full XI is not available under current injury and preparation status."
        return
    _save_spatial_formation(career, managed_id, managed_team, user_shape,
                            user_lineup, user_positions, user_style)
    _save_spatial_formation(career, opponent_id, opponent_team, opponent_shape,
                            opponent_lineup, opponent_positions, opponent_style)
    adapter = _adapter_with_career(adapter, career)
    home_profiles, home_unavailable = _prepared_match_profiles(adapter, career, home_id)
    away_profiles, away_unavailable = _prepared_match_profiles(adapter, career, away_id)
    try:
        home_sheet = build_team_sheet(
            career, home_id, "home", career["clubs"][home_id]["lineup"],
            shape=str(career["clubs"][home_id]["spatial_formation_v1"]["shape"]),
            prepared_profiles=home_profiles, unavailable_profiles=home_unavailable,
        )
        away_sheet = build_team_sheet(
            career, away_id, "away", career["clubs"][away_id]["lineup"],
            shape=str(career["clubs"][away_id]["spatial_formation_v1"]["shape"]),
            prepared_profiles=away_profiles, unavailable_profiles=away_unavailable,
        )
        adapter = start_spatial_career_match(
            adapter,
            home_sheet=home_sheet.sheet,
            away_sheet=away_sheet.sheet,
            seed=_match_seed(career, career["round"], home_id, away_id),
            rules=MATCHDAY_RULES,
            pitch=Pitch(),
            physics=BallPhysics(step_seconds=MATCHDAY_RULES.tick_duration_ms / 1000.0),
        )
    except (TypeError, ValueError) as exc:
        app["message"] = f"Match setup needs attention: {exc}"
        return
    save_data["_career_adapter_state"] = adapter
    career["spatial_matchday_runtime_v1"] = {
        "match_id": str(adapter.current_match_id),
        "distance_m": {
            str(player_id): 0.0 for club_id in (home_id, away_id)
            for player_id in career["clubs"][club_id]["roster"]
        },
        "queued_substitution": None,
    }
    session = resume_spatial_career_match(adapter)
    adapter = _adapter_with_career(adapter, career)
    save_data["_career_adapter_state"] = adapter
    app["_adapter"] = adapter
    app["spatial_tactical_runtimes"] = tactical_runtimes(session, career)
    app["spatial_watching"] = False
    app["spatial_watch_ticks"] = 25
    app["spatial_match_phase"] = session.match.phase
    app["spatial_keeper_replacement"] = session.match.keeper_replacement_team_id
    app["spatial_keeper_user_required"] = (
        session.match.keeper_replacement_team_id == _spatial_user_team(session, career)
        if session.match.keeper_replacement_team_id is not None else False
    )
    app["page"] = "spatial_match"
    app["match_view"] = "live"
    app["message"] = "Kickoff. The same spatial match can be watched, stepped or quick-simmed."


def _begin_spatial_setup(career: dict[str, Any], app: dict[str, Any],
                         save_data: dict[str, Any]) -> None:
    prepare_week(career)
    fixture = current_fixture(career)
    if fixture is None:
        app["message"] = "No fixture remains this season."
        return
    managed_id = career["club_id"]
    managed_team = "home" if managed_id == fixture[0] else "away"
    adapter = _runtime_adapter(save_data, career)
    app["_adapter"] = adapter
    try:
        prepared_profiles, unavailable = _prepared_match_profiles(adapter, career, managed_id)
        shape = str(career["clubs"][managed_id].get("spatial_formation_v1", {}).get(
            "shape", career["clubs"][managed_id]["tactics"].get("in_shape", "4-3-3")))
        lineup = _matchday_lineup(career, managed_id, shape, unavailable)
        if len(lineup) != 11:
            app["message"] = "Fewer than 11 players are selectable. Review injury and preparation status."
            return
        positions, style_id = _draft_formation(career, managed_id, managed_team,
                                                shape, lineup)
    except (KeyError, TypeError, ValueError) as exc:
        app["message"] = f"Match preparation needs attention: {exc}"
        return
    app["match_setup"] = {
        "team_id": managed_team,
        "club_id": managed_id,
        "shape": shape,
        "style_id": style_id,
        "lineup_ids": lineup,
        "positions": positions,
        "selected_slot": 0,
    }
    app["page"] = "match_setup"
    app["message"] = "Set your XI, shape and plan; placements become kickoff positions."


def _start_matchday(career: dict[str, Any], app: dict[str, Any],
                    save_data: dict[str, Any] | None = None) -> None:
    if career["season_complete"]:
        app["message"] = "The season is complete. Press Enter at Home to begin the next one."
        return
    if career.get("live_match"):
        app["page"] = "team_talk" if _needs_team_talk(career["live_match"]) else "match"
        app["message"] = "Resumed saved match · clock, players and event record restored."
        return
    save_data = save_data if save_data is not None else app.get("_save_data", {})
    adapter = (app.get("_adapter")
               or (save_data.get("_career_adapter_state")
                   if isinstance(save_data, dict) else None))
    if isinstance(adapter, VersionedCareerSave) and adapter.spatial_match_json is not None:
        app["page"] = "spatial_match"
        session = resume_spatial_career_match(adapter)
        app.setdefault("spatial_tactical_runtimes", tactical_runtimes(session, career))
        app["message"] = "Resumed spatial match · clock, players and event record restored."
        return
    if app.get("match_engine", "legacy") == "spatial":
        _begin_spatial_setup(career, app, save_data if isinstance(save_data, dict) else {})
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
    elif page == "spatial_report" and career:
        _draw_spatial_report(win, body, career, app)
    elif page == "team_talk" and career and career.get("live_match"):
        _draw_team_talk(win, body, career, app)
    elif page == "match_setup" and career:
        _draw_match_setup(win, body, career, app)
    elif page == "spatial_subs" and career:
        _draw_spatial_substitutions(win, body, career, app)
    elif page == "spatial_match" and career:
        _draw_spatial_match(win, body, career, app)
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


def _ensure_spatial_runtime_state(career: dict[str, Any],
                                  session: CareerMatchSession) -> dict[str, Any]:
    match_id = str(session.binding.match_id)
    state = career.get("spatial_matchday_runtime_v1")
    if not isinstance(state, dict) or state.get("match_id") != match_id:
        state = {
            "match_id": match_id,
            "distance_m": {
                str(player_id): 0.0 for club_id in (
                    str(session.binding.home_club_id), str(session.binding.away_club_id))
                for player_id in career["clubs"][club_id]["roster"]
            },
            "queued_substitution": None,
        }
        career["spatial_matchday_runtime_v1"] = state
    distances = state.get("distance_m")
    if not isinstance(distances, dict):
        state["distance_m"] = {}
    state.setdefault("queued_substitution", None)
    return state


def _spatial_user_team(session: CareerMatchSession, career: dict[str, Any]) -> str:
    return "home" if str(session.binding.home_club_id) == career["club_id"] else "away"


def _apply_queued_spatial_substitution(
    career: dict[str, Any], session: CareerMatchSession,
) -> tuple[str | None, bool]:
    runtime_state = _ensure_spatial_runtime_state(career, session)
    request = runtime_state.get("queued_substitution")
    if not isinstance(request, dict):
        return None, False
    match = session.match
    if match.phase not in (MatchPhase.RESTART_READY, MatchPhase.INTERVAL):
        return None, False
    team_id = str(request.get("team_id", ""))
    if team_id not in ("home", "away"):
        runtime_state["queued_substitution"] = None
        return "Queued change cancelled: its match side is invalid.", False
    tick = match.play.clock.tick
    window_id = f"sub-window:{team_id}:{match.period.value}:{tick}"
    roster = match.teams[team_id]
    if (match.keeper_replacement_team_id == team_id
            and len(roster.substitution_windows_used)
                >= match.rules.substitution_windows_allowed
            and roster.substitution_windows_used):
        # The rules permit a dismissed goalkeeper to be replaced in an
        # already-used window. Reusing its identity avoids making a forbidden
        # new window while the engine's required-keeper gate is active.
        window_id = roster.substitution_windows_used[-1]
    outgoing_id = PlayerId(str(request.get("outgoing_id", "")))
    incoming_id = PlayerId(str(request.get("incoming_id", "")))
    try:
        substitute(match, outgoing_id, incoming_id, window_id=window_id)
    except (TypeError, ValueError) as exc:
        runtime_state["queued_substitution"] = None
        return f"Queued change could not be applied: {exc}", False
    club_id = str(session.binding.home_club_id if team_id == "home"
                  else session.binding.away_club_id)
    lineup = career["clubs"][club_id].get("lineup", [])
    career["clubs"][club_id]["lineup"] = [
        str(incoming_id) if str(player_id) == str(outgoing_id) else str(player_id)
        for player_id in lineup
    ]
    runtime_state["distance_m"].setdefault(str(incoming_id), 0.0)
    runtime_state["queued_substitution"] = None
    return (f"Change completed at a legal stoppage: {_player_name(career, incoming_id)} "
            f"for {_player_name(career, outgoing_id)}."), True


def _record_spatial_distance(career: dict[str, Any], session: CareerMatchSession,
                             before: dict[PlayerId, tuple[Position2D, float]]) -> None:
    state = _ensure_spatial_runtime_state(career, session)
    distances = state["distance_m"]
    after = session.match.play.players
    step_seconds = session.match.rules.tick_duration_ms / 1000.0
    for player_id, (position, speed_limit) in before.items():
        current = after.get(player_id)
        if current is None:
            continue
        distance = math.hypot(current.motion.position.x_m - position.x_m,
                              current.motion.position.y_m - position.y_m)
        # Restarts can reposition a player instantly. Those reset placements
        # are not work performed and are excluded from the P09 exertion input.
        if distance > speed_limit * step_seconds + 0.02:
            continue
        distances[str(player_id)] = float(distances.get(str(player_id), 0.0)) + distance


def _queue_opponent_keeper_replacement(career: dict[str, Any],
                                      session: CareerMatchSession) -> bool:
    """Queue a visible, deterministic AI response to its dismissed keeper."""
    team_id = session.match.keeper_replacement_team_id
    if (team_id is None or team_id == _spatial_user_team(session, career)
            or session.match.phase not in (MatchPhase.RESTART_READY, MatchPhase.INTERVAL)):
        return False
    roster = session.match.teams[team_id]
    keepers = [profile for profile in roster.eligible_bench()
               if profile.primary_role.value == "goalkeeper"]
    outfield = [
        (player_id, state) for player_id, state in session.match.play.players.items()
        if state.team_id == team_id and state.profile.primary_role.value != "goalkeeper"
    ]
    if (not keepers or not outfield
            or roster.substitutions_made >= session.match.rules.substitutions_allowed
            or (len(roster.substitution_windows_used)
                >= session.match.rules.substitution_windows_allowed
                and not roster.substitution_windows_used)):
        return False
    outgoing_id, _outgoing = min(
        outfield,
        key=lambda pair: (
            int(career.get("players", {}).get(str(pair[0]), {}).get("overall", 50)),
            str(pair[0]),
        ),
    )
    runtime_state = _ensure_spatial_runtime_state(career, session)
    runtime_state["queued_substitution"] = {
        "team_id": team_id,
        "outgoing_id": str(outgoing_id),
        "incoming_id": str(keepers[0].player_id),
    }
    return True


def _advance_spatial_match(career: dict[str, Any], save_data: dict[str, Any],
                           app: dict[str, Any], transitions: int) -> int:
    if type(transitions) is not int or transitions <= 0:
        raise ValueError("spatial match advancement requires positive transitions")
    adapter = save_data.get("_career_adapter_state")
    if not isinstance(adapter, VersionedCareerSave) or adapter.spatial_match_json is None:
        raise ValueError("career has no active spatial match checkpoint")
    session = resume_spatial_career_match(adapter)
    _ensure_spatial_runtime_state(career, session)
    runtimes = app.get("spatial_tactical_runtimes")
    if not isinstance(runtimes, dict):
        runtimes = tactical_runtimes(session, career)
        app["spatial_tactical_runtimes"] = runtimes
    advanced = 0
    messages: list[str] = []
    for _ in range(transitions):
        if session.match.phase in (MatchPhase.FINISHED, MatchPhase.ABANDONED):
            break
        keeper_team = session.match.keeper_replacement_team_id
        if keeper_team is not None:
            runtime_state = _ensure_spatial_runtime_state(career, session)
            if runtime_state.get("queued_substitution") is not None:
                runtime_state["queued_substitution"] = None
                messages.append(
                    "An earlier queued change was canceled because the goalkeeper vacancy takes priority."
                )
            if keeper_team == _spatial_user_team(session, career):
                app["spatial_watching"] = False
                app["spatial_sub_focus"] = "in"
                app["spatial_sub_out_index"] = 0
                app["spatial_sub_in_index"] = 0
                app["page"] = "spatial_subs"
                messages.append("Match paused: select an eligible goalkeeper to continue.")
                break
            if not _queue_opponent_keeper_replacement(career, session):
                messages.append("Opponent goalkeeper replacement is waiting for a legal option.")
                break
            message, changed = _apply_queued_spatial_substitution(career, session)
            if changed:
                runtimes = tactical_runtimes(session, career)
                app["spatial_tactical_runtimes"] = runtimes
                messages.append(message or "Opponent completed its required goalkeeper change.")
            else:
                if message:
                    messages.append(f"Opponent goalkeeper change failed: {message}")
                break
        message, changed = _apply_queued_spatial_substitution(career, session)
        if message:
            messages.append(message)
        if changed:
            runtimes = tactical_runtimes(session, career)
            app["spatial_tactical_runtimes"] = runtimes
        before = {
            player_id: (state.motion.position, state.motion.limits.maximum_speed_mps)
            for player_id, state in session.match.play.players.items()
        }
        step_match(session.match, tactical_runtimes=runtimes)
        _record_spatial_distance(career, session, before)
        advanced += 1
    updated = _adapter_with_spatial_checkpoint(adapter, session, career)
    save_data["_career_adapter_state"] = updated
    app["_adapter"] = updated
    app["spatial_match_phase"] = session.match.phase
    app["spatial_keeper_replacement"] = session.match.keeper_replacement_team_id
    app["spatial_keeper_user_required"] = (
        session.match.keeper_replacement_team_id == _spatial_user_team(session, career)
        if session.match.keeper_replacement_team_id is not None else False
    )
    if (session.match.keeper_replacement_team_id is not None
            and session.match.keeper_replacement_team_id == _spatial_user_team(session, career)):
        app["spatial_watching"] = False
        app["spatial_sub_focus"] = "in"
        app["spatial_sub_out_index"] = 0
        app["spatial_sub_in_index"] = 0
        app["page"] = "spatial_subs"
        if not messages or "select an eligible goalkeeper" not in messages[-1]:
            messages.append("Match paused: select an eligible goalkeeper to continue.")
    if messages:
        app["message"] = messages[-1]
    elif session.match.phase is MatchPhase.FINISHED:
        app["spatial_watching"] = False
        app["message"] = "Full time. Review the chronology, then settle the spatial match and round."
    elif session.match.phase is MatchPhase.ABANDONED:
        app["spatial_watching"] = False
        app["message"] = (
            "Match abandoned. The league has no abandonment result policy, so the score "
            "and table were not settled; the saved chronology remains available."
        )
    elif session.match.keeper_replacement_team_id is not None:
        app["message"] = "The opponent needs an eligible goalkeeper at a legal stoppage."
    elif advanced:
        app["message"] = f"Advanced {advanced} fixed simulation tick{'s' if advanced != 1 else ''}."
    return advanced


def _queue_spatial_substitution(career: dict[str, Any], save_data: dict[str, Any],
                                app: dict[str, Any], outgoing_id: str,
                                incoming_id: str) -> None:
    adapter = save_data.get("_career_adapter_state")
    if not isinstance(adapter, VersionedCareerSave) or adapter.spatial_match_json is None:
        app["message"] = "No active spatial match is available for changes."
        return
    session = resume_spatial_career_match(adapter)
    team_id = _spatial_user_team(session, career)
    state = _ensure_spatial_runtime_state(career, session)
    if state.get("queued_substitution") is not None:
        app["message"] = "A change is already queued; let it apply or cancel it first."
        return
    if session.match.play.possession_id == PlayerId(outgoing_id):
        app["message"] = "Choose a different player: the active ball carrier cannot leave at this stoppage."
        return
    state["queued_substitution"] = {
        "team_id": team_id,
        "outgoing_id": outgoing_id,
        "incoming_id": incoming_id,
    }
    message, changed = _apply_queued_spatial_substitution(career, session)
    if changed:
        updated = _adapter_with_spatial_checkpoint(adapter, session, career)
        save_data["_career_adapter_state"] = updated
        app["_adapter"] = updated
        app["spatial_tactical_runtimes"] = tactical_runtimes(session, career)
    app["message"] = message or "Change queued for the next legal stoppage or interval."


def _spatial_exertion_inputs(adapter: VersionedCareerSave,
                             career: dict[str, Any],
                             session: CareerMatchSession) -> dict[PlayerId, float] | None:
    preparation = load_preparation_state(adapter)
    if preparation is None:
        return None
    runtime_state = _ensure_spatial_runtime_state(career, session)
    distance_by_player = runtime_state["distance_m"]
    profiles = {}
    snapshot = session.match.input_snapshot
    for sheet in (snapshot.home_sheet, snapshot.away_sheet):
        for player in sheet.starters:
            profiles[player.profile.player_id] = player.profile
        for player in sheet.substitutes:
            profiles[player.player_id] = player
    output: dict[PlayerId, float] = {}
    for prepared in preparation.profiles:
        player_id = prepared.player_id
        minutes = session.match.minutes_played.get(player_id, 0.0)
        if minutes <= 0:
            output[player_id] = 0.0
            continue
        match_profile = profiles.get(player_id)
        if match_profile is None:
            raise ValueError(f"P09 workload is missing the match profile for {player_id}")
        seconds = float(minutes) * 60.0
        distance_limit = limits_from_profile(match_profile).maximum_speed_mps * seconds
        if distance_limit <= 0:
            raise ValueError(f"P09 workload has no positive movement capacity for {player_id}")
        # Exertion is the measured simulated distance divided by that player's
        # profile-limited maximum distance over their actual playing time.
        output[player_id] = min(1.0, float(distance_by_player.get(str(player_id), 0.0))
                                / distance_limit)
    return output


def _finish_spatial_round(career: dict[str, Any], spatial_match_id: str) -> int:
    round_index = int(career["round"])
    spatial_result = next((row for row in reversed(career.get("results", []))
                           if isinstance(row, dict) and row.get("id") == spatial_match_id), None)
    if not isinstance(spatial_result, dict):
        raise ValueError("settled spatial result is missing from career history")
    resolved = 1
    for division in content.DIVISIONS:
        for home, away in fixtures_for(career, division["id"])[round_index]:
            if {home, away} == {spatial_result["home"], spatial_result["away"]}:
                continue
            already = any(isinstance(item, dict)
                          and item.get("season") == career["season"]
                          and item.get("round") == round_index + 1
                          and (item.get("home"), item.get("away")) == (home, away)
                          for item in career.get("results", []))
            if already:
                continue
            other = simulate_match(
                career, home, away,
                _match_seed(career, round_index, home, away), round_index,
            )
            apply_match_result(career, other)
            resolved += 1
    career["round"] = round_index + 1
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


def _settle_spatial_match(career: dict[str, Any], save_data: dict[str, Any],
                          app: dict[str, Any]) -> None:
    adapter = save_data.get("_career_adapter_state")
    if not isinstance(adapter, VersionedCareerSave) or adapter.spatial_match_json is None:
        app["message"] = "No spatial match is awaiting settlement."
        return
    session = resume_spatial_career_match(adapter)
    if session.match.phase is not MatchPhase.FINISHED:
        app["message"] = "Finish the match in the spatial engine before settling the result."
        return
    try:
        exertion = _spatial_exertion_inputs(adapter, career, session)
        updated, settled = settle_spatial_career_match(
            adapter, session,
            exertion_by_player=exertion if exertion is not None else None,
        )
        if not settled:
            app["message"] = "This spatial match was already settled."
            return
        match_id = str(session.binding.match_id)
        career_snapshot = updated.legacy_save["career"]
        career.clear()
        career.update(career_snapshot)
        career.pop("spatial_matchday_runtime_v1", None)
        count = _finish_spatial_round(career, match_id)
        updated_payload = updated.legacy_save
        updated_payload["career"] = copy.deepcopy(career)
        updated = replace(updated, legacy_save_json=json.dumps(
            updated_payload, ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":")))
        save_data["_career_adapter_state"] = updated
        app["_adapter"] = updated
        app["page"] = "home"
        app["nav_index"] = 0
        app["spatial_watching"] = False
        app["message"] = f"Spatial result saved · round closed · {count} fixtures resolved."
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        app["message"] = f"Settlement needs attention: {exc}"


def _handle_match_setup_key(key: int, career: dict[str, Any],
                            save_data: dict[str, Any], app: dict[str, Any]) -> bool:
    setup = app.get("match_setup")
    if not isinstance(setup, dict):
        app["page"] = "home"
        return True
    slots = formation_slots(setup["shape"])
    selected = int(clamp(setup.get("selected_slot", 0), 0, len(slots) - 1))
    if key in (27, ord("q"), ord("Q")):
        app["page"] = "home"
        app["message"] = "Matchday setup paused. The current league fixture is unchanged."
    elif key in (curses.KEY_UP, ord("k")):
        setup["selected_slot"] = max(0, selected - 1)
    elif key in (curses.KEY_DOWN, ord("j")):
        setup["selected_slot"] = min(len(slots) - 1, selected + 1)
    elif key in (ord("f"), ord("F")):
        shape = _cycle_choice(setup["shape"], tuple(FORMATION_SLOT_IDS))
        adapter = save_data.get("_career_adapter_state")
        try:
            profiles, unavailable = _prepared_match_profiles(
                adapter if isinstance(adapter, VersionedCareerSave)
                else migrate_v2_save({"version": 2, "career": career}),
                career, setup["club_id"])
            del profiles
            lineup = _matchday_lineup(career, setup["club_id"], shape, unavailable)
            if len(lineup) != 11:
                app["message"] = "That shape has fewer than 11 selectable players."
            else:
                positions = legal_formation_positions(
                    setup["team_id"], default_formation_positions(shape))
                setup.update(shape=shape, lineup_ids=lineup, positions=positions,
                             selected_slot=0)
                app["message"] = f"Formation set to {shape}; place its players before kickoff."
        except (KeyError, TypeError, ValueError) as exc:
            app["message"] = f"Formation could not be changed: {exc}"
    elif key in (ord("t"), ord("T")):
        styles = tuple(key for key, _label in MATCHDAY_PROFILE_STYLES)
        setup["style_id"] = _cycle_choice(setup["style_id"], styles)
        app["message"] = f"Match plan: {dict(MATCHDAY_PROFILE_STYLES)[setup['style_id']]}"
    elif key in tuple(ord(symbol) for symbol in "1234567890A"):
        symbol_index = "1234567890A".index(chr(key))
        if symbol_index < len(setup["lineup_ids"]):
            setup["selected_slot"] = symbol_index
            player_id = setup["lineup_ids"][symbol_index]
            app["message"] = f"Selected {career['players'][player_id]['name']} from your XI."
    elif key in (ord("w"), ord("W"), ord("a"), ord("A"),
                 ord("s"), ord("S"), ord("d"), ord("D")):
        slot = slots[selected]
        current = setup["positions"][slot]
        dx = -2.0 if key in (ord("a"), ord("A")) else 2.0 if key in (ord("d"), ord("D")) else 0.0
        dy = -2.0 if key in (ord("w"), ord("W")) else 2.0 if key in (ord("s"), ord("S")) else 0.0
        proposed = dict(setup["positions"])
        proposed[slot] = Position2D(current.x_m + dx, current.y_m + dy)
        setup["positions"] = legal_formation_positions(setup["team_id"], proposed)
        app["message"] = f"{career['players'][setup['lineup_ids'][selected]]['name']} placed at " \
                          f"{setup['positions'][slot].x_m:.1f}, {setup['positions'][slot].y_m:.1f}m."
    elif key in (10, 13, curses.KEY_ENTER):
        _start_spatial_match(save_data, career, app)
    return True


def _handle_spatial_subs_key(key: int, career: dict[str, Any],
                             save_data: dict[str, Any], app: dict[str, Any]) -> bool:
    adapter = save_data.get("_career_adapter_state")
    if not isinstance(adapter, VersionedCareerSave) or adapter.spatial_match_json is None:
        app["page"] = "home"
        return True
    session = resume_spatial_career_match(adapter)
    team_id = _spatial_user_team(session, career)
    roster = session.match.teams[team_id]
    active_ids = [player_id for player_id in roster.starting_ids
                  if player_id in session.match.play.players]
    active_ids.extend(sorted((player_id for player_id, state in session.match.play.players.items()
                              if state.team_id == team_id and player_id not in active_ids),
                             key=str))
    bench = list(roster.eligible_bench())
    keeper_required = session.match.keeper_replacement_team_id == team_id
    if keeper_required:
        bench = [profile for profile in bench if profile.primary_role.value == "goalkeeper"]
    focus = app.get("spatial_sub_focus", "out")
    if focus not in ("out", "in"):
        focus = "in" if keeper_required else "out"
        app["spatial_sub_focus"] = focus
    out_index = int(clamp(app.get("spatial_sub_out_index", 0), 0,
                          max(0, len(active_ids) - 1)))
    in_index = int(clamp(app.get("spatial_sub_in_index", 0), 0,
                         max(0, len(bench) - 1)))
    if key in (27, ord("q"), ord("Q")):
        app["page"] = "spatial_match"
    elif key == 9:
        app["spatial_sub_focus"] = "in" if focus == "out" else "out"
    elif key in (curses.KEY_UP, ord("k")):
        if focus == "in":
            app["spatial_sub_in_index"] = max(0, in_index - 1)
        else:
            app["spatial_sub_out_index"] = max(0, out_index - 1)
    elif key in (curses.KEY_DOWN, ord("j")):
        if focus == "in":
            app["spatial_sub_in_index"] = min(max(0, len(bench) - 1), in_index + 1)
        else:
            app["spatial_sub_out_index"] = min(max(0, len(active_ids) - 1), out_index + 1)
    elif key in (10, 13, curses.KEY_ENTER):
        if not active_ids or not bench:
            app["message"] = "No eligible player pair is available."
        else:
            outgoing_id = active_ids[out_index]
            if keeper_required and outgoing_id == session.match.play.possession_id:
                app["message"] = (
                    "Choose another outfield player: the active ball carrier cannot leave now."
                )
                app["page"] = "spatial_subs"
            else:
                _queue_spatial_substitution(
                    career, save_data, app,
                    str(outgoing_id), str(bench[in_index].player_id),
                )
                current_session = _spatial_session(save_data)
                if (keeper_required and current_session is not None
                        and current_session.match.keeper_replacement_team_id == team_id):
                    app["page"] = "spatial_subs"
                else:
                    app["page"] = "spatial_match"
    return True


def _handle_spatial_match_key(key: int, career: dict[str, Any],
                              save_data: dict[str, Any], app: dict[str, Any]) -> bool:
    adapter = save_data.get("_career_adapter_state")
    if not isinstance(adapter, VersionedCareerSave) or adapter.spatial_match_json is None:
        app["page"] = "home"
        return True
    session = resume_spatial_career_match(adapter)
    match = session.match
    app["spatial_match_phase"] = match.phase
    app["spatial_keeper_replacement"] = match.keeper_replacement_team_id
    app["spatial_keeper_user_required"] = (
        match.keeper_replacement_team_id == _spatial_user_team(session, career)
        if match.keeper_replacement_team_id is not None else False
    )
    if key == -1:
        if app.get("spatial_watching") and match.phase not in (
                MatchPhase.FINISHED, MatchPhase.ABANDONED):
            _advance_spatial_match(
                career, save_data, app,
                int(app.get("spatial_watch_ticks", 25)))
        return True
    if key == 9:
        views = SPATIAL_MATCH_VIEWS
        view = app.get("match_view", "live")
        app["match_view"] = views[(views.index(view) + 1) % len(views)] if view in views else "live"
    elif app.get("match_view") == "events" and key in (ord("m"), ord("M")):
        app["show_movement_events"] = not app.get("show_movement_events", False)
        visible = (list(match.events) if app["show_movement_events"]
                   else _key_match_events(match.events))
        app["event_index"] = max(0, len(visible) - 1)
        app["message"] = ("Showing every movement event. M returns to the key-event chronology."
                          if app["show_movement_events"] else
                          "Movement detail is hidden; all event data remains in the match record.")
    elif app.get("match_view") == "events" and key in (curses.KEY_UP, ord("k")):
        visible = (list(match.events) if app.get("show_movement_events", False)
                   else _key_match_events(match.events))
        app["event_index"] = max(0, int(app.get("event_index", len(visible) - 1)) - 1)
    elif app.get("match_view") == "events" and key in (curses.KEY_DOWN, ord("j")):
        visible = (list(match.events) if app.get("show_movement_events", False)
                   else _key_match_events(match.events))
        app["event_index"] = min(max(0, len(visible) - 1),
                                  int(app.get("event_index", len(visible) - 1)) + 1)
    elif (key in (curses.KEY_UP, ord("k"))
          and app.get("match_view") in ("stats", "players")):
        app["spatial_roster_scroll"] = max(
            0, int(app.get("spatial_roster_scroll", 0)) - 1)
    elif (key in (curses.KEY_DOWN, ord("j"))
          and app.get("match_view") in ("stats", "players")):
        app["spatial_roster_scroll"] = int(app.get("spatial_roster_scroll", 0)) + 1
    elif app.get("match_view") in ("live", "pitch") and key in (ord("["), ord("]")):
        cycle_bounds = (app.get("spatial_pitch_bounds")
                        if app.get("match_view") == "pitch"
                        and app.get("spatial_pitch_zoom") else None)
        player_ids = _spatial_player_cycle_ids(
            match, str(app.get("spatial_selected_player_id", "")),
            app.get("spatial_pitch_viewport"), cycle_bounds,
        )
        if player_ids:
            selected = str(app.get("spatial_selected_player_id", ""))
            current = next((index for index, player_id in enumerate(player_ids)
                            if str(player_id) == selected),
                           -1 if key == ord("]") else 0)
            delta = 1 if key == ord("]") else -1
            player_id = player_ids[(current + delta) % len(player_ids)]
            app["spatial_selected_player_id"] = str(player_id)
            app["spatial_pitch_focus_ball"] = False
            profile = match.play.players[player_id].profile
            app["message"] = (f"Selected {profile.display_name} · "
                              f"{profile.primary_role.value.replace('_', ' ')}.")
    elif (app.get("match_view") in ("live", "pitch") and key == ord("B")):
        opened_from_live = app.get("match_view") == "live"
        app["match_view"] = "pitch"
        app["spatial_pitch_zoom"] = True
        selected_id = str(app.get("spatial_selected_player_id", ""))
        has_selected_player = any(
            str(player_id) == selected_id for player_id in match.play.players)
        if opened_from_live:
            app["spatial_pitch_focus_ball"] = True
        elif app.get("spatial_pitch_focus_ball") and has_selected_player:
            app["spatial_pitch_focus_ball"] = False
        elif app.get("spatial_pitch_focus_ball") and not has_selected_player:
            app["message"] = "No selected player; close pitch view stays on the live ball."
            return True
        else:
            app["spatial_pitch_focus_ball"] = True
        if app.get("spatial_pitch_focus_ball"):
            app["message"] = "Close pitch view follows the live ball; B returns to the selected player."
        else:
            profile = next((state.profile for player_id, state in match.play.players.items()
                            if str(player_id) == selected_id), None)
            name = profile.display_name if profile else "selected player"
            app["message"] = f"Close pitch view follows {name}; B returns to the live ball."
    elif (app.get("match_view") == "live"
          and key in (ord("z"), ord("Z"))):
        app["match_view"] = "pitch"
        app["spatial_pitch_zoom"] = True
        app["spatial_pitch_focus_ball"] = False
        selected_id = str(app.get("spatial_selected_player_id", ""))
        focus_target = ("selected player" if any(
            str(player_id) == selected_id for player_id in match.play.players
        ) else "live ball")
        app["message"] = (f"Close pitch view follows the {focus_target}. "
                           "Z restores the full pitch.")
    elif (app.get("match_view") == "pitch"
          and key in (ord("z"), ord("Z"))):
        app["spatial_pitch_zoom"] = not app.get("spatial_pitch_zoom", False)
        selected_id = str(app.get("spatial_selected_player_id", ""))
        focus_target = ("live ball" if app.get("spatial_pitch_focus_ball") else
                        "selected player" if any(
            str(player_id) == selected_id for player_id in match.play.players
        ) else "live ball")
        app["message"] = (
            f"Close pitch view follows the {focus_target}; Z restores the full pitch."
            if app["spatial_pitch_zoom"] else
            f"Full pitch restored; Z follows the {focus_target} again.")
    elif match.phase is MatchPhase.FINISHED:
        if key in (10, 13, curses.KEY_ENTER):
            _settle_spatial_match(career, save_data, app)
        elif key == 27:
            app["page"] = "home"
            app["message"] = "Full-time match and event record remain saved. M reopens the report."
        return True
    elif match.phase is MatchPhase.ABANDONED:
        app["spatial_watching"] = False
        if key == 27:
            app["page"] = "home"
            app["message"] = (
                "Abandoned match saved without a league result; a competition policy is needed "
                "before the round can advance."
            )
        else:
            app["message"] = "This match is abandoned. Review its chronology or Esc to Home."
        return True
    elif key in (ord(" "),):
        app["spatial_watching"] = not app.get("spatial_watching", False)
        app["message"] = ("Match watch resumed." if app["spatial_watching"]
                          else "Match paused; the spatial checkpoint is saved.")
    elif key in (ord("."), ord(">")):
        app["spatial_watching"] = False
        _advance_spatial_match(career, save_data, app, 1)
    elif key in (ord("-"), ord("+"), ord("=")):
        speeds = (10, 25, 50, 100, 250)
        current = int(app.get("spatial_watch_ticks", 25))
        current_index = min(range(len(speeds)), key=lambda index: abs(speeds[index] - current))
        next_index = min(len(speeds) - 1, current_index + 1) if key != ord("-") \
            else max(0, current_index - 1)
        app["spatial_watch_ticks"] = speeds[next_index]
        app["message"] = f"Watch speed: {speeds[next_index]} simulation ticks per screen update."
    elif key in (ord("s"), ord("S")):
        app["spatial_sub_out_index"] = 0
        app["spatial_sub_in_index"] = 0
        app["spatial_sub_focus"] = "in" if app["spatial_keeper_user_required"] else "out"
        app["page"] = "spatial_subs"
    elif key in (ord("q"), ord("Q")):
        app["spatial_watching"] = False
        advanced = _advance_spatial_match(career, save_data, app, 500_000)
        current = resume_spatial_career_match(save_data["_career_adapter_state"]).match
        if current.phase is MatchPhase.FINISHED:
            app["message"] = (
                f"Quick-sim reached full time after {advanced} transitions; "
                "review the chronology, then settle the round."
            )
        elif current.phase is not MatchPhase.ABANDONED and current.keeper_replacement_team_id is None:
            app["message"] = f"Quick-sim stopped after {advanced} transitions; the match is still in progress."
    elif key == 27:
        app["spatial_watching"] = False
        app["page"] = "home"
        app["message"] = "Match paused. M returns to the saved live pitch and clock."
    elif app.get("match_view") in ("live", "pitch") and 0 <= key < 128:
        symbol = chr(key)
        symbols = _spatial_player_symbols(match)
        selected_id = next((player_id for player_id in match.play.players
                            if symbols.get(str(player_id)) == symbol), None)
        if selected_id is not None:
            app["spatial_selected_player_id"] = str(selected_id)
            app["spatial_pitch_focus_ball"] = False
            profile = match.play.players[selected_id].profile
            app["message"] = (f"Selected {profile.display_name} · "
                              f"{profile.primary_role.value.replace('_', ' ')}.")
    return True


def _route_key(key: int, career: dict[str, Any] | None,
               save_data: dict[str, Any], app: dict[str, Any]) -> bool:
    """Handle one key; return False only when the player exits cleanly."""
    page = app.get("page", "home")
    if key == curses.KEY_RESIZE:
        return True
    if key == -1 and not (page == "spatial_match" and app.get("spatial_watching")):
        return True
    if page == "match_setup" and career:
        _handle_match_setup_key(key, career, save_data, app)
        _persist(save_data, career)
        return True
    if page == "spatial_match" and career:
        _handle_spatial_match_key(key, career, save_data, app)
        _persist(save_data, career)
        return True
    if page == "spatial_subs" and career:
        _handle_spatial_subs_key(key, career, save_data, app)
        _persist(save_data, career)
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
    if page == "spatial_report":
        if key in (curses.KEY_UP, ord("k")):
            app["spatial_report_scroll"] = max(
                0, int(app.get("spatial_report_scroll", 0)) - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            app["spatial_report_scroll"] = int(app.get("spatial_report_scroll", 0)) + 1
        _persist(save_data, career)
        return True
    if page == "home" and key in (ord("r"), ord("R")) and career:
        if _latest_managed_spatial_result(career):
            app["page"] = "spatial_report"
            app["nav_index"] = 0
            app["spatial_report_scroll"] = 0
            app["message"] = "Last spatial match report · score, scoring lineage and playing time."
        else:
            app["message"] = "No settled spatial match report is saved in this career yet."
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
            _start_matchday(career, app, save_data)
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
        _start_matchday(career, app, save_data)
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
    save_data.pop("_career_adapter_state", None)
    app.pop("_adapter", None)
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
    match_engine = os.environ.get("TOUCHLINE_MATCH_ENGINE", "spatial").strip().lower()
    if match_engine not in ("spatial", "legacy"):
        match_engine = "spatial"
    if career:
        _ensure_player_ids(career)
        for cid, state in career.get("clubs", {}).items():
            if not state.get("lineup") and state.get("roster"):
                state["lineup"] = best_lineup(career, cid)
    app: dict[str, Any] = {
        "page": ("team_talk" if career and _needs_team_talk(career.get("live_match"))
                 else "match" if career and career.get("live_match") else
                 "spatial_match" if career and _spatial_session(save_data) else
                 "home" if career else "career_select"),
        "nav_index": (MATCH_NAV_INDEX if career and
                      (career.get("live_match") or _spatial_session(save_data)) else 0),
        "club_index": 0, "squad_index": 0, "market_index": 0,
        "match_view": "live",
        "match_engine": match_engine,
        "_adapter": save_data.get("_career_adapter_state"),
        "_save_data": save_data,
        "spatial_watching": False,
        "spatial_watch_ticks": 25,
        "message": "Choose a club and build a football life around its people.",
    }
    spatial_session = _spatial_session(save_data)
    if spatial_session is not None:
        app["spatial_tactical_runtimes"] = tactical_runtimes(spatial_session, career or {})
        app["spatial_match_phase"] = spatial_session.match.phase
        app["spatial_keeper_replacement"] = spatial_session.match.keeper_replacement_team_id
        app["spatial_keeper_user_required"] = (
            spatial_session.match.keeper_replacement_team_id
            == _spatial_user_team(spatial_session, career)
            if career and spatial_session.match.keeper_replacement_team_id is not None
            else False
        )
    app["career"] = career
    app["data"] = save_data
    win, screen = ts.tv_curses(stdscr, "Ekse Slaan Ball")
    _restore_bezel_bottom_right(stdscr, screen)
    win.clear()
    win.keypad(True)
    while True:
        win.timeout(50 if app.get("page") == "spatial_match"
                    and app.get("spatial_watching") else -1)
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
