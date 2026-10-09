from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from games.touchline.esb.ids import EventId
from games.touchline.esb.people.relationships import (
    AwarenessBasis,
    ExperienceId,
    PersonalAdjustment,
    PersonalAppraisal,
    PersonalDimension,
    PersonalHistory,
    PersonalState,
    PersonalStateValue,
    PersonId,
    RelationshipDimension,
    RelationshipKnowledge,
    WorldMoment,
    appraise_personal_experience,
    new_personal_experience,
    record_personal_experience,
    record_relationship_evidence,
    record_relationship_knowledge,
)
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.time import WorldDate

ROOT = Path(__file__).resolve().parents[3]
START = WorldDate(date(2026, 10, 5))
SOURCE = PersonId("player:source")
TARGET = PersonId("player:target")


def moment(sequence: int, days: int = 0) -> WorldMoment:
    return WorldMoment(WorldDate(START.day + timedelta(days=days)), sequence)


def empty_history(person_id: PersonId = TARGET) -> PersonalHistory:
    state = PersonalState(
        person_id,
        tuple(PersonalStateValue(dimension, 0.5)
              for dimension in sorted(PersonalDimension, key=lambda item: item.value)),
    )
    return PersonalHistory(person_id, state)


class RelationshipTests(unittest.TestCase):
    def test_relationship_edges_are_directed_and_keep_dimensions_independent(self) -> None:
        first = record_relationship_evidence(
            None,
            source_person_id=SOURCE,
            target_person_id=TARGET,
            dimension=RelationshipDimension.TRUST,
            delta=0.04,
            event_id=EventId("event:trust-1"),
            at=moment(1),
            direct_contact=True,
            initial_value=0.40,
        )
        second = record_relationship_evidence(
            first,
            source_person_id=SOURCE,
            target_person_id=TARGET,
            dimension=RelationshipDimension.AFFINITY,
            delta=-0.03,
            event_id=EventId("event:affinity-1"),
            at=moment(2),
            direct_contact=False,
            initial_value=0.70,
        )
        values = {item.dimension: item.value for item in second.dimensions}
        self.assertEqual(values[RelationshipDimension.TRUST], 0.44)
        self.assertEqual(values[RelationshipDimension.AFFINITY], 0.67)
        self.assertEqual(second.source_person_id, SOURCE)
        self.assertEqual(second.target_person_id, TARGET)
        self.assertNotEqual((second.target_person_id, second.source_person_id),
                            (second.source_person_id, second.target_person_id))
        self.assertEqual(second.last_contact_at, moment(1))
        self.assertEqual(second.supporting_event_ids,
                         (EventId("event:trust-1"), EventId("event:affinity-1")))

    def test_relationship_event_is_once_only_and_conflicts_are_rejected(self) -> None:
        args = dict(
            source_person_id=SOURCE,
            target_person_id=TARGET,
            dimension=RelationshipDimension.RESPECT,
            delta=0.02,
            event_id=EventId("event:respect-1"),
            at=moment(1),
            direct_contact=True,
            initial_value=0.50,
        )
        edge = record_relationship_evidence(None, **args)
        self.assertIs(record_relationship_evidence(edge, **args), edge)
        with self.assertRaisesRegex(ValueError, "conflicting content"):
            record_relationship_evidence(edge, **{**args, "delta": 0.03})
        with self.assertRaisesRegex(ValueError, "conflicting content"):
            record_relationship_evidence(edge, **{**args, "initial_value": 0.90})

    def test_one_shared_event_can_support_two_distinct_relationship_dimensions(self) -> None:
        args = dict(
            source_person_id=SOURCE,
            target_person_id=TARGET,
            event_id=EventId("event:shared-session"),
            at=moment(1),
            direct_contact=True,
        )
        edge = record_relationship_evidence(
            None,
            **args,
            dimension=RelationshipDimension.TRUST,
            delta=0.02,
            initial_value=0.50,
        )
        edge = record_relationship_evidence(
            edge,
            **args,
            dimension=RelationshipDimension.RESPECT,
            delta=0.01,
            initial_value=0.65,
        )
        self.assertEqual(edge.supporting_event_ids, (EventId("event:shared-session"),))
        self.assertEqual(len(edge.evidence), 2)
        self.assertEqual({item.dimension for item in edge.dimensions}, {
            RelationshipDimension.TRUST,
            RelationshipDimension.RESPECT,
        })

    def test_relationship_knowledge_is_explicit_and_does_not_copy_world_value(self) -> None:
        event_id = EventId("event:observed-support")
        edge = record_relationship_evidence(
            None,
            source_person_id=SOURCE,
            target_person_id=TARGET,
            dimension=RelationshipDimension.TRUST,
            delta=0.03,
            event_id=event_id,
            at=moment(1),
            direct_contact=True,
            initial_value=0.50,
        )
        knowledge = RelationshipKnowledge(
            disclosure_id="knowledge:manager-report",
            observer_id="person:manager",
            dimension=RelationshipDimension.TRUST,
            perceived_value=0.42,
            confidence=0.55,
            at=moment(2),
            supporting_event_ids=(event_id,),
        )
        informed = record_relationship_knowledge(edge, knowledge)
        world = next(item.value for item in informed.dimensions
                     if item.dimension is RelationshipDimension.TRUST)
        self.assertEqual(world, 0.53)
        self.assertEqual(informed.observer_knowledge[0].perceived_value, 0.42)
        self.assertEqual(informed.observer_knowledge[0].confidence, 0.55)
        self.assertIs(record_relationship_knowledge(informed, knowledge), informed)
        self.assertEqual(loads(dumps(informed), type(informed)), informed)
        with self.assertRaisesRegex(ValueError, "cite evidence"):
            record_relationship_knowledge(informed, RelationshipKnowledge(
                disclosure_id="knowledge:unsupported",
                observer_id="person:manager",
                dimension=RelationshipDimension.TRUST,
                perceived_value=0.9,
                confidence=1.0,
                at=moment(3),
                supporting_event_ids=(EventId("event:not-recorded"),),
            ))

    def test_relationship_changes_are_bounded_and_chronological(self) -> None:
        with self.assertRaisesRegex(ValueError, "relationship update delta"):
            record_relationship_evidence(
                None,
                source_person_id=SOURCE,
                target_person_id=TARGET,
                dimension=RelationshipDimension.TRUST,
                delta=0.051,
                event_id=EventId("event:too-large"),
                at=moment(1),
                direct_contact=False,
                initial_value=0.5,
            )
        edge = record_relationship_evidence(
            None,
            source_person_id=SOURCE,
            target_person_id=TARGET,
            dimension=RelationshipDimension.TRUST,
            delta=0.01,
            event_id=EventId("event:latest"),
            at=moment(3, days=1),
            direct_contact=False,
            initial_value=0.5,
        )
        with self.assertRaisesRegex(ValueError, "world chronology"):
            record_relationship_evidence(
                edge,
                source_person_id=SOURCE,
                target_person_id=TARGET,
                dimension=RelationshipDimension.TRUST,
                delta=0.01,
                event_id=EventId("event:older"),
                at=moment(4),
                direct_contact=False,
            )

    def test_awareness_appraisal_and_once_only_state_changes(self) -> None:
        history = empty_history()
        experience = new_personal_experience(
            TARGET,
            EventId("event:role-conversation"),
            moment(1),
            AwarenessBasis.REPORTED,
            moment(2),
        )
        history = record_personal_experience(history, experience)
        appraisal = PersonalAppraisal(
            assessed_at=moment(3),
            confidence=0.75,
            salience=0.80,
            adjustments=(
                PersonalAdjustment(PersonalDimension.BELONGING, 1.0, 0.5),
                PersonalAdjustment(PersonalDimension.FRUSTRATION, -0.5, 0.4),
            ),
        )
        changed = appraise_personal_experience(history, experience.experience_id, appraisal)
        values = {item.dimension: item.value for item in changed.state.dimensions}
        self.assertAlmostEqual(values[PersonalDimension.BELONGING], 0.515)
        self.assertAlmostEqual(values[PersonalDimension.FRUSTRATION], 0.494)
        self.assertEqual(values[PersonalDimension.CONFIDENCE], 0.5)
        self.assertEqual(values[PersonalDimension.MOTIVATION], 0.5)
        record = changed.experiences[0]
        self.assertEqual(record.awareness, AwarenessBasis.REPORTED)
        self.assertTrue(record.processed)
        self.assertEqual(record.state_changes[0].requested_delta, 0.015)
        self.assertEqual(record.state_changes[0].before, 0.5)
        self.assertEqual(record.state_changes[0].after, 0.515)
        self.assertIs(appraise_personal_experience(changed, experience.experience_id, appraisal), changed)
        with self.assertRaisesRegex(ValueError, "different inputs"):
            appraise_personal_experience(
                changed,
                experience.experience_id,
                PersonalAppraisal(moment(3), 1.0, 1.0, ()),
            )

    def test_same_cause_and_unseen_or_out_of_order_appraisal_cannot_double_apply(self) -> None:
        history = empty_history()
        first = new_personal_experience(
            TARGET, EventId("event:cause-1"), moment(1), AwarenessBasis.RUMOURED, moment(1)
        )
        later = new_personal_experience(
            TARGET, EventId("event:cause-2"), moment(2), AwarenessBasis.DIRECT, moment(2)
        )
        history = record_personal_experience(history, first)
        history = record_personal_experience(history, later)
        duplicate = replace(
            first,
            experience_id=ExperienceId("experience:duplicate-cause"),
            awareness=AwarenessBasis.DIRECT,
        )
        with self.assertRaisesRegex(ValueError, "cause event"):
            record_personal_experience(history, duplicate)
        with self.assertRaisesRegex(ValueError, "earlier personal experiences"):
            appraise_personal_experience(
                history,
                later.experience_id,
                PersonalAppraisal(moment(3), 1.0, 1.0, ()),
            )

    def test_aware_bases_round_trip_and_effects_clamp_at_state_bounds(self) -> None:
        baseline = PersonalState(
            TARGET,
            tuple(PersonalStateValue(
                dimension,
                0.96 if dimension is PersonalDimension.CONFIDENCE else 0.50,
            ) for dimension in sorted(PersonalDimension, key=lambda item: item.value)),
        )
        history = PersonalHistory(TARGET, baseline)
        awareness_types = (
            AwarenessBasis.DIRECT,
            AwarenessBasis.REPORTED,
            AwarenessBasis.RUMOURED,
        )
        experiences = []
        for index, awareness in enumerate(awareness_types, start=1):
            experience = new_personal_experience(
                TARGET,
                EventId(f"event:awareness-{index}"),
                moment(index),
                awareness,
                moment(index),
            )
            experiences.append(experience)
            history = record_personal_experience(history, experience)
        for index, experience in enumerate(experiences, start=4):
            history = appraise_personal_experience(
                history,
                experience.experience_id,
                PersonalAppraisal(
                    assessed_at=moment(index),
                    confidence=1.0,
                    salience=1.0,
                    adjustments=(PersonalAdjustment(PersonalDimension.CONFIDENCE, 1.0, 1.0),),
                ),
            )
        self.assertEqual(tuple(item.awareness for item in history.experiences), awareness_types)
        confidence_change = history.experiences[-1].state_changes[0]
        self.assertEqual(confidence_change.after, 1.0)
        self.assertEqual(confidence_change.applied_delta, 0.0)
        restored_history = loads(dumps(history), PersonalHistory)
        self.assertEqual(restored_history, history)

    def test_experience_and_relationship_records_round_trip(self) -> None:
        history = empty_history()
        experience = new_personal_experience(
            TARGET,
            EventId("event:round-trip"),
            moment(1),
            AwarenessBasis.DIRECT,
            moment(1),
        )
        history = record_personal_experience(history, experience)
        restored = loads(dumps(history), PersonalHistory)
        self.assertEqual(restored, history)

        edge = record_relationship_evidence(
            None,
            source_person_id=SOURCE,
            target_person_id=TARGET,
            dimension=RelationshipDimension.RESPECT,
            delta=0.01,
            event_id=EventId("event:relationship-round-trip"),
            at=moment(1),
            direct_contact=True,
            initial_value=0.60,
        )
        self.assertEqual(loads(dumps(edge), type(edge)), edge)

    def test_history_rejects_current_state_that_disagrees_with_recorded_appraisal(self) -> None:
        history = empty_history()
        experience = new_personal_experience(
            TARGET,
            EventId("event:state-consistency"),
            moment(1),
            AwarenessBasis.DIRECT,
            moment(1),
        )
        history = record_personal_experience(history, experience)
        history = appraise_personal_experience(
            history,
            experience.experience_id,
            PersonalAppraisal(
                assessed_at=moment(2),
                confidence=1.0,
                salience=1.0,
                adjustments=(PersonalAdjustment(PersonalDimension.BELONGING, 1.0, 1.0),),
            ),
        )
        bad_state = replace(
            history.state,
            dimensions=tuple(
                replace(item, value=0.99)
                if item.dimension is PersonalDimension.BELONGING else item
                for item in history.state.dimensions
            ),
        )
        with self.assertRaisesRegex(ValueError, "current personal state"):
            replace(history, state=bad_state)

        payload = json.loads(dumps(history))
        belonging = next(
            item for item in payload["payload"]["state"]["dimensions"]
            if item["dimension"] == PersonalDimension.BELONGING.value
        )
        belonging["value"] = 0.99
        with self.assertRaisesRegex(SerializationError, "domain contract"):
            loads(json.dumps(payload), PersonalHistory)

    def test_probe_is_byte_stable_across_processes_and_domain_import_is_headless(self) -> None:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable, "-m", "games.touchline.checks.relationship_probe"]
        first = subprocess.run(command, cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        second = subprocess.run(command, cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        self.assertEqual(first.stdout, second.stdout)

        headless = r"""
import builtins, io, sys
def denied(*args, **kwargs):
    raise AssertionError('domain import attempted file access')
builtins.open = denied
io.open = denied
import games.touchline.esb.people.relationships
assert 'curses' not in sys.modules
assert 'games.touchline.main' not in sys.modules
assert 'games.touchline.esb.match.engine' not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-c", headless],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
