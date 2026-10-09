"""Fresh-process deterministic probe for the headless P09 preparation state."""

from __future__ import annotations

import argparse
from datetime import date, timedelta

from games.touchline.esb.content.proof_roster import PROOF_SQUADS
from games.touchline.esb.ids import CareerId, MatchId
from games.touchline.esb.world.preparation import (
    ExposureInput,
    PreparationFixture,
    advance_preparation_day,
    create_preparation_state,
    settle_fixture_exposure,
)
from games.touchline.esb.time import WorldDate


def run(seed: int) -> str:
    squad = PROOF_SQUADS[0]
    start = WorldDate(date(2026, 9, 24))
    fixture_day = WorldDate(start.day + timedelta(days=2))
    match_id = MatchId("match:p09-determinism")
    state = create_preparation_state(
        career_id=CareerId("career:p09-determinism"),
        club_id=squad.club_id,
        world_date=start,
        profiles=squad.players,
        fixtures=(PreparationFixture(match_id, fixture_day),),
        seed=seed,
    )
    state = advance_preparation_day(state, WorldDate(start.day + timedelta(days=1)))
    state = advance_preparation_day(state, fixture_day)
    played_id = squad.players[10].player_id
    exposure = tuple(
        ExposureInput(profile.player_id, 90 if profile.player_id == played_id else 0,
                      0.76 if profile.player_id == played_id else 0.0)
        for profile in squad.players
    )
    return settle_fixture_exposure(state, match_id, exposure).to_json()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1729)
    args = parser.parse_args(argv)
    print(run(args.seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
