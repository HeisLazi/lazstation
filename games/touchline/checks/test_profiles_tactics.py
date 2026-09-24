from __future__ import annotations

from dataclasses import replace
import unittest

from games.touchline.esb.content.proof_roster import (
    PLAYER_DECISION_PAIR,
    PROOF_SQUADS,
    validate_proof_rosters,
)
from games.touchline.esb.content.proof_tactics import (
    KICKOFF_TOUCHLINE_TRAP,
    MAN_ORIENTED_PRESS,
    POSITIONAL_POSSESSION,
    PROOF_TACTICS,
    SLOTS,
)
from games.touchline.esb.model import DataProvenance, ProvenanceKind
from games.touchline.esb.people import PreferredFoot, PrimaryRole
from games.touchline.esb.serialization import dumps, loads
from games.touchline.esb.tactics import (
    AnchorReference,
    ConditionalRule,
    IndividualInstruction,
    PhasePlan,
    RelativeAnchor,
    TacticalAction,
    TacticalPhase,
    TacticDefinition,
    TacticIssueSeverity,
    Trigger,
    validate_tactic,
)


class ProofRosterTests(unittest.TestCase):
    def test_two_balanced_squads_have_depth_and_noninterchangeable_profiles(self) -> None:
        self.assertEqual(len(PROOF_SQUADS), 2)
        validation = dict(validate_proof_rosters())
        for squad in PROOF_SQUADS:
            self.assertEqual(len(squad.players), 16)
            self.assertEqual(validation[squad.name], ())
            self.assertGreaterEqual(sum(player.primary_role is PrimaryRole.GOALKEEPER for player in squad.players), 2)
            self.assertGreaterEqual(sum(player.primary_role is PrimaryRole.CENTER_BACK for player in squad.players), 2)
            self.assertGreaterEqual(sum(player.primary_role is PrimaryRole.FULLBACK for player in squad.players), 2)
            signatures = {
                (
                    player.primary_role,
                    tuple((item.name, item.normalized_value) for item in player.capabilities.capabilities),
                    tuple((item.name, item.value) for item in player.tendencies.values),
                    tuple((item.name, item.value, item.unit) for item in player.capabilities.measurements),
                )
                for player in squad.players
            }
            self.assertEqual(len(signatures), len(squad.players))
            self.assertEqual(loads(dumps(squad), type(squad)), squad)

    def test_player_01_matched_execution_profiles_differ_only_in_decision_traits(self) -> None:
        less_informed, more_informed = PLAYER_DECISION_PAIR
        self.assertIs(less_informed.primary_role, PrimaryRole.CENTRAL_MIDFIELDER)
        self.assertEqual(less_informed.preference.preferred_foot, PreferredFoot.RIGHT)
        self.assertEqual(less_informed.capabilities.measurements, more_informed.capabilities.measurements)
        self.assertEqual(less_informed.identity.physical_facts, more_informed.identity.physical_facts)
        self.assertEqual(
            (less_informed.readiness.sampled_on, less_informed.readiness.match_readiness,
             less_informed.readiness.accumulated_fatigue, less_informed.readiness.provenance),
            (more_informed.readiness.sampled_on, more_informed.readiness.match_readiness,
             more_informed.readiness.accumulated_fatigue, more_informed.readiness.provenance),
        )
        self.assertEqual(
            tuple((item.name, item.value, item.provenance) for item in less_informed.tendencies.values),
            tuple((item.name, item.value, item.provenance) for item in more_informed.tendencies.values),
        )

        left = {item.name: item.normalized_value for item in less_informed.capabilities.capabilities}
        right = {item.name: item.normalized_value for item in more_informed.capabilities.capabilities}
        self.assertEqual(left.keys(), right.keys())
        decision_traits = {"scanning", "anticipation", "decision_quality"}
        execution_traits = set(left) - decision_traits
        self.assertNotEqual({key: left[key] for key in decision_traits}, {key: right[key] for key in decision_traits})
        self.assertEqual({key: left[key] for key in execution_traits}, {key: right[key] for key in execution_traits})
        self.assertNotIn("overall", left)

    def test_provenance_never_promotes_inference_to_a_measured_history(self) -> None:
        for squad in PROOF_SQUADS:
            for player in squad.players:
                self.assertEqual(player.identity.history, ())
                self.assertIsNone(player.identity.birth_date)
                self.assertEqual(player.provenance.kind, ProvenanceKind.AUTHORED)
                for capability in player.capabilities.capabilities:
                    self.assertEqual(capability.provenance.kind, ProvenanceKind.AUTHORED)
                for measure in player.identity.physical_facts + player.capabilities.measurements:
                    self.assertEqual(measure.provenance.kind, ProvenanceKind.AUTHORED)

        inferred = DataProvenance(ProvenanceKind.INFERRED, "legacy 0-100 pace mapping")
        self.assertIsNot(inferred.kind, ProvenanceKind.MEASURED)
        with self.assertRaises(ValueError):
            DataProvenance(ProvenanceKind.MEASURED, "timing gate")


class TacticDefinitionTests(unittest.TestCase):
    def test_three_proof_families_use_shared_components_and_round_trip(self) -> None:
        self.assertEqual(len(PROOF_TACTICS), 3)
        for tactic in PROOF_TACTICS:
            issues = validate_tactic(tactic)
            self.assertFalse(
                [issue for issue in issues if issue.severity is TacticIssueSeverity.ERROR],
                f"{tactic.name}: {issues}",
            )
            self.assertEqual(loads(dumps(tactic), TacticDefinition), tactic)

        self.assertTrue(any(phase.relationships for phase in POSITIONAL_POSSESSION.phases))
        self.assertTrue(any(phase.pressing and phase.marking for phase in MAN_ORIENTED_PRESS.phases))
        kickoff = KICKOFF_TOUCHLINE_TRAP.phases[0].routines[0]
        self.assertEqual(kickoff.start_trigger, Trigger.OWN_KICKOFF)
        self.assertEqual([step.sequence for step in kickoff.steps], [0, 1, 2])
        self.assertTrue(all(step.timeout_ticks > 0 and step.fallback for step in kickoff.steps))
        self.assertTrue(kickoff.fallback)

    def test_contradictions_are_explainable_warnings_and_unknown_slots_are_errors(self) -> None:
        anchor = RelativeAnchor(AnchorReference.TEAM_SHAPE)
        conflict = PhasePlan(
            phase=TacticalPhase.BUILD_UP,
            instructions=(
                IndividualInstruction("LW", (TacticalAction.HOLD_WIDTH,), anchor),
                IndividualInstruction("LW", (TacticalAction.MOVE_INSIDE,), anchor),
            ),
        )
        tactic = TacticDefinition(
            POSITIONAL_POSSESSION.tactic_id,
            "Conflict example",
            SLOTS,
            (conflict,),
        )
        issues = validate_tactic(tactic)
        warning = next(issue for issue in issues if issue.code == "same_priority_conflict")
        self.assertIs(warning.severity, TacticIssueSeverity.WARNING)
        self.assertIn("LW", warning.message)

        unknown_slot_plan = replace(
            conflict,
            instructions=(IndividualInstruction("UNDECLARED", (TacticalAction.SUPPORT,)),),
        )
        unknown_tactic = replace(tactic, phases=(unknown_slot_plan,))
        errors = validate_tactic(unknown_tactic)
        self.assertTrue(any(issue.code == "unknown_slot" and issue.severity is TacticIssueSeverity.ERROR for issue in errors))

    def test_conditions_require_fallback_expiry_and_valid_relative_frames(self) -> None:
        with self.assertRaises(ValueError):
            ConditionalRule(
                "no-fallback",
                Trigger.POOR_TOUCH,
                1,
                10,
                Trigger.OPPONENT_ESCAPES_PRESS,
                (IndividualInstruction("LW", (TacticalAction.PRESS_RECEIVER,)),),
                (),
            )
        with self.assertRaises(ValueError):
            RelativeAnchor(AnchorReference.TEAMMATE)
        with self.assertRaises(ValueError):
            RelativeAnchor(AnchorReference.TEAM_SHAPE, longitudinal_offset_m=float("inf"))


if __name__ == "__main__":
    unittest.main()
