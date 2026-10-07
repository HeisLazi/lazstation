"""Fresh-process deterministic miniature full-match probe for P05."""

from __future__ import annotations

import argparse
import json

from games.touchline.esb.content.proof_roster import PROOF_SQUADS
from games.touchline.esb.ids import MatchId
from games.touchline.esb.match.engine import TeamSheet, create_match, run_to_completion
from games.touchline.esb.match.possession import PlayerState
from games.touchline.esb.match.rules import STANDARD_RULES
from games.touchline.esb.match.spatial import PlayerMotion, limits_from_profile
from games.touchline.esb.model import Position2D


_LINEUP = (0, 2, 3, 5, 6, 10, 13)
_POSITIONS = {
    "home": ((4, 34), (15, 20), (15, 48), (28, 9), (28, 59), (52.5, 34), (40, 34)),
    "away": ((101, 34), (90, 20), (90, 48), (78, 9), (78, 59), (62, 34), (70, 34)),
}


def _team_sheet(team_id: str, squad) -> TeamSheet:
    starters = []
    for index, roster_index in enumerate(_LINEUP):
        profile = squad.players[roster_index]
        motion = PlayerMotion(profile.player_id, team_id,
            Position2D(*_POSITIONS[team_id][index]), 0.0, 0.0, 0.0,
            limits_from_profile(profile))
        starters.append(PlayerState(profile, motion, team_id))
    bench = tuple(profile for index, profile in enumerate(squad.players)
                  if index not in _LINEUP)[:3]
    return TeamSheet(team_id, tuple(starters), bench, (squad.players[15].player_id,))


def fingerprint(seed: int) -> dict[str, object]:
    rules = STANDARD_RULES.with_overrides(
        "rules:p05-determinism-probe-v1", half_duration_ticks=14,
        stoppage_time_ticks=3, extra_time_duration_ticks=6,
        extra_time_stoppage_ticks=1, shootout_kicks_per_team=3,
        foul_probability_per_challenge=0.08)
    state = create_match(_team_sheet("home", PROOF_SQUADS[0]),
                         _team_sheet("away", PROOF_SQUADS[1]),
                         rules=rules, seed=seed,
                         match_id=MatchId(f"match:p05-determinism:{seed}"))
    state = run_to_completion(state, maximum_transitions=160)
    return {
        "match_id": str(state.match_id),
        "ruleset_id": state.rules.ruleset_id,
        "phase": state.phase.value,
        "period": state.period.value,
        "finished_reason": state.finished_reason,
        "tick": state.play.clock.tick,
        "score": [state.home_score, state.away_score],
        "shootout": ({
            "attempts": state.shootout.attempts,
            "goals": state.shootout.goals,
            "kicks": [(kick.index, kick.team_id, str(kick.taker_id), kick.scored, kick.saved)
                      for kick in state.shootout.kicks],
        } if state.shootout else None),
        "events": [(event.sequence, event.kind, event.match_tick,
                    str(event.cause_event_id) if event.cause_event_id else None,
                    str(event.parent_event_id) if event.parent_event_id else None,
                    event.payload_json, event.outcome_json)
                   for event in state.events],
        "playing_ticks": {str(player_id): ticks
                          for player_id, ticks in sorted(state.playing_ticks.items(), key=lambda row: str(row[0]))},
        "player_statistics": {
            str(player_id): totals
            for player_id, totals in sorted(state.player_statistics.items(), key=lambda row: str(row[0]))
        },
        "stream_states": {name: (stream.state, stream.draws)
                          for name, stream in sorted(state.play.random_streams.streams.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=9142)
    args = parser.parse_args()
    print(json.dumps(fingerprint(args.seed), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
