from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from games.touchline.checks.knowledge_probe import (
    CLUB_ID,
    MATCH_ID,
    OBSERVED_ON,
    build_scenario,
    rich_grant,
    scenario_events,
)
from games.touchline.esb.ids import ClubId, MatchId
from games.touchline.esb.knowledge import (
    CORE_METRICS,
    CoverageGrant,
    CoverageLevel,
    FieldRequest,
    ObservationLedger,
    Report,
    ReportCache,
    ReportQuery,
    StaffCapacity,
    StaffRole,
    StaffSchedule,
    StaffWorkAssignment,
    assign_staff_work,
    build_report,
    observation_task_id,
    record_match_observations,
    record_observations,
)
from games.touchline.esb.content.proof_roster import PROOF_SQUADS
from games.touchline.esb.match.actions import PassIntent, PassKind
from games.touchline.esb.match.ball import BALL_RADIUS_M, BallState
from games.touchline.esb.match.possession import (
    ActionKind,
    Decision,
    FeasibleAction,
    PlayerState,
    create_state,
    execute_action,
    perceive,
)
from games.touchline.esb.match.spatial import MotionLimits, Pitch, PlayerMotion
from games.touchline.esb.model import Position2D
from games.touchline.esb.randomness import RandomStreams
from games.touchline.esb.serialization import dumps, loads
from games.touchline.esb.time import WorldDate


REPO_ROOT = Path(__file__).resolve().parents[3]


class KnowledgeInfrastructureTests(unittest.TestCase):
    def setUp(self):
        self.report, self.cache, self.ledger, self.grant = build_scenario()

    def _query(self, *, club_id=CLUB_ID, as_of=OBSERVED_ON):
        return ReportQuery(
            club_id=club_id,
            match_id=MATCH_ID,
            as_of=as_of,
            metric_ids=("pass_completion_rate", "tracked_position_samples", "observed_goal_events"),
            fields=(
                FieldRequest("pass_completion", CoverageLevel.EVENTS),
                FieldRequest("tracked_position", CoverageLevel.TRACKING, 14),
                FieldRequest("goal_event", CoverageLevel.RESULTS),
            ),
        )

    def _poor_grant(self, club_id=CLUB_ID):
        return CoverageGrant(
            grant_id=f"coverage:poor-{club_id.split(':')[-1]}",
            club_id=club_id,
            match_id=MATCH_ID,
            match_date=OBSERVED_ON,
            starts_on=OBSERVED_ON,
            expires_on=WorldDate(date(2027, 2, 14)),
            level=CoverageLevel.RESULTS,
            permitted_fields=("goal_event",),
            permitted_event_kinds=("goal",),
            method="results bulletin",
            minimum_work_units=1,
        )

    def test_same_match_yields_only_each_clubs_authorized_knowledge(self):
        pass_rate = self.report.metric_findings[0]
        tracked = self.report.metric_findings[1]
        self.assertEqual(pass_rate.value, 0.5)
        self.assertEqual((pass_rate.numerator, pass_rate.denominator), (1, 2))
        self.assertIn("intended receiver", pass_rate.denominator_label)
        self.assertIn("single match", pass_rate.context)
        self.assertEqual(pass_rate.warning_codes, ("small_sample",))
        self.assertEqual(pass_rate.uncertainty, "95% Wilson score interval")
        self.assertLess(pass_rate.lower_bound, pass_rate.value)
        self.assertGreater(pass_rate.upper_bound, pass_rate.value)
        self.assertEqual(tracked.value, 2.0)
        self.assertEqual(self.report.metric_findings[2].value, 1.0)
        self.assertEqual(self.report.field_findings[0].sample_count, 2)
        self.assertEqual(self.report.field_findings[1].sample_count, 2)
        self.assertEqual(self.report.field_findings[2].sample_count, 1)
        self.assertEqual(len(pass_rate.source_event_ids), 6)
        self.assertTrue(all("capabilit" not in item.value_json
                            for item in self.ledger.observations))
        first_pass = next(item for item in self.ledger.observations
                          if item.field == "pass_completion")
        self.assertEqual(tuple(map(str, first_pass.source_event_ids)), (
            "event:knowledge-probe:0000",
            "event:knowledge-probe:0001",
            "event:knowledge-probe:0002",
        ))

        poor = self._poor_grant()
        poor_observations = record_match_observations_from_probe_events(scenario_events(), poor)
        poor_ledger = record_observations(ObservationLedger(), poor_observations)
        poor_report, _ = build_report(self._query(), poor_ledger, (poor,), CORE_METRICS)
        self.assertIsNone(poor_report.metric_findings[0].value)
        self.assertEqual(poor_report.metric_findings[0].unavailable_reason, "coverage_insufficient")
        self.assertIsNone(poor_report.metric_findings[1].value)
        self.assertEqual(poor_report.metric_findings[1].unavailable_reason, "coverage_insufficient")
        self.assertEqual(poor_report.field_findings[1].sample_count, 0)
        self.assertEqual(poor_report.field_findings[1].unavailable_reason, "coverage_insufficient")
        self.assertEqual(poor_report.metric_findings[2].value, 1.0)
        self.assertEqual(poor_report.field_findings[2].sample_count, 1)

    def test_capture_and_report_reissue_are_idempotent_and_keep_lineage(self):
        capacity = StaffCapacity("staff:observer", CLUB_ID,
                                 (StaffRole.OBSERVER, StaffRole.ANALYST), 8)
        assignment = StaffWorkAssignment(
            "assignment:knowledge-probe", observation_task_id(self.grant), capacity.staff_id,
            CLUB_ID, StaffRole.OBSERVER, OBSERVED_ON, 4,
        )
        schedule = assign_staff_work(StaffSchedule(), capacity, assignment)
        captured_again = record_match_observations(
            scenario_events(), self.grant, assignment, capacity, schedule, OBSERVED_ON,
        )
        self.assertEqual(captured_again, self.ledger.observations)
        once = record_observations(self.ledger, captured_again)
        self.assertEqual(once, self.ledger)

        report, cache = build_report(self._query(), once, (self.grant,), CORE_METRICS, self.cache)
        self.assertIs(report, self.report)
        self.assertIs(cache, self.cache)
        self.assertEqual(report.report_id, self.report.report_id)
        self.assertEqual(report.metric_findings[0].source_event_ids,
                         self.report.metric_findings[0].source_event_ids)

        revised_method = replace(self._query(), method_version="match-report-v2")
        revised, revised_cache = build_report(
            revised_method, once, (self.grant,), CORE_METRICS, self.cache,
        )
        self.assertNotEqual(revised.report_id, report.report_id)
        self.assertEqual(len(revised_cache.reports), len(self.cache.reports) + 1)
        revised_registry = replace(CORE_METRICS, version="touchline-metrics-v2")
        registry_report, _ = build_report(
            self._query(), once, (self.grant,), revised_registry, self.cache,
        )
        self.assertNotEqual(registry_report.report_id, report.report_id)

        rng = RandomStreams.seeded(610)
        draws_before = {name: stream.draws for name, stream in rng.streams.items()}
        build_report(self._query(), self.ledger, (self.grant,), CORE_METRICS)
        self.assertEqual({name: stream.draws for name, stream in rng.streams.items()}, draws_before)

    def test_p04_generated_pass_contact_and_control_chain_is_reportable(self):
        home, _ = PROOF_SQUADS
        passer, receiver = home.players[10], home.players[11]

        def player(profile, team, x):
            motion = PlayerMotion(profile.player_id, team, Position2D(x, 34),
                                  0.0, 0.0, 0.0, MotionLimits(8.0, 6.0))
            return PlayerState(profile, motion, team)

        match_id = MatchId("match:p10-real-p04")
        passer_state = player(passer, "home", 35.0)
        receiver_state = player(receiver, "home", 43.0)
        opponent = player(PROOF_SQUADS[1].players[10], "away", 90.0)
        state = create_state(
            match_id,
            (passer_state, receiver_state, opponent),
            BallState(Position2D(35.0, 34.0), BALL_RADIUS_M, 0.0, 0.0, 0.0),
            passer.player_id,
            RandomStreams.seeded(24),
            pitch=Pitch(),
        )
        state.players.pop(opponent.profile.player_id)
        intent = PassIntent(PassKind.DRIVEN, receiver_state.motion.position,
                            intended_receiver_id=receiver.player_id)
        action = FeasibleAction(
            ActionKind.PASS, passer.player_id, receiver.player_id,
            receiver_state.motion.position, intent, 0.8, "P10 event-lineage fixture",
        )
        decision = Decision(passer.player_id, perceive(state, passer.player_id),
                           (action,), action, "fixed evidence test")
        execute_action(state, decision)
        self.assertTrue(any(item.kind == "possession_controlled" for item in state.events))

        grant = replace(
            self.grant,
            grant_id="coverage:p10-real-p04",
            match_id=match_id,
            level=CoverageLevel.EVENTS,
            permitted_fields=("pass_completion",),
            permitted_event_kinds=(
                "pass", "ball_contact", "possession_controlled", "possession_regained",
            ),
            method="P04 event sequence",
            minimum_work_units=2,
        )
        capacity = StaffCapacity("staff:p10-real-p04", CLUB_ID,
                                 (StaffRole.OBSERVER,), 4)
        assignment = StaffWorkAssignment(
            "assignment:p10-real-p04", observation_task_id(grant), capacity.staff_id,
            CLUB_ID, StaffRole.OBSERVER, OBSERVED_ON, 2,
        )
        schedule = assign_staff_work(StaffSchedule(), capacity, assignment)
        observations = record_match_observations(
            tuple(state.events), grant, assignment, capacity, schedule, OBSERVED_ON,
        )
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].field, "pass_completion")
        self.assertIs(json.loads(observations[0].value_json), True)
        self.assertEqual(len(observations[0].source_event_ids), 3)
        self.assertTrue(all(event_id in {event.event_id for event in state.events}
                            for event_id in observations[0].source_event_ids))

    def test_conflicting_reuse_of_one_observation_or_event_chain_fails(self):
        first = next(item for item in self.ledger.observations if item.field == "pass_completion")
        with self.assertRaisesRegex(ValueError, "not implemented or observable"):
            replace(first, field="hidden_passing_skill")
        changed = replace(first, value_json="false")
        with self.assertRaisesRegex(ValueError, "observation ID was reused"):
            record_observations(self.ledger, (changed,))

        second_grant = replace(self.grant, grant_id="coverage:second-method", method="second method")
        capacity = StaffCapacity("staff:observer", CLUB_ID, (StaffRole.OBSERVER,), 8)
        assignment = StaffWorkAssignment(
            "assignment:second-method", observation_task_id(second_grant), capacity.staff_id,
            CLUB_ID, StaffRole.OBSERVER, OBSERVED_ON, 4,
        )
        schedule = assign_staff_work(StaffSchedule(), capacity, assignment)
        second_capture = record_match_observations(
            scenario_events(), second_grant, assignment, capacity, schedule, OBSERVED_ON,
        )
        repeated_pass = next(item for item in second_capture if item.field == "pass_completion")
        self.assertEqual(record_observations(self.ledger, (repeated_pass,)), self.ledger)
        conflicting_chain = replace(repeated_pass, value_json="false")
        with self.assertRaisesRegex(ValueError, "one source event chain"):
            record_observations(self.ledger, (conflicting_chain,))

    def test_staff_role_club_and_daily_capacity_are_enforced(self):
        capacity = StaffCapacity("staff:observer", CLUB_ID,
                                 (StaffRole.OBSERVER, StaffRole.ANALYST), 8)
        assignment = StaffWorkAssignment(
            "assignment:knowledge-probe", observation_task_id(self.grant), capacity.staff_id,
            CLUB_ID, StaffRole.OBSERVER, OBSERVED_ON, 4,
        )
        schedule = assign_staff_work(StaffSchedule(), capacity, assignment)
        self.assertIs(assign_staff_work(schedule, capacity, assignment), schedule)
        overbooked = StaffWorkAssignment(
            "assignment:overbooked", "task:overbooked", capacity.staff_id, CLUB_ID,
            StaffRole.ANALYST, OBSERVED_ON, 5,
        )
        with self.assertRaisesRegex(ValueError, "capacity would be exceeded"):
            assign_staff_work(schedule, capacity, overbooked)

        wrong_club = replace(assignment, club_id=ClubId("club:other"))
        with self.assertRaisesRegex(ValueError, "staff and club must match"):
            assign_staff_work(StaffSchedule(), capacity, wrong_club)
        wrong_role_capacity = StaffCapacity("staff:analyst", CLUB_ID, (StaffRole.ANALYST,), 8)
        wrong_role = replace(assignment, assignment_id="assignment:analyst",
                             staff_id=wrong_role_capacity.staff_id)
        with self.assertRaisesRegex(ValueError, "not qualified"):
            assign_staff_work(StaffSchedule(), wrong_role_capacity, wrong_role)

        analyst_assignment = replace(assignment, assignment_id="assignment:analyst-work",
                                     role=StaffRole.ANALYST)
        analyst_schedule = assign_staff_work(StaffSchedule(), capacity, analyst_assignment)
        with self.assertRaisesRegex(ValueError, "requires an observer assignment"):
            record_match_observations(
                scenario_events(), self.grant, analyst_assignment, capacity,
                analyst_schedule, OBSERVED_ON,
            )

    def test_future_expired_cross_match_and_reordered_events_are_rejected(self):
        capacity = StaffCapacity("staff:observer", CLUB_ID, (StaffRole.OBSERVER,), 8)
        assignment = StaffWorkAssignment(
            "assignment:knowledge-probe", observation_task_id(self.grant), capacity.staff_id,
            CLUB_ID, StaffRole.OBSERVER, OBSERVED_ON, 4,
        )
        schedule = assign_staff_work(StaffSchedule(), capacity, assignment)
        with self.assertRaisesRegex(ValueError, "not active"):
            record_match_observations(
                scenario_events(), self.grant, assignment, capacity, schedule,
                WorldDate(date(2028, 1, 1)),
            )
        other_match_event = replace(scenario_events()[0], match_id=MatchId("match:other"))
        with self.assertRaisesRegex(ValueError, "another match"):
            record_match_observations(
                (other_match_event,), self.grant, assignment, capacity, schedule, OBSERVED_ON,
            )
        wrong_aggregate = replace(scenario_events()[0], aggregate_id="match:other")
        with self.assertRaisesRegex(ValueError, "matching match aggregate"):
            record_match_observations(
                (wrong_aggregate,), self.grant, assignment, capacity, schedule, OBSERVED_ON,
            )
        with self.assertRaisesRegex(ValueError, "sequence order"):
            record_match_observations(
                tuple(reversed(scenario_events())), self.grant, assignment,
                capacity, schedule, OBSERVED_ON,
            )

    def test_missing_positions_and_stale_evidence_remain_unknown(self):
        events_without_tracking = tuple(event for event in scenario_events()
                                        if event.kind != "tracking_sample")
        captured = record_match_observations_from_probe_events(
            events_without_tracking, self.grant,
        )
        ledger = record_observations(ObservationLedger(), captured)
        no_tracking, _ = build_report(self._query(), ledger, (self.grant,), CORE_METRICS)
        self.assertIsNone(no_tracking.metric_findings[1].value)
        self.assertEqual(no_tracking.metric_findings[1].unavailable_reason, "no_observations")
        self.assertEqual(no_tracking.field_findings[1].unavailable_reason, "no_observations")

        stale_date = WorldDate(date(2026, 8, 30))
        stale, _ = build_report(self._query(as_of=stale_date), self.ledger,
                                (self.grant,), CORE_METRICS)
        self.assertIsNone(stale.metric_findings[0].value)
        self.assertEqual(stale.metric_findings[0].unavailable_reason, "stale_evidence")
        self.assertTrue(stale.metric_findings[0].source_event_ids)
        self.assertIsNone(stale.metric_findings[1].value)
        self.assertEqual(stale.metric_findings[1].unavailable_reason, "stale_evidence")
        self.assertTrue(stale.field_findings[1].source_observation_ids)

        late_on = WorldDate(date(2026, 6, 1))
        late_grant = replace(
            self.grant,
            grant_id="coverage:late-entry",
            starts_on=WorldDate(date(2026, 2, 14)),
            method="late-entered match report",
        )
        capacity = StaffCapacity("staff:observer", CLUB_ID, (StaffRole.OBSERVER,), 8)
        assignment = StaffWorkAssignment(
            "assignment:late-entry", observation_task_id(late_grant), capacity.staff_id,
            CLUB_ID, StaffRole.OBSERVER, late_on, 4,
        )
        schedule = assign_staff_work(StaffSchedule(), capacity, assignment)
        late_capture = record_match_observations(
            scenario_events(), late_grant, assignment, capacity, schedule, late_on,
        )
        late_ledger = record_observations(ObservationLedger(), late_capture)
        late_report, _ = build_report(
            self._query(as_of=late_on), late_ledger, (late_grant,), CORE_METRICS,
        )
        self.assertEqual(late_capture[0].recorded_on, late_on)
        self.assertEqual(late_capture[0].evidence_date, OBSERVED_ON)
        self.assertEqual(late_report.metric_findings[0].unavailable_reason, "stale_evidence")
        self.assertTrue(late_report.metric_findings[0].source_observation_ids)

    def test_cross_club_and_as_of_queries_do_not_reveal_other_or_future_evidence(self):
        other, _ = build_report(self._query(club_id=ClubId("club:other")), self.ledger,
                                (self.grant,), CORE_METRICS)
        self.assertEqual(other.metric_findings[0].unavailable_reason, "no_match_access")
        self.assertEqual(other.metric_findings[0].source_event_ids, ())

        before, _ = build_report(self._query(as_of=WorldDate(date(2026, 2, 1))),
                                 self.ledger, (self.grant,), CORE_METRICS)
        self.assertEqual(before.metric_findings[0].unavailable_reason, "coverage_not_started")
        self.assertEqual(before.metric_findings[0].source_observation_ids, ())

    def test_wrong_grant_provenance_is_not_reportable(self):
        pass_observation = next(item for item in self.ledger.observations
                                if item.field == "pass_completion")
        forged_observation = replace(
            pass_observation, coverage_grant_id="coverage:unknown",
        )
        forged_ledger = ObservationLedger((forged_observation,))
        report, _ = build_report(self._query(), forged_ledger, (self.grant,), CORE_METRICS)
        self.assertIsNone(report.metric_findings[0].value)
        self.assertEqual(report.metric_findings[0].unavailable_reason,
                         "provenance_not_authorized")

    def test_records_round_trip_with_provenance_capacity_and_uncertainty(self):
        self.assertEqual(loads(dumps(self.ledger), ObservationLedger), self.ledger)
        self.assertEqual(loads(dumps(self.grant), CoverageGrant), self.grant)
        self.assertEqual(loads(dumps(self.cache), ReportCache), self.cache)
        self.assertEqual(loads(dumps(self.report), Report), self.report)
        self.assertEqual(loads(dumps(CORE_METRICS), type(CORE_METRICS)), CORE_METRICS)
        observation = next(item for item in self.ledger.observations
                           if item.field == "pass_completion")
        self.assertEqual(observation.provenance.evidence_date, observation.evidence_date)
        self.assertEqual(len(observation.source_event_ids), 3)

    def test_fresh_process_report_and_headless_import_are_stable(self):
        with tempfile.TemporaryDirectory(prefix="touchline-p10-pycache-") as pycache:
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONPYCACHEPREFIX"] = pycache
            command = [sys.executable, "-m", "games.touchline.checks.knowledge_probe"]
            first = subprocess.run(command, cwd=REPO_ROOT, env=env, check=True,
                                   capture_output=True, text=True).stdout
            second = subprocess.run(command, cwd=REPO_ROOT, env=env, check=True,
                                    capture_output=True, text=True).stdout
        self.assertEqual(first, second)
        report_payload = json.loads(first)
        self.assertEqual(report_payload["payload"]["metric_findings"][0]["numerator"], 1)

        code = r'''
import builtins, importlib, io, pathlib, sys
def blocked(*args, **kwargs): raise AssertionError("knowledge import performed file I/O")
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
importlib.import_module("games.touchline.esb.knowledge")
assert "curses" not in sys.modules
assert "termstation_ui" not in sys.modules
assert "games.touchline.main" not in sys.modules
assert not any(name.startswith("termstation.") for name in sys.modules)
'''
        child = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT,
                               capture_output=True, text=True)
        self.assertEqual(child.returncode, 0, child.stderr)


def record_match_observations_from_probe_events(events, grant):
    capacity = StaffCapacity("staff:observer", CLUB_ID, (StaffRole.OBSERVER,), 8)
    assignment = StaffWorkAssignment(
        "assignment:knowledge-probe", observation_task_id(grant), capacity.staff_id,
        CLUB_ID, StaffRole.OBSERVER, OBSERVED_ON, 4,
    )
    schedule = assign_staff_work(StaffSchedule(), capacity, assignment)
    return record_match_observations(events, grant, assignment, capacity, schedule, OBSERVED_ON)


if __name__ == "__main__":
    unittest.main()
