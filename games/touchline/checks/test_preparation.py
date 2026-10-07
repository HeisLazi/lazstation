"""Mechanism tests for P09 preparation, medical histories and unit learning."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from games.touchline.checks.career_adapter_probe import build_scenario
from games.touchline.esb.career_adapter import (
    CareerMatchSession,
    SAVE_VERSION,
    VersionedCareerSave,
    load_preparation_state,
    migrate_v2_save,
    next_spatial_match_id,
    run_spatial_career_match,
    settle_spatial_career_match,
    start_spatial_career_match,
    store_preparation_state,
)
from games.touchline.esb.content.proof_roster import PLAYER_DECISION_PAIR, PROOF_SQUADS
from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import CareerId, EventId, MatchId
from games.touchline.esb.model import Capability, CapabilitySnapshot
from games.touchline.esb.people.learning import UnitFamiliarity
from games.touchline.esb.people.medical import MedicalProfile, RehabStage
from games.touchline.esb.randomness import RandomStreams
from games.touchline.esb.time import WorldDate
from games.touchline.esb.match.spatial import limits_from_profile
from games.touchline.esb.match.engine import TeamSheet
from games.touchline.esb.match.possession import PlayerState
from games.touchline.esb.world.preparation import (
    ExposureInput,
    PreparationFixture,
    PreparationPolicy,
    SelectionStatus,
    TrainingKind,
    TrainingSession,
    advance_preparation_day,
    available_training_minutes,
    create_preparation_state,
    injury_risk_for_exposure,
    prepared_profile,
    record_unit_match_experience,
    schedule_training_session,
    selection_assessment,
    selectable_profiles,
    settle_fixture_exposure,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
START = WorldDate(date(2026, 9, 24))


def day(offset: int) -> WorldDate:
    return WorldDate(START.day + timedelta(days=offset))


def _medical_set(squad, target_id, baseline: float) -> tuple[MedicalProfile, ...]:
    return tuple(
        MedicalProfile(
            profile.player_id,
            baseline if profile.player_id == target_id else 0.0,
            provenance="p09-test-fixture",
        )
        for profile in squad.players
    )


def _zero_minutes(squad, *, played_id=None, minutes=0, exertion=0.0):
    return tuple(
        ExposureInput(
            profile.player_id,
            minutes if profile.player_id == played_id else 0,
            exertion if profile.player_id == played_id else 0.0,
        )
        for profile in squad.players
    )


def _seed_with_medical_roll_below(limit: float) -> int:
    for seed in range(20_000):
        stream = RandomStreams.seeded(seed).stream("medical")
        if stream.random() < limit:
            return seed
    raise AssertionError("no test seed found within deterministic search bound")


def _with_adaptability(profile, value: float):
    capabilities = tuple(
        replace(item, normalized_value=value) if item.name == "adaptability" else item
        for item in profile.capabilities.capabilities
    )
    snapshot = replace(profile.capabilities, capabilities=capabilities)
    return replace(profile, capabilities=snapshot)


class PreparationWorkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.squad = PROOF_SQUADS[0]
        self.target = PLAYER_DECISION_PAIR[0]
        self.backup = max(
            (item for item in self.squad.players if item.player_id != self.target.player_id),
            key=lambda item: item.readiness.match_readiness,
        )
        self.first_match = MatchId("match:p09-week-one")
        self.second_match = MatchId("match:p09-week-two")
        self.state = create_preparation_state(
            career_id=CareerId("career:p09-prep-test"),
            club_id=self.squad.club_id,
            world_date=START,
            profiles=self.squad.players,
            fixtures=(
                PreparationFixture(self.first_match, day(2)),
                PreparationFixture(self.second_match, day(4)),
            ),
            medical_profiles=_medical_set(self.squad, self.target.player_id, 0.0),
            seed=714,
        )

    def test_congested_fixture_week_turns_minutes_into_a_selection_tradeoff(self) -> None:
        self.assertEqual(available_training_minutes(self.state, self.target.player_id, day(1)), 60)
        self.assertEqual(available_training_minutes(self.state, self.target.player_id, day(2)), 0)
        self.assertEqual(available_training_minutes(self.state, self.target.player_id, day(3)), 60)

        day_one_recovery = TrainingSession(
            "work:prep-before-first", day(1), (self.target.player_id,),
            TrainingKind.CONDITIONING, 60, 1.0,
        )
        prepared = schedule_training_session(self.state, day_one_recovery)
        with self.assertRaisesRegex(ValueError, "minutes left"):
            schedule_training_session(prepared, TrainingSession(
                "work:prep-overflow", day(1), (self.target.player_id,),
                TrainingKind.RECOVERY, 1, 0.0,
            ))
        self.assertEqual(len(prepared.sessions), 1)

        prepared = advance_preparation_day(prepared, day(1))
        prepared = advance_preparation_day(prepared, day(2))
        exposure = _zero_minutes(
            self.squad, played_id=self.target.player_id, minutes=90, exertion=0.8
        )
        played = settle_fixture_exposure(prepared, self.first_match, exposure)

        without_recovery = advance_preparation_day(played, day(3))
        with_recovery = schedule_training_session(played, TrainingSession(
            "work:post-match-recovery", day(3), (self.target.player_id,),
            TrainingKind.RECOVERY, 60, 0.0,
        ))
        with_recovery = advance_preparation_day(with_recovery, day(3))
        without_recovery = advance_preparation_day(without_recovery, day(4))
        with_recovery = advance_preparation_day(with_recovery, day(4))

        tired = selection_assessment(without_recovery, self.target.player_id)
        rested = selection_assessment(with_recovery, self.target.player_id)
        reserve = selection_assessment(with_recovery, self.backup.player_id)
        self.assertEqual(tired.status, SelectionStatus.CLEARED_NOT_READY)
        self.assertEqual(rested.status, SelectionStatus.SELECTABLE)
        self.assertEqual(reserve.status, SelectionStatus.SELECTABLE)
        self.assertLess(tired.match_readiness, rested.match_readiness)
        selected = selectable_profiles(
            with_recovery,
            (self.target.player_id, self.backup.player_id),
        )
        self.assertEqual(
            [profile.player_id for profile in selected],
            [self.target.player_id, self.backup.player_id],
        )
        self.assertEqual(len(with_recovery.training_results), 2)

    def test_repeated_views_and_fixture_settlement_do_not_redraw_injuries(self) -> None:
        seed = _seed_with_medical_roll_below(0.25)
        state = create_preparation_state(
            career_id=CareerId("career:p09-medical-test"),
            club_id=self.squad.club_id,
            world_date=START,
            profiles=self.squad.players,
            fixtures=(PreparationFixture(self.first_match, day(1)),),
            medical_profiles=_medical_set(self.squad, self.target.player_id, 0.25),
            seed=seed,
        )
        state = advance_preparation_day(state, day(1))
        exposure = _zero_minutes(
            self.squad, played_id=self.target.player_id, minutes=90, exertion=0.8
        )
        # Query the actual player entry rather than depending on roster order.
        target_input = next(item for item in exposure if item.player_id == self.target.player_id)
        risk = injury_risk_for_exposure(state, self.first_match, target_input)
        before = state.to_json()
        unviewed_state = type(state).from_json(before)
        draw_count = state.random_streams.stream("medical").draws
        for _ in range(4):
            self.assertEqual(
                injury_risk_for_exposure(state, self.first_match, target_input), risk
            )
            selection_assessment(state, self.target.player_id)
        self.assertEqual(state.to_json(), before)
        self.assertEqual(state.random_streams.stream("medical").draws, draw_count)

        settled = settle_fixture_exposure(state, self.first_match, exposure)
        unviewed_settlement = settle_fixture_exposure(
            unviewed_state, self.first_match, exposure
        )
        self.assertEqual(unviewed_settlement.to_json(), settled.to_json())
        self.assertEqual(settled.random_streams.stream("medical").draws, draw_count + 1)
        episode = next(item for item in settled.injury_history if item.player_id == self.target.player_id)
        assessment = selection_assessment(settled, self.target.player_id)
        self.assertEqual(episode.stage, RehabStage.ACUTE)
        self.assertEqual(assessment.status, SelectionStatus.MEDICALLY_UNAVAILABLE)
        with self.assertRaisesRegex(ValueError, "not selectable"):
            selectable_profiles(settled, (self.target.player_id,))

        replayed = settle_fixture_exposure(settled, self.first_match, exposure)
        self.assertEqual(replayed.to_json(), settled.to_json())
        self.assertEqual(replayed.random_streams.stream("medical").draws, draw_count + 1)
        with self.assertRaisesRegex(ValueError, "different minutes"):
            settle_fixture_exposure(
                settled,
                self.first_match,
                _zero_minutes(self.squad, played_id=self.target.player_id, minutes=60, exertion=0.8),
            )

    def test_rehabilitation_requires_staged_contacts_and_clearance_does_not_mean_ready(self) -> None:
        seed = _seed_with_medical_roll_below(0.25)
        fixture = MatchId("match:p09-rehab-trigger")
        state = create_preparation_state(
            career_id=CareerId("career:p09-rehab-test"),
            club_id=self.squad.club_id,
            world_date=START,
            profiles=self.squad.players,
            fixtures=(PreparationFixture(fixture, day(1)),),
            medical_profiles=_medical_set(self.squad, self.target.player_id, 0.25),
            seed=seed,
        )
        state = advance_preparation_day(state, day(1))
        state = settle_fixture_exposure(
            state,
            fixture,
            _zero_minutes(self.squad, played_id=self.target.player_id, minutes=90, exertion=0.8),
        )
        injury = next(item for item in state.injury_history if item.player_id == self.target.player_id)
        self.assertEqual(injury.stage, RehabStage.ACUTE)

        for offset in (3, 4, 5):
            state = schedule_training_session(state, TrainingSession(
                f"work:rehab-{offset}", day(offset), (self.target.player_id,),
                TrainingKind.REHABILITATION, 30, 0.1,
            ))
        for offset in (8, 9):
            state = schedule_training_session(state, TrainingSession(
                f"work:return-{offset}", day(offset), (self.target.player_id,),
                TrainingKind.RETURN_TO_PLAY, 30, 0.1,
            ))
        with self.assertRaisesRegex(ValueError, "projected rehab stage"):
            schedule_training_session(state, TrainingSession(
                "work:early-return", day(7), (self.target.player_id,),
                TrainingKind.RETURN_TO_PLAY, 30, 0.1,
            ))

        for offset in range(2, 11):
            state = advance_preparation_day(state, day(offset))
        injury = next(item for item in state.injury_history if item.player_id == self.target.player_id)
        self.assertEqual(injury.stage, RehabStage.CLEARED)
        self.assertEqual(len(injury.rehabilitation_dates), 3)
        self.assertEqual(len(injury.return_to_play_dates), 2)
        self.assertEqual(
            selection_assessment(state, self.target.player_id).status,
            SelectionStatus.CLEARED_NOT_READY,
        )
        self.assertLess(
            prepared_profile(state, self.target.player_id).readiness.match_readiness,
            state.policy.minimum_selection_readiness,
        )


class TacticalLearningTests(unittest.TestCase):
    def test_rehearsal_and_match_event_add_once_and_adaptability_only_changes_learning(self) -> None:
        original = PLAYER_DECISION_PAIR
        slow_learner = _with_adaptability(original[0], 0.1)
        fast_learner = _with_adaptability(original[1], 0.9)
        squad = (slow_learner, fast_learner)
        rehearsal_day = day(1)
        match_id = MatchId("match:p09-unit-learning")
        state = create_preparation_state(
            career_id=CareerId("career:p09-learning-test"),
            club_id=slow_learner.club_id,
            world_date=START,
            profiles=squad,
            fixtures=(PreparationFixture(match_id, day(2)),),
            medical_profiles=tuple(MedicalProfile(profile.player_id, 0.0) for profile in squad),
            seed=52,
        )
        source_session = TrainingSession(
            "work:unit-press-rehearsal",
            rehearsal_day,
            tuple(sorted((profile.player_id for profile in squad), key=str)),
            TrainingKind.UNIT_REHEARSAL,
            60,
            0.2,
            "unit:pressing-trap",
            10,
        )
        state = schedule_training_session(state, source_session)
        self.assertIs(schedule_training_session(state, source_session), state)
        state = advance_preparation_day(state, rehearsal_day)
        values = {
            item.player_id: item
            for item in state.unit_familiarities
        }
        slow_value = values[slow_learner.player_id].familiarity
        fast_value = values[fast_learner.player_id].familiarity
        self.assertGreater(fast_value, slow_value)
        self.assertEqual(len(values[slow_learner.player_id].receipts), 1)
        original_skill = {
            item.name: item.normalized_value
            for item in slow_learner.capabilities.capabilities
        }
        stored_slow = next(
            profile for profile in state.profiles
            if profile.player_id == slow_learner.player_id
        )
        self.assertEqual(
            {
                item.name: item.normalized_value
                for item in stored_slow.capabilities.capabilities
            }.get("short_passing"),
            original_skill["short_passing"],
        )

        state = advance_preparation_day(state, day(2))
        state = settle_fixture_exposure(
            state,
            match_id,
            tuple(ExposureInput(profile.player_id, 45, 0.5) for profile in squad),
        )
        event = EventEnvelope(
            event_id=EventId("event:p09-unit-pass"),
            aggregate_type="match",
            aggregate_id=str(match_id),
            sequence=4,
            kind="pass_completed",
            match_id=match_id,
            match_tick=18,
            world_date=day(2),
            payload_json="{}",
            outcome_json="{}",
        )
        state = record_unit_match_experience(
            state,
            source_event=event,
            unit_id="unit:pressing-trap",
            player_ids=tuple(profile.player_id for profile in squad),
            meaningful_repetitions=3,
        )
        after_match = {
            item.player_id: item
            for item in state.unit_familiarities
        }
        gains = {
            player_id: record.familiarity
            for player_id, record in after_match.items()
        }
        repeated = record_unit_match_experience(
            state,
            source_event=event,
            unit_id="unit:pressing-trap",
            player_ids=tuple(profile.player_id for profile in squad),
            meaningful_repetitions=3,
        )
        self.assertEqual(repeated.to_json(), state.to_json())
        with self.assertRaisesRegex(ValueError, "different repetitions"):
            record_unit_match_experience(
                repeated,
                source_event=event,
                unit_id="unit:pressing-trap",
                player_ids=tuple(profile.player_id for profile in squad),
                meaningful_repetitions=4,
            )
        self.assertGreater(
            gains[fast_learner.player_id] - fast_value,
            gains[slow_learner.player_id] - slow_value,
        )


class PreparationPersistenceAndMotionTests(unittest.TestCase):
    def test_p09_state_round_trips_in_v4_and_a_v3_envelope_upgrades_without_payload_change(self) -> None:
        legacy, _home, _away, _rules = build_scenario(seed=46)
        save = migrate_v2_save(legacy)
        squad = PROOF_SQUADS[0]
        state = create_preparation_state(
            career_id=save.career_id,
            club_id=squad.club_id,
            world_date=START,
            profiles=squad.players,
            seed=46,
        )
        state = advance_preparation_day(state, day(1))
        stored = store_preparation_state(save, state)
        restored = VersionedCareerSave.from_json(stored.to_json())
        self.assertEqual(SAVE_VERSION, 4)
        self.assertEqual(load_preparation_state(restored), state)
        self.assertEqual(restored.legacy_save, save.legacy_save)
        self.assertEqual(restored.default_engine_id, save.default_engine_id)

        old_envelope = json.loads(save.to_json())
        old_payload = dict(old_envelope["payload"])
        old_payload.pop("preparation_json")
        old_payload["save_version"] = 3
        old_envelope["payload"] = old_payload
        upgraded = VersionedCareerSave.from_json(json.dumps(old_envelope))
        self.assertEqual(upgraded.save_version, 4)
        self.assertIsNone(upgraded.preparation_json)
        self.assertEqual(upgraded.legacy_save, save.legacy_save)
        self.assertEqual(upgraded.historical_engine_labels, save.historical_engine_labels)

    def test_spatial_career_uses_p09_selection_profiles_and_settles_actual_minutes(self) -> None:
        legacy, home_sheet, away_sheet, rules = build_scenario(seed=46, half_ticks=8)
        save = migrate_v2_save(legacy)
        home_squad = PROOF_SQUADS[0]
        match_id = next_spatial_match_id(save)
        preparation = create_preparation_state(
            career_id=save.career_id,
            club_id=home_squad.club_id,
            world_date=START,
            profiles=home_squad.players,
            fixtures=(PreparationFixture(match_id, day(1)),),
            medical_profiles=tuple(MedicalProfile(profile.player_id, 0.0) for profile in home_squad.players),
            policy=PreparationPolicy(minimum_selection_readiness=0.65),
            seed=46,
        )
        preparation = advance_preparation_day(preparation, day(1))
        save = store_preparation_state(save, preparation)
        original_save_json = save.to_json()
        with self.assertRaisesRegex(ValueError, "current P09 condition snapshot"):
            start_spatial_career_match(
                save,
                home_sheet=home_sheet,
                away_sheet=away_sheet,
                seed=46,
                rules=rules,
            )
        self.assertEqual(save.to_json(), original_save_json)

        def prepare_sheet(sheet: TeamSheet) -> TeamSheet:
            starters = tuple(
                replace(
                    player,
                    profile=prepared_profile(preparation, player.profile.player_id),
                    motion=replace(
                        player.motion,
                        limits=limits_from_profile(
                            prepared_profile(preparation, player.profile.player_id)
                        ),
                    ),
                )
                for player in sheet.starters
            )
            substitutes = tuple(
                prepared_profile(preparation, profile.player_id)
                for profile in sheet.substitutes
            )
            return replace(sheet, starters=starters, substitutes=substitutes)

        started = start_spatial_career_match(
            save,
            home_sheet=prepare_sheet(home_sheet),
            away_sheet=away_sheet,
            seed=46,
            rules=rules,
        )
        finished = run_spatial_career_match(started, maximum_transitions=2_000)
        session = CareerMatchSession.from_json(finished.spatial_match_json)
        minutes = session.match.minutes_played
        exertion = {
            profile.player_id: (0.45 if minutes.get(profile.player_id, 0) > 0 else 0.0)
            for profile in home_squad.players
        }
        settled, applied = settle_spatial_career_match(
            finished,
            exertion_by_player=exertion,
        )
        self.assertTrue(applied)
        self.assertEqual(settled.default_engine_id, "touchline.legacy.v2")
        settled_preparation = load_preparation_state(settled)
        self.assertEqual(settled_preparation.completed_fixture_ids, (match_id,))
        self.assertEqual(len(settled_preparation.exposure_results), len(home_squad.players))
        self.assertEqual(
            {
                item.player_id: item.minutes_played
                for item in settled_preparation.exposure_results
            },
            {
                profile.player_id: minutes.get(profile.player_id, 0.0)
                for profile in home_squad.players
            },
        )
        replayed, was_applied = settle_spatial_career_match(
            settled,
            session,
            exertion_by_player=exertion,
        )
        self.assertFalse(was_applied)
        self.assertEqual(replayed.to_json(), settled.to_json())

    def test_readiness_and_fatigue_change_actual_spatial_motion_limits(self) -> None:
        profile = PLAYER_DECISION_PAIR[0]
        rested = replace(
            profile,
            readiness=replace(
                profile.readiness,
                match_readiness=1.0,
                accumulated_fatigue=0.0,
            ),
        )
        tired = replace(
            profile,
            readiness=replace(
                profile.readiness,
                match_readiness=0.2,
                accumulated_fatigue=0.8,
            ),
        )
        rested_limits = limits_from_profile(rested)
        tired_limits = limits_from_profile(tired)
        self.assertEqual(rested_limits.condition_factor, 1.0)
        self.assertAlmostEqual(tired_limits.condition_factor, 0.672)
        self.assertLess(tired_limits.maximum_speed_mps, rested_limits.maximum_speed_mps)
        self.assertEqual(
            {item.name: item.normalized_value for item in tired.capabilities.capabilities},
            {item.name: item.normalized_value for item in rested.capabilities.capabilities},
        )

    def test_fresh_process_import_and_same_seed_probe_are_headless_and_deterministic(self) -> None:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        import_script = r'''
import builtins, importlib, io, pathlib, sys
def blocked(*args, **kwargs): raise AssertionError("P09 import performed file I/O")
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
importlib.import_module("games.touchline.esb.world.preparation")
importlib.import_module("games.touchline.esb.career_adapter")
assert "curses" not in sys.modules
assert "termstation_ui" not in sys.modules
assert not any(name.startswith("termstation.") for name in sys.modules)
'''
        subprocess.run(
            [sys.executable, "-c", import_script],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        command = [sys.executable, "-m", "games.touchline.checks.preparation_probe", "--seed", "1729"]
        first = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)
        second = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, "")


if __name__ == "__main__":
    unittest.main()
