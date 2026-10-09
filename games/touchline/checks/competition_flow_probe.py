"""Run the synthetic P16b world flow and print a stable JSON report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from games.touchline.esb.content.proof_world import proof_world_flow_state, proof_world_schedule
from games.touchline.esb.world.archive import WorldArchiveStore
from games.touchline.esb.world.competition_flow import simulate_world_season


def run_probe(*, seed: int = 271828, half_ticks: int = 2) -> dict[str, object]:
    schedule = proof_world_schedule(seed=seed, half_ticks=half_ticks)
    initial_state = proof_world_flow_state(schedule)
    with tempfile.TemporaryDirectory(prefix="touchline-p16b-probe-") as directory:
        archive_path = Path(directory) / "world.sqlite3"
        with WorldArchiveStore(archive_path) as archive:
            first, _ = simulate_world_season(
                schedule, initial_state, archive, maximum_fixtures=2,
            )
        with WorldArchiveStore(archive_path) as archive:
            resumed, final_state = simulate_world_season(schedule, initial_state, archive)
            matches = []
            for fixture in schedule.ordered_fixtures:
                summary = archive.match_summary(fixture.match_id)
                matches.append({
                    "fixture_id": fixture.fixture_id,
                    "match_id": str(fixture.match_id),
                    "competition_id": fixture.competition_id,
                    "scheduled_on": fixture.scheduled_on.isoformat,
                    "home_goals": summary["home_goals"],
                    "away_goals": summary["away_goals"],
                    "event_count": summary["event_count"],
                })
            exposure_rows = []
            for profile in initial_state.profiles:
                history = archive.world_player_exposure_history(profile.player_id)
                exposure_rows.append({
                    "player_id": str(profile.player_id),
                    "fixtures": len(history),
                    "minutes": sum(item.minutes_played for item in history),
                    "injuries": sum(item.injury_id is not None for item in history),
                })
            return {
                "schema_version": 1,
                "schedule_sha256": initial_state.schedule_sha256,
                "initial_state_sha256": initial_state.initial_state_sha256,
                "first_run": {
                    "simulated": first.simulated_this_run,
                    "archived": first.archived,
                    "pending": first.pending,
                },
                "resume_run": {
                    "simulated": resumed.simulated_this_run,
                    "resumed": resumed.resumed_this_run,
                    "archived": resumed.archived,
                    "pending": resumed.pending,
                },
                "world_state_sha256": final_state.state_sha256,
                "world_state_revision": final_state.revision,
                "matches": matches,
                "exposure_rows": exposure_rows,
            }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=271828)
    parser.add_argument("--half-ticks", type=int, default=2)
    args = parser.parse_args()
    result = run_probe(seed=args.seed, half_ticks=args.half_ticks)
    print(json.dumps(result, allow_nan=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
