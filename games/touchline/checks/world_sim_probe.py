"""Fresh-process deterministic multi-competition world/archive probe for P16a."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from games.touchline.esb.content.proof_world import proof_world_schedule
from games.touchline.esb.world.archive import WorldArchiveStore


def fingerprint(seed: int) -> dict[str, object]:
    schedule = proof_world_schedule(seed=seed)
    with TemporaryDirectory(prefix="touchline-world-probe-") as temporary:
        archive_path = Path(temporary) / "world.sqlite3"
        with WorldArchiveStore(archive_path) as archive:
            progress = archive.simulate(schedule)
            matches = []
            for fixture in schedule.ordered_fixtures:
                summary = archive.match_summary(fixture.match_id)
                match = archive.match_state(fixture.match_id)
                matches.append({
                    "match_id": summary["match_id"],
                    "competition_id": summary["competition_id"],
                    "ruleset_id": summary["ruleset_id"],
                    "score": [summary["home_goals"], summary["away_goals"]],
                    "event_count": summary["event_count"],
                    "state_sha256": summary["state_sha256"],
                    "events_sha256": hashlib.sha256("\n".join(
                        event.payload_json + "\n" + event.outcome_json
                        for event in archive.events(fixture.match_id)
                    ).encode("utf-8")).hexdigest(),
                    "players": len(match.teams["home"].starting_ids)
                    + len(match.teams["away"].starting_ids),
                })
            league_table = [
                [row.participant_id, row.played, row.points, row.goals_for, row.goals_against]
                for row in archive.competition_table("competition:proof-league")
            ]
            metrics = archive.metrics()
            return {
                "world_id": schedule.world_id,
                "season_id": schedule.season_id,
                "progress": [progress.scheduled, progress.archived, progress.pending],
                "matches": matches,
                "league_table": league_table,
                "archive": [metrics.total_recorded_events, metrics.player_rows,
                            metrics.unique_players, metrics.summary_bytes],
            }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=271828)
    args = parser.parse_args()
    print(json.dumps(fingerprint(args.seed), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
