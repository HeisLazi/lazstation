"""Small same-seed career-adapter run for fresh-process determinism checks."""

from __future__ import annotations

import argparse
import hashlib
import json
from typing import Sequence

from games.touchline.esb.content.proof_roster import PROOF_SQUADS
from games.touchline.esb.match.engine import TeamSheet
from games.touchline.esb.match.possession import PlayerState
from games.touchline.esb.match.rules import STANDARD_RULES
from games.touchline.esb.match.spatial import Pitch, PlayerMotion, limits_from_profile
from games.touchline.esb.model import Position2D
from games.touchline.esb.career_adapter import (
    migrate_v2_save,
    resume_spatial_career_match,
    run_spatial_career_match,
    settle_spatial_career_match,
    start_spatial_career_match,
)


LINEUP_INDEXES = (0, 2, 3, 5, 6, 10, 13)
HOME_POSITIONS = ((4, 34), (15, 20), (15, 48), (28, 9), (28, 59),
                  (52.5, 34), (40, 34))
AWAY_POSITIONS = ((101, 34), (90, 20), (90, 48), (78, 9), (78, 59),
                  (62, 34), (70, 34))


def build_scenario(seed: int = 17, half_ticks: int = 8):
    home_squad, away_squad = PROOF_SQUADS
    sheets = []
    clubs = {}
    players = {}
    table = {}
    for team_id, squad, positions in (
        ("home", home_squad, HOME_POSITIONS),
        ("away", away_squad, AWAY_POSITIONS),
    ):
        club_id = str(squad.club_id)
        selected = set(LINEUP_INDEXES)
        starters = tuple(
            PlayerState(
                squad.players[index],
                PlayerMotion(
                    squad.players[index].player_id,
                    team_id,
                    Position2D(*position),
                    0.0,
                    0.0,
                    0.0,
                    limits_from_profile(squad.players[index]),
                ),
                team_id,
            )
            for index, position in zip(LINEUP_INDEXES, positions)
        )
        bench_indexes = [index for index in range(len(squad.players)) if index not in selected]
        substitutes = tuple(squad.players[index] for index in bench_indexes[:3])
        unavailable_id = squad.players[15].player_id
        sheets.append(TeamSheet(team_id, starters, substitutes, (unavailable_id,)))
        roster = [str(profile.player_id) for profile in squad.players]
        lineup = [str(starters_item.profile.player_id) for starters_item in starters]
        clubs[club_id] = {"division": "proof-league", "roster": roster,
                          "lineup": lineup, "wins": 0}
        for profile in squad.players:
            players[str(profile.player_id)] = {
                "club": club_id,
                "injury_until_round": -1,
            }
        table[club_id] = {key: 0 for key in
                          ("played", "won", "drawn", "lost", "gf", "ga", "points")}
    home_id, away_id = str(home_squad.club_id), str(away_squad.club_id)
    career = {
        "version": 2,
        "seed": seed,
        "club_id": home_id,
        "season": 1,
        "round": 0,
        "career_week": 0,
        "season_complete": False,
        "clubs": clubs,
        "players": players,
        "table": table,
        "fixtures": {"proof-league": [[(home_id, away_id)]]},
        "played_ids": [],
        "results": [],
        "live_match": None,
    }
    wrapper = {"version": 2, "career": career}
    # Simulate the actual JSON save/load boundary: fixture tuples become arrays.
    persisted = json.loads(json.dumps(wrapper, ensure_ascii=False, sort_keys=True))
    rules = STANDARD_RULES.with_overrides(
        "rules:p08-determinism-v1", half_duration_ticks=half_ticks,
        offside_enabled=False, fouls_enabled=False, cards_enabled=False,
    )
    return persisted, sheets[0], sheets[1], rules


def run_probe(seed: int = 17) -> dict[str, object]:
    legacy_save, home_sheet, away_sheet, rules = build_scenario(seed)
    versioned = migrate_v2_save(legacy_save)
    started = start_spatial_career_match(
        versioned,
        home_sheet=home_sheet,
        away_sheet=away_sheet,
        seed=seed,
        rules=rules,
        pitch=Pitch(),
    )
    finished = run_spatial_career_match(started, maximum_transitions=2_000)
    session = resume_spatial_career_match(finished)
    settled, applied = settle_spatial_career_match(finished)
    career = settled.legacy_save["career"]
    result = career["results"][-1]
    return {
        "match_id": str(session.binding.match_id),
        "engine_id": result["engine_id"],
        "engine_version": result["engine_version"],
        "ruleset_id": result["ruleset_id"],
        "home_goals": result["home_goals"],
        "away_goals": result["away_goals"],
        "event_count": len(session.match.events),
        "match_json_sha256": hashlib.sha256(
            session.to_json().encode("utf-8")).hexdigest(),
        "settled": applied,
        "round": career["round"],
        "home_played": career["table"][str(session.binding.home_club_id)]["played"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args(argv)
    print(json.dumps(run_probe(args.seed), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
