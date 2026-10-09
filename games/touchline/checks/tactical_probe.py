"""Fresh-process tactical kickoff, throw-in trap and continuation probe."""

from __future__ import annotations

import argparse
import json

from games.touchline.esb.content.proof_roster import PROOF_SQUADS
from games.touchline.esb.content.proof_tactics import (
    KICKOFF_TOUCHLINE_TRAP, MAN_ORIENTED_PRESS,
)
from games.touchline.esb.ids import MatchId
from games.touchline.esb.match.engine import (
    MatchPhase, TeamSheet, create_match, step_match,
)
from games.touchline.esb.match.possession import PlayerState
from games.touchline.esb.match.rules import STANDARD_RULES
from games.touchline.esb.match.spatial import PlayerMotion, limits_from_profile
from games.touchline.esb.match.tactics import TacticalRuntime
from games.touchline.esb.model import Position2D


_SLOT_INDEX = {
    "GK": 0, "LCB": 2, "RCB": 3, "LB": 5, "RB": 6,
    "DM": 8, "LCM": 10, "RCM": 11, "LW": 12, "RW": 13, "ST": 14,
}
_HOME = {
    "GK": (5.0, 34.0), "LCB": (18.0, 20.0), "RCB": (18.0, 48.0),
    "LB": (27.0, 7.0), "RB": (27.0, 61.0), "DM": (35.0, 34.0),
    "LCM": (40.0, 24.0), "RCM": (40.0, 44.0), "LW": (46.0, 7.0),
    "RW": (46.0, 61.0), "ST": (52.5, 34.0),
}
_AWAY = {
    "GK": (100.0, 34.0), "LCB": (90.0, 20.0), "RCB": (90.0, 48.0),
    "LB": (80.0, 7.0), "RB": (80.0, 61.0), "DM": (72.0, 34.0),
    "LCM": (65.0, 24.0), "RCM": (65.0, 44.0), "LW": (62.0, 7.0),
    "RW": (62.0, 61.0), "ST": (63.0, 34.0),
}


def _team(team_id: str, squad, positions: dict[str, tuple[float, float]]):
    starters = []
    bindings = {}
    for slot, index in _SLOT_INDEX.items():
        profile = squad.players[index]
        x_m, y_m = positions[slot]
        motion = PlayerMotion(profile.player_id, team_id, Position2D(x_m, y_m),
                              0.0, 0.0, 0.0, limits_from_profile(profile))
        starters.append(PlayerState(profile, motion, team_id))
        bindings[slot] = profile.player_id
    return TeamSheet(team_id, tuple(starters)), bindings


def fingerprint(seed: int = 8217, maximum_transitions: int = 220) -> dict[str, object]:
    home_sheet, home_slots = _team("home", PROOF_SQUADS[0], _HOME)
    away_sheet, away_slots = _team("away", PROOF_SQUADS[1], _AWAY)
    rules = STANDARD_RULES.with_overrides(
        f"rules:p06-probe-{seed}", half_duration_ticks=500,
        stoppage_time_ticks=0, extra_time_duration_ticks=0,
        extra_time_stoppage_ticks=0, offside_enabled=False,
        foul_probability_per_challenge=0.0,
    )
    state = create_match(home_sheet, away_sheet, rules=rules, seed=seed,
                         match_id=MatchId(f"match:p06-probe:{seed}"))
    references = {
        "opponent:deep_playmaker": away_slots["DM"],
        "opponent:center_back_left": away_slots["LCB"],
        "opponent:pivot": away_slots["DM"],
        "opponent:last_line": away_slots["ST"],
        "opponent:throw_receiver": away_slots["LW"],
        "deep_touchline_runner": away_slots["LW"],
    }
    home = TacticalRuntime.bind(state.play, KICKOFF_TOUCHLINE_TRAP, "home",
                                home_slots, opponent_slots=references)
    away = TacticalRuntime.bind(state.play, MAN_ORIENTED_PRESS, "away",
                                away_slots, opponent_slots={
                                    "opponent:deep_playmaker": home_slots["DM"],
                                    "opponent:center_back_left": home_slots["LCB"],
                                    "opponent:pivot": home_slots["DM"],
                                    "opponent:last_line": home_slots["ST"],
                                })
    runtimes = {"home": home, "away": away}

    for _ in range(maximum_transitions):
        if (state.phase is MatchPhase.RESTART_READY and state.restart is not None
                and state.restart.kind.value == "throw_in"
                and state.restart.team_id == "away"):
            break
        step_match(state, tactical_runtimes=runtimes)
    else:
        raise RuntimeError("kickoff did not produce the expected away throw-in")

    # Resolve one restart transition so the home trap's pressing response is
    # evaluated against the same live match state as the ordinary engine.
    step_match(state, tactical_runtimes=runtimes)
    return {
        "seed": seed,
        "match_id": str(state.match_id),
        "ruleset_id": state.rules.ruleset_id,
        "phase": state.phase.value,
        "tick": state.play.clock.tick,
        "score": [state.home_score, state.away_score],
        "events": [
            {
                "sequence": event.sequence,
                "kind": event.kind,
                "tick": event.match_tick,
                "cause": str(event.cause_event_id) if event.cause_event_id else None,
                "parent": str(event.parent_event_id) if event.parent_event_id else None,
                "payload": event.payload_json,
                "outcome": event.outcome_json,
            }
            for event in state.events
        ],
        "tactical_trace": {
            team: [
                {
                    "tick": frame.tick,
                    "phase": frame.phase.value,
                    "movements": [
                        (move.slot_id, move.action.value,
                         round(move.start.x_m, 4), round(move.start.y_m, 4),
                         round(move.target.x_m, 4), round(move.target.y_m, 4),
                         move.source, move.priority)
                        for move in frame.movements
                    ],
                    "events": [(event.code, event.slot_ids, event.detail)
                               for event in frame.events],
                    "restart_target": (
                        (round(frame.restart_target.x_m, 4), round(frame.restart_target.y_m, 4))
                        if frame.restart_target is not None else None
                    ),
                }
                for frame in runtimes[team].trace
            ]
            for team in ("home", "away")
        },
        "random_streams": {
            name: (stream.state, stream.draws)
            for name, stream in sorted(state.play.random_streams.streams.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=8217)
    parser.add_argument("--maximum-transitions", type=int, default=220)
    args = parser.parse_args()
    print(json.dumps(fingerprint(args.seed, args.maximum_transitions),
                     sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
