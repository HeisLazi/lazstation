"""Fresh-process determinism probe for P16c season progression."""

from __future__ import annotations

import json
import hashlib

from games.touchline.esb.content.proof_progression import (
    proof_next_season_schedule,
    proof_progression_plan,
    proof_progression_schedule,
)
from games.touchline.esb.world.archive import ArchiveMetrics, WorldArchiveStore
from games.touchline.esb.world.progression import (
    ResultCompletionBasis,
    resolve_season_progression,
    validate_next_season_schedule,
)
from games.touchline.esb.world.season import fixture_input_sha256, fixture_seed, immutable_snapshot_json


_SCORES = {
    ("club:top-ash", "club:top-birch"): (2, 0),
    ("club:top-ash", "club:top-cinder"): (3, 0),
    ("club:top-birch", "club:top-cinder"): (1, 0),
    ("club:lower-dune", "club:lower-elm"): (1, 0),
    ("club:lower-dune", "club:lower-flint"): (2, 0),
    ("club:lower-elm", "club:lower-flint"): (1, 0),
    ("nation:amber", "nation:birch"): (1, 0),
    ("nation:amber", "nation:cedar"): (1, 1),
    ("nation:amber", "nation:delta"): (3, 0),
    ("nation:birch", "nation:cedar"): (1, 0),
    ("nation:birch", "nation:delta"): (2, 0),
    ("nation:cedar", "nation:delta"): (2, 1),
}


class SyntheticArchive(WorldArchiveStore):
    """Controlled, immutable ArchiveStore contract fixture for progression logic."""

    def __init__(self, schedule, *, scores=None):
        super().__init__(":memory:")
        self._schedule = schedule
        self._schedule_json = immutable_snapshot_json(schedule)
        self._fixtures_by_match = {str(item.match_id): item for item in schedule.fixtures}
        self._scores = _SCORES if scores is None else scores

    def metrics(self):
        return ArchiveMetrics(
            self._schedule.world_id,
            self._schedule.season_id,
            len(self._schedule.fixtures),
            0,
            0,
            len(self._schedule.fixtures),
            0,
            0,
            0,
            0,
        )

    def initialize(self, schedule):
        if immutable_snapshot_json(schedule) != self._schedule_json:
            raise ValueError("synthetic archive schedule differs from its immutable input")

    def recorded_fixture(
        self, fixture_id, *, expected_input_sha256=None, expected_match_id=None,
        expected_simulation_seed=None,
    ):
        fixture = next((item for item in self._schedule.fixtures if item.fixture_id == fixture_id), None)
        if fixture is None:
            return None
        competition = self._schedule.competition(fixture.competition_id)
        input_sha256 = fixture_input_sha256(fixture, competition)
        if (expected_input_sha256 not in (None, input_sha256)
                or expected_match_id not in (None, str(fixture.match_id))
                or expected_simulation_seed not in (None, fixture_seed(self._schedule, fixture))):
            raise ValueError("synthetic archived fixture conflicts with its schedule")
        return input_sha256, str(fixture.match_id)

    def match_summary(self, match_id):
        fixture = self._fixtures_by_match[str(match_id)]
        goals = self._scores[(fixture.home_participant_id, fixture.away_participant_id)]
        return {
            "match_id": str(fixture.match_id),
            "fixture_id": fixture.fixture_id,
            "competition_id": fixture.competition_id,
            "scheduled_on": fixture.scheduled_on.isoformat,
            "home_participant_id": fixture.home_participant_id,
            "away_participant_id": fixture.away_participant_id,
            "home_goals": goals[0],
            "away_goals": goals[1],
            "state_sha256": hashlib.sha256(
                f"synthetic-archived-state:{fixture.match_id}:{goals[0]}:{goals[1]}".encode()
            ).hexdigest(),
            "details_available": False,
        }


def run_probe() -> dict[str, object]:
    schedule = proof_progression_schedule()
    plan = proof_progression_plan()
    archive = SyntheticArchive(schedule)
    result = resolve_season_progression(schedule, archive, plan)
    target_schedule = proof_next_season_schedule(result, plan)
    validate_next_season_schedule(result, plan, target_schedule)
    return {
        "progression_id": result.progression_id,
        "result_sha256": result.result_sha256,
        "source_schedule_sha256": result.source_schedule_sha256,
        "plan_sha256": result.plan_sha256,
        "evidence_mode": "controlled archived result projections with maximum-duration fallback",
        "completion_basis_counts": {
            basis.value: sum(
                fixture.completion_basis is basis
                for evidence in result.source_evidence for fixture in evidence.fixtures
            )
            for basis in ResultCompletionBasis
        },
        "source_competitions": [
            {
                "competition_id": item.competition_id,
                "kind": item.kind.value,
                "fixtures": len(item.fixtures),
                "table": [
                    {
                        "participant_id": row.participant_id,
                        "position": row.position,
                        "played": row.played,
                        "points": row.points,
                        "goal_difference": row.goal_difference,
                    }
                    for row in item.standings
                ],
            }
            for item in result.source_evidence
        ],
        "decisions": [
            {
                "decision_id": item.decision_id,
                "kind": item.kind.value,
                "participant_id": item.participant_id,
                "source_competition_id": item.source_competition_id,
                "source_position": item.source_position,
                "destination_competition_id": item.destination_competition_id,
                "qualification_route_id": item.qualification_route_id,
                "qualification_purpose": (
                    item.qualification_purpose.value if item.qualification_purpose else None
                ),
            }
            for item in result.decisions
        ],
        "entrants": [
            {
                "competition_id": item.competition_id,
                "kind": item.kind.value,
                "participant_ids": list(item.participant_ids),
            }
            for item in result.entrants
        ],
        "target_schedule_fixtures": len(target_schedule.fixtures),
        "target_schedule_validated": True,
    }


def main() -> int:
    print(json.dumps(run_probe(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
