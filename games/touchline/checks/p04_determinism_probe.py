"""Emit a compact replay fingerprint for a seeded P04 open-play sequence."""

from __future__ import annotations

import argparse
import json

from games.touchline.esb.content.proof_roster import PROOF_SQUADS
from games.touchline.esb.ids import MatchId
from games.touchline.esb.match.ball import BALL_RADIUS_M, BallState
from games.touchline.esb.match.possession import PlayerState, create_state, step_open_play
from games.touchline.esb.match.spatial import MotionLimits, Pitch, PlayerMotion
from games.touchline.esb.model import Position2D
from games.touchline.esb.randomness import RandomStreams


def fingerprint(seed: int) -> dict[str, object]:
    home, away = PROOF_SQUADS
    players = []
    for profile, team, x, y in (
        (home.players[10], "home", 35.0, 34.0),
        (home.players[11], "home", 43.0, 31.0),
        (away.players[10], "away", 39.0, 35.0),
    ):
        motion = PlayerMotion(profile.player_id, team, Position2D(x, y), 0.0, 0.0, 0.0,
                              MotionLimits(8.0, 6.0))
        players.append(PlayerState(profile, motion, team))
    state = create_state(MatchId("match:p04-probe"), tuple(players),
        BallState(Position2D(35.0, 34.0), BALL_RADIUS_M, 0.0, 0.0, 0.0),
        home.players[10].player_id, RandomStreams.seeded(seed), pitch=Pitch())
    for _ in range(8):
        step_open_play(state)
    return {
        "seed": seed,
        "tick": state.clock.tick,
        "ball": [state.ball.position.x_m, state.ball.position.y_m, state.ball.height_m,
                 state.ball.velocity_x_mps, state.ball.velocity_y_mps, state.ball.velocity_z_mps],
        "possession": str(state.possession_id) if state.possession_id else None,
        "score": [state.home_score, state.away_score],
        "statistics": dict(sorted(state.statistics.items())),
        "events": [[e.sequence, e.match_tick, e.kind, e.payload_json, e.outcome_json]
                   for e in state.events],
        "football_rng": [state.random_streams.stream("football").state,
                         state.random_streams.stream("football").draws],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=2605)
    args = parser.parse_args()
    print(json.dumps(fingerprint(args.seed), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
