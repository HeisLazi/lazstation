"""Mechanism tests for P16b cross-competition condition flow."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from games.touchline.esb.content.proof_world import proof_world_flow_state, proof_world_schedule
from games.touchline.esb.ids import derive_id
from games.touchline.esb.match.engine import create_match, run_to_completion
from games.touchline.esb.match.spatial import limits_from_profile
from games.touchline.esb.model import DataProvenance, ProvenanceKind
from games.touchline.esb.people.medical import InjuryEpisode, MedicalProfile, RehabStage
from games.touchline.esb.randomness import RandomStreams
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.archive import WorldArchiveStore, WorldMatchRecord
from games.touchline.esb.world.competition_flow import (
    AvailabilityStatus,
    CallUpDecision,
    NationalSelectionBook,
    WorldCompetitionState,
    WorldExposureResolution,
    WorldFlowCheckpoint,
    WorldFixtureIneligible,
    _condition_snapshot_sha256,
    _conditioned_fixture,
    _settle_fixture,
    _injury_episode_is_known_by,
    advance_world_condition_to,
    assess_fixture_selections,
    create_world_competition_state,
    flow_snapshot_sha256,
    offer_national_call_up,
    respond_to_national_call_up,
    WorldFixtureSettlement,
    simulate_world_season,
)
from games.touchline.esb.world.season import (
    fixture_input_sha256,
    fixture_seed,
    immutable_snapshot_json,
    simulate_fixture,
)


class CompetitionFlowTests(unittest.TestCase):
    def setUp(self):
        self.schedule = proof_world_schedule(half_ticks=2)
        self.initial = proof_world_flow_state(self.schedule)
        self.fixture = self.schedule.ordered_fixtures[0]

    def _state(self, *, profiles=None, registration=None, selection=None,
               initial_injuries=(), medical_profiles=None, seed=None):
        if medical_profiles is None:
            medical_profiles = tuple(item.medical_profile for item in self.initial.conditions)
        return create_world_competition_state(
            self.schedule,
            profiles=tuple(self.initial.profiles if profiles is None else profiles),
            registration=(self.initial.registration if registration is None else registration),
            national_selection=(self.initial.national_selection if selection is None else selection),
            starting_on=self.initial.starting_on,
            seed=self.initial.seed if seed is None else seed,
            medical_profiles=tuple(medical_profiles),
            initial_injuries=tuple(initial_injuries),
            policy=self.initial.policy,
            match_exertion=self.initial.match_exertion,
        )

    def _temporary_archive(self):
        return tempfile.TemporaryDirectory(prefix="touchline-p16b-test-")

    def test_versioned_flow_state_round_trips_and_checkpoint_is_bounded(self):
        restored = WorldCompetitionState.from_json(self.initial.to_json())
        self.assertEqual(restored, self.initial)
        self.assertEqual(WorldCompetitionState.from_json(restored.to_json()).state_sha256,
                         self.initial.state_sha256)
        self.assertEqual(self.initial.checkpoint().revision, 0)
        broken = json.loads(self.initial.to_json())
        broken["payload"]["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "invalid world competition-flow state"):
            WorldCompetitionState.from_json(json.dumps(broken))

    def test_initial_checkpoint_values_are_fully_derived_from_hashed_inputs(self):
        original = self.initial.conditions[0]
        changed_condition = replace(original, match_readiness=max(0.0, original.match_readiness - 0.1))
        conditions = tuple(changed_condition if item.player_id == original.player_id else item
                           for item in self.initial.conditions)
        with self.assertRaisesRegex(ValueError, "unsettled world conditions"):
            replace(self.initial, conditions=conditions)

        extra_injury = InjuryEpisode(
            "injury:p16b-unhashed-initial", original.player_id,
            "world-exposure:p16b-unhashed-initial", self.initial.starting_on,
        )
        with self.assertRaisesRegex(ValueError, "unsettled world injury history"):
            replace(self.initial, injury_history=(extra_injury,))

        changed_streams = loads(dumps(self.initial.random_streams), RandomStreams)
        changed_streams.stream("medical").random()
        with self.assertRaisesRegex(ValueError, "initial world random streams"):
            replace(self.initial, random_streams=changed_streams)

        later_date = WorldDate(self.initial.starting_on.day + timedelta(days=1))
        with self.assertRaisesRegex(ValueError, "unsettled world conditions"):
            replace(self.initial, world_date=later_date)
        recovered = advance_world_condition_to(self.initial, later_date)
        self.assertEqual(self.initial.flow_inputs().restore_checkpoint(recovered.checkpoint()), recovered)

        encoded = json.loads(self.initial.to_json())
        encoded["payload"]["conditions"][0]["match_readiness"] = changed_condition.match_readiness
        with self.assertRaisesRegex(ValueError, "invalid world competition-flow state"):
            WorldCompetitionState.from_json(json.dumps(encoded))

        forged_checkpoint = replace(self.initial.checkpoint(), conditions=conditions)
        with self.assertRaisesRegex(ValueError, "unsettled world conditions"):
            self.initial.flow_inputs().restore_checkpoint(forged_checkpoint)
        forged_checkpoint = replace(self.initial.checkpoint(), world_date=later_date)
        with self.assertRaisesRegex(ValueError, "unsettled world conditions"):
            self.initial.flow_inputs().restore_checkpoint(forged_checkpoint)

    def test_old_readiness_samples_recover_to_start_and_future_evidence_is_rejected(self):
        profile = self.initial.profiles[0]
        sampled_on = WorldDate(self.initial.starting_on.day - timedelta(days=5))
        readiness = replace(
            profile.readiness,
            sampled_on=sampled_on,
            match_readiness=0.45,
            accumulated_fatigue=0.4,
        )
        older_profile = replace(profile, readiness=readiness)
        profiles = tuple(older_profile if item.player_id == profile.player_id else item
                         for item in self.initial.profiles)
        state = self._state(profiles=profiles)
        condition = next(item for item in state.conditions if item.player_id == profile.player_id)
        self.assertAlmostEqual(
            condition.match_readiness,
            min(1.0, 0.45 + 5 * state.policy.daily_readiness_recovery),
        )
        self.assertAlmostEqual(
            condition.accumulated_fatigue,
            max(0.0, 0.4 - 5 * state.policy.daily_fatigue_recovery),
        )

        future_sampled_profile = replace(
            profile,
            readiness=replace(
                profile.readiness,
                sampled_on=WorldDate(self.initial.starting_on.day + timedelta(days=1)),
            ),
        )
        invalid_profiles = tuple(future_sampled_profile if item.player_id == profile.player_id else item
                                 for item in self.initial.profiles)
        with self.assertRaisesRegex(ValueError, "future readiness evidence"):
            self._state(profiles=invalid_profiles)

        future_evidence = replace(
            profile,
            readiness=replace(
                profile.readiness,
                provenance=DataProvenance(
                    ProvenanceKind.AUTHORED,
                    "test:future-readiness-evidence",
                    WorldDate(profile.readiness.sampled_on.day + timedelta(days=1)),
                ),
            ),
        )
        invalid_evidence_profiles = tuple(
            future_evidence if item.player_id == profile.player_id else item
            for item in self.initial.profiles
        )
        with self.assertRaisesRegex(ValueError, "evidence date cannot follow"):
            self._state(profiles=invalid_evidence_profiles)

        encoded = json.loads(self.initial.to_json())
        encoded_profile = next(
            item for item in encoded["payload"]["profiles"]
            if item["player_id"] == str(profile.player_id)
        )
        encoded_profile["readiness"]["sampled_on"] = {
            "day": WorldDate(self.initial.starting_on.day + timedelta(days=1)).isoformat,
        }
        with self.assertRaisesRegex(ValueError, "invalid world competition-flow state"):
            WorldCompetitionState.from_json(json.dumps(encoded))

        encoded = json.loads(self.initial.to_json())
        encoded_profile = next(
            item for item in encoded["payload"]["profiles"]
            if item["player_id"] == str(profile.player_id)
        )
        encoded_profile["readiness"]["provenance"]["evidence_date"] = {
            "day": WorldDate(profile.readiness.sampled_on.day + timedelta(days=1)).isoformat,
        }
        with self.assertRaisesRegex(ValueError, "invalid world competition-flow state"):
            WorldCompetitionState.from_json(json.dumps(encoded))

    def test_initial_injury_dates_cannot_use_future_rehab_contacts(self):
        player_id = self.initial.profiles[0].player_id
        occurred_on = WorldDate(self.initial.starting_on.day - timedelta(days=12))
        valid = InjuryEpisode(
            "injury:p16b-dated-rehab", player_id, "world-exposure:p16b-dated-rehab",
            occurred_on, RehabStage.RETURN_TO_PLAY,
            WorldDate(self.initial.starting_on.day - timedelta(days=5)),
            (
                WorldDate(self.initial.starting_on.day - timedelta(days=8)),
                WorldDate(self.initial.starting_on.day - timedelta(days=7)),
                WorldDate(self.initial.starting_on.day - timedelta(days=6)),
            ),
        )
        future_contact = replace(
            valid,
            return_to_play_dates=(
                WorldDate(self.initial.starting_on.day + timedelta(days=1)),
            ),
        )
        with self.assertRaisesRegex(ValueError, "fully dated by the start"):
            self._state(initial_injuries=(future_contact,))
        pre_stage_contacts = replace(valid, rehabilitation_dates=(
            WorldDate(self.initial.starting_on.day - timedelta(days=11)),
            *valid.rehabilitation_dates[1:],
        ))
        with self.assertRaisesRegex(ValueError, "fully dated by the start"):
            self._state(initial_injuries=(pre_stage_contacts,))
        stale_stage = replace(
            valid, stage=RehabStage.REHABILITATION,
            stage_started_on=WorldDate(occurred_on.day + timedelta(days=2)),
            return_to_play_dates=(),
        )
        with self.assertRaisesRegex(ValueError, "fully dated by the start"):
            self._state(initial_injuries=(stale_stage,))

        profile = next(item for item in self.initial.profiles if item.player_id == player_id)
        old_sample = WorldDate(self.initial.starting_on.day - timedelta(days=1))
        low_readiness = replace(profile, readiness=replace(
            profile.readiness,
            sampled_on=old_sample,
            match_readiness=0.8,
        ))
        profiles = tuple(low_readiness if item.player_id == player_id else item
                         for item in self.initial.profiles)
        injury_on_start = InjuryEpisode(
            "injury:p16b-readiness-loss", player_id,
            "world-exposure:p16b-readiness-loss", self.initial.starting_on,
        )
        injured_state = self._state(profiles=profiles, initial_injuries=(injury_on_start,))
        injured_condition = next(item for item in injured_state.conditions if item.player_id == player_id)
        self.assertAlmostEqual(
            injured_condition.match_readiness,
            max(0.0, 0.8 - injured_state.policy.injury_readiness_loss),
        )

        state = self._state(initial_injuries=(valid,))
        future_stage_date = WorldDate(self.initial.starting_on.day + timedelta(days=1))
        encoded = json.loads(state.to_json())
        encoded["payload"]["initial_injuries"][0]["stage_started_on"] = {
            "day": future_stage_date.isoformat,
        }
        encoded["payload"]["injury_history"][0]["stage_started_on"] = {
            "day": future_stage_date.isoformat,
        }
        with self.assertRaisesRegex(ValueError, "invalid world competition-flow state"):
            WorldCompetitionState.from_json(json.dumps(encoded))
        future_episode = replace(valid, stage_started_on=future_stage_date)
        with self.assertRaisesRegex(ValueError, "no later than its date"):
            replace(state.checkpoint(), injury_history=(future_episode,))

    def test_injury_chronology_accepts_the_last_world_date(self):
        player_id = self.initial.profiles[0].player_id
        last_day = WorldDate(date.max)
        injury = InjuryEpisode(
            "injury:p16b-last-calendar-day", player_id,
            "world-exposure:p16b-last-calendar-day", last_day,
        )
        self.assertTrue(_injury_episode_is_known_by(injury, last_day))

    def test_club_players_need_current_competition_registration(self):
        registration = replace(
            self.initial.registration,
            squads=tuple(item for item in self.initial.registration.squads
                         if not (item.competition_id == self.fixture.competition_id
                                 and item.club_id == self.fixture.home_participant_id)),
        )
        state = self._state(registration=registration)
        decisions = assess_fixture_selections(state, self.schedule, self.fixture)
        home_ids = ({item.profile.player_id for item in self.fixture.home_sheet.starters}
                    | {item.player_id for item in self.fixture.home_sheet.substitutes})
        denied = tuple(item for item in decisions if item.player_id in home_ids)
        self.assertEqual(len(denied), len(home_ids))
        self.assertTrue(all(not item.eligible and "not_currently_registered" in item.reasons
                            for item in denied))
        self.assertTrue(all(item.registration_check_id for item in denied))

    def test_missing_declined_and_fixture_date_conflicting_callups_block_representative_players(self):
        fixture = next(item for item in self.schedule.fixtures
                       if item.competition_id == "competition:proof-representative")
        first_offer = self.initial.national_selection.call_ups[0]

        missing = self._state(selection=NationalSelectionBook(self.initial.national_selection.eligibility))
        missing = advance_world_condition_to(missing, fixture.scheduled_on)
        missing_decisions = assess_fixture_selections(missing, self.schedule, fixture)
        self.assertTrue(all("call_up_missing" in item.reasons for item in missing_decisions))

        pending_book = replace(
            self.initial.national_selection,
            call_ups=tuple(replace(item, decision=None, responded_on=None)
                           if item.offer_id == first_offer.offer_id else item
                           for item in self.initial.national_selection.call_ups),
        )
        declined_book = respond_to_national_call_up(
            pending_book, first_offer.offer_id,
            CallUpDecision.DECLINED, first_offer.responded_on,
        )
        declined = advance_world_condition_to(self._state(selection=declined_book), fixture.scheduled_on)
        declined_decisions = assess_fixture_selections(declined, self.schedule, fixture)
        self.assertIn("call_up_not_accepted", next(
            item.reasons for item in declined_decisions if item.player_id == first_offer.player_id
        ))

        wrong_date = replace(first_offer, fixture_on=WorldDate(first_offer.fixture_on.day + timedelta(days=1)))
        date_book = replace(
            self.initial.national_selection,
            call_ups=tuple(wrong_date if item.offer_id == first_offer.offer_id else item
                           for item in self.initial.national_selection.call_ups),
        )
        date_conflict = advance_world_condition_to(self._state(selection=date_book), fixture.scheduled_on)
        date_decisions = assess_fixture_selections(date_conflict, self.schedule, fixture)
        self.assertIn("call_up_fixture_date_mismatch", next(
            item.reasons for item in date_decisions if item.player_id == first_offer.player_id
        ))

    def test_callup_retries_are_idempotent_and_late_or_conflicting_responses_reject(self):
        fixture = next(item for item in self.schedule.fixtures
                       if item.competition_id == "competition:proof-representative")
        offer = self.initial.national_selection.call_ups[0]
        same = offer_national_call_up(
            self.initial.national_selection, self.schedule, player_id=offer.player_id,
            fixture_id=fixture.fixture_id, offered_on=offer.offered_on,
            response_by=offer.response_by,
        )
        self.assertEqual(same, self.initial.national_selection)
        self.assertEqual(respond_to_national_call_up(
            same, offer.offer_id, CallUpDecision.ACCEPTED, offer.responded_on,
        ), same)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            respond_to_national_call_up(
                same, offer.offer_id, CallUpDecision.DECLINED, offer.responded_on,
            )
        with self.assertRaisesRegex(ValueError, "outside"):
            respond_to_national_call_up(
                NationalSelectionBook(self.initial.national_selection.eligibility,
                                      tuple(replace(item, decision=None, responded_on=None)
                                            if item.offer_id == offer.offer_id else item
                                            for item in same.call_ups)),
                offer.offer_id, CallUpDecision.ACCEPTED,
                WorldDate(offer.response_by.day + timedelta(days=1)),
            )

    def test_active_injury_and_low_readiness_block_selection(self):
        profile = self.fixture.home_sheet.starters[0].profile
        injury = InjuryEpisode(
            "injury:p16b-starting-player", profile.player_id,
            "world-exposure:p16b-pre-season", self.initial.starting_on,
        )
        state = self._state(initial_injuries=(injury,))
        decision = next(item for item in assess_fixture_selections(state, self.schedule, self.fixture)
                        if item.player_id == profile.player_id)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.availability, AvailabilityStatus.MEDICALLY_UNAVAILABLE)
        self.assertIn("active_injury", decision.reasons)

        low_profile = replace(profile, readiness=replace(
            profile.readiness, match_readiness=0.1,
        ))
        profiles = tuple(low_profile if item.player_id == profile.player_id else item
                         for item in self.initial.profiles)
        low_state = self._state(profiles=profiles)
        low_decision = next(item for item in assess_fixture_selections(low_state, self.schedule, self.fixture)
                            if item.player_id == profile.player_id)
        self.assertFalse(low_decision.eligible)
        self.assertEqual(low_decision.availability, AvailabilityStatus.BELOW_SELECTION_READINESS)
        self.assertIn("below_selection_readiness", low_decision.reasons)

    def test_successful_medical_draw_requires_lineaged_injury_id_in_objects_and_codec(self):
        player_id = self.fixture.home_sheet.starters[0].profile.player_id
        exposure_id = derive_id(
            "world-exposure", "p16b-match-exposure-v1",
            self.fixture.fixture_id, self.fixture.match_id, player_id,
        )
        injury_id = derive_id("world-injury", "p16b-match-injury-v1", exposure_id)
        valid = WorldExposureResolution(
            self.fixture.fixture_id, self.fixture.match_id, player_id,
            self.fixture.scheduled_on, 90.0, 0.5, 0.2, 0.1,
            exposure_id, injury_id, "a" * 64,
        )
        with self.assertRaisesRegex(ValueError, "successful injury draw"):
            WorldExposureResolution(
                self.fixture.fixture_id, self.fixture.match_id, player_id,
                self.fixture.scheduled_on, 90.0, 0.5, 0.2, 0.1,
                exposure_id, None, "a" * 64,
            )
        encoded = json.loads(dumps(valid))
        encoded["payload"]["injury_id"] = None
        with self.assertRaises(SerializationError):
            loads(json.dumps(encoded), WorldExposureResolution)
        with self.assertRaisesRegex(ValueError, r"injury probability.*\[0, 0\.25\]"):
            replace(valid, injury_probability=0.5, injury_roll=0.75)
        encoded = json.loads(dumps(valid))
        encoded["payload"]["injury_probability"] = 0.5
        with self.assertRaises(SerializationError):
            loads(json.dumps(encoded), WorldExposureResolution)

    def test_dated_recovery_advances_readiness_fatigue_and_medical_stage(self):
        profile = self.fixture.home_sheet.starters[0].profile
        injured_on = WorldDate(self.initial.starting_on.day - timedelta(days=1))
        injury = InjuryEpisode("injury:p16b-recovery", profile.player_id,
                               "world-exposure:p16b-recovery-source", injured_on)
        state = self._state(initial_injuries=(injury,))
        condition_before = next(item for item in state.conditions if item.player_id == profile.player_id)
        target = WorldDate(self.initial.starting_on.day + timedelta(days=2))
        recovered = advance_world_condition_to(state, target)
        condition_after = next(item for item in recovered.conditions if item.player_id == profile.player_id)
        expected_readiness = min(
            1.0, condition_before.match_readiness
            + 2 * self.initial.policy.injured_daily_readiness_recovery,
        )
        expected_fatigue = max(
            0.0, condition_before.accumulated_fatigue
            - 2 * self.initial.policy.daily_fatigue_recovery,
        )
        self.assertAlmostEqual(condition_after.match_readiness, expected_readiness, places=6)
        self.assertAlmostEqual(condition_after.accumulated_fatigue, expected_fatigue)
        self.assertEqual(recovered.injury_history[0].stage, RehabStage.REHABILITATION)
        with self.assertRaisesRegex(ValueError, "backward"):
            advance_world_condition_to(recovered, self.initial.starting_on)

    def test_current_condition_is_snapshotted_into_match_profile_and_p05_motion_limits(self):
        progress, updated = self._simulate(self.initial, maximum_fixtures=1)
        self.assertEqual(progress.archived, 1)
        fixture = self.schedule.ordered_fixtures[1]
        current = advance_world_condition_to(updated, fixture.scheduled_on)
        effective = _conditioned_fixture(current, fixture)
        profiles = {item.player_id: item for item in current.conditions}
        for sheet in (effective.home_sheet, effective.away_sheet):
            for player in sheet.starters:
                condition = profiles[player.profile.player_id]
                self.assertEqual(player.profile.readiness.match_readiness,
                                 condition.match_readiness)
                self.assertEqual(player.profile.readiness.accumulated_fatigue,
                                 condition.accumulated_fatigue)
                self.assertEqual(player.motion.limits, limits_from_profile(player.profile))
        self.assertGreater(updated.revision, 0)

    def test_minutes_condition_and_all_roster_exposure_rows_reconcile_across_competitions(self):
        with self._temporary_archive() as temporary:
            path = Path(temporary) / "world.sqlite3"
            with WorldArchiveStore(path) as archive:
                progress, final = simulate_world_season(self.schedule, self.initial, archive)
                self.assertEqual((progress.archived, progress.pending), (4, 0))
                self.assertEqual(final.revision, 4)
                for profile in self.initial.profiles:
                    history = archive.world_player_exposure_history(profile.player_id)
                    self.assertEqual(len(history), 4)
                    self.assertEqual(tuple(item.fixture_id for item in history),
                                     tuple(item.fixture_id for item in self.schedule.ordered_fixtures))
                    self.assertEqual(len({item.exposure_id for item in history}), 4)
                first = self.schedule.ordered_fixtures[0]
                lines = {}
                for profile in self.initial.profiles:
                    history = archive.player_match_history(profile.player_id)
                    line = next((item for item in history if item.fixture_id == first.fixture_id), None)
                    if line is not None:
                        lines[profile.player_id] = line
                first_exposures = tuple(item for item in archive.world_player_exposure_history(
                    self.initial.profiles[0].player_id
                ) if item.fixture_id == first.fixture_id)
                self.assertEqual(len(first_exposures), 1)
                exposed = first_exposures[0]
                self.assertEqual(exposed.minutes_played,
                                 lines[exposed.player_id].minutes_played
                                 if exposed.player_id in lines else 0.0)
                unused = next(item for item in archive.world_player_exposure_history(
                    next(profile.player_id for profile in self.initial.profiles
                         if profile.player_id not in first.named_player_ids)
                ) if item.fixture_id == first.fixture_id)
                self.assertEqual((unused.minutes_played, unused.exertion,
                                  unused.injury_probability, unused.injury_roll), (0, 0, 0, None))
                summaries = [archive.match_summary(item.match_id) for item in self.schedule.ordered_fixtures]
                self.assertEqual(len(summaries), 4)
                self.assertEqual(len(final.injury_history), 0)

    def test_flow_resume_rejects_changed_initial_inputs_and_does_not_repeat_fixtures(self):
        with self._temporary_archive() as temporary:
            path = Path(temporary) / "resume.sqlite3"
            with WorldArchiveStore(path) as archive:
                first, state = simulate_world_season(self.schedule, self.initial, archive,
                                                     maximum_fixtures=1)
                self.assertEqual((first.simulated_this_run, first.pending), (1, 3))
            codec_restored = WorldCompetitionState.from_json(self.initial.to_json())
            self.assertEqual(codec_restored.inputs_sha256, self.initial.inputs_sha256)
            with WorldArchiveStore(path) as archive:
                resumed, state = simulate_world_season(self.schedule, codec_restored, archive)
                self.assertEqual((resumed.simulated_this_run, resumed.resumed_this_run,
                                  resumed.pending), (3, 1, 0))
                replay, _ = simulate_world_season(self.schedule, codec_restored, archive)
                self.assertEqual((replay.simulated_this_run, replay.resumed_this_run), (0, 4))
            changed = self._state(seed=self.initial.seed + 1)
            with WorldArchiveStore(path) as archive:
                with self.assertRaisesRegex(ValueError, "immutable inputs conflict"):
                    simulate_world_season(self.schedule, changed, archive)

    def test_match_exposure_and_checkpoint_commit_atomically(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "atomic.sqlite3") as archive:
            archive.initialize_world_flow(self.schedule, self.initial)
            fixture = self.schedule.ordered_fixtures[0]
            state = advance_world_condition_to(self.initial, fixture.scheduled_on)
            effective = _conditioned_fixture(state, fixture)
            competition = self.schedule.competition(fixture.competition_id)
            match = create_match(effective.home_sheet, effective.away_sheet,
                                 rules=competition.rules,
                                 seed=fixture_seed(self.schedule, fixture),
                                 match_id=fixture.match_id)
            run_to_completion(match)
            record = WorldMatchRecord.create(self.schedule, fixture, match)
            updated, exposures, settlement = _settle_fixture(
                state, self.schedule, fixture, record, _condition_snapshot_sha256(state),
            )
            archive.connection.execute(
                "CREATE TRIGGER reject_flow_exposure BEFORE INSERT ON world_flow_exposures "
                "BEGIN SELECT RAISE(ABORT, 'forced exposure insert failure'); END"
            )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "forced exposure"):
                archive.append_with_world_flow(
                    record, updated, exposures, settlement,
                    expected_previous_state_sha256=self.initial.state_sha256,
                )
            self.assertEqual(archive.connection.execute("SELECT COUNT(*) FROM archived_matches").fetchone()[0], 0)
            self.assertEqual(archive.connection.execute("SELECT COUNT(*) FROM archived_events").fetchone()[0], 0)
            self.assertEqual(archive.world_flow_fixture_ids(), ())
            checkpoint = json.loads(archive.connection.execute(
                "SELECT checkpoint_json FROM world_flow_state WHERE singleton = 1"
            ).fetchone()[0])
            self.assertEqual(checkpoint["payload"]["revision"], 0)

    def test_mutated_revision_zero_medical_stream_cannot_initialize_archive(self):
        changed = proof_world_flow_state(self.schedule)
        changed.random_streams.stream("medical").random()
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "mutated-rng.sqlite3") as archive:
            with self.assertRaisesRegex(ValueError, "initial world random streams"):
                archive.initialize_world_flow(self.schedule, changed)
            self.assertEqual(archive.connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0], 0)

    def test_flow_start_after_first_fixture_is_rejected_before_archive_creation(self):
        later = WorldDate(self.initial.starting_on.day + timedelta(days=1))
        recovered = advance_world_condition_to(self.initial, later)
        updated_inputs = replace(self.initial.flow_inputs(), starting_on=later)
        late_state = replace(
            recovered,
            starting_on=later,
            initial_state_sha256=updated_inputs.inputs_sha256,
        )
        self.assertEqual(late_state.initial_state_sha256, late_state.flow_inputs().inputs_sha256)
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "late-start.sqlite3") as archive:
            with self.assertRaisesRegex(ValueError, "cannot follow the first scheduled fixture"):
                archive.initialize_world_flow(self.schedule, late_state)
            self.assertEqual(archive.connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0], 0)

    def test_direct_initial_state_cannot_attach_profiles_that_conflict_with_schedule(self):
        original = self.initial.profiles[0]
        changed = replace(original, display_name=f"{original.display_name} changed")
        profiles = tuple(changed if item.player_id == original.player_id else item
                         for item in self.initial.profiles)
        changed_inputs = replace(self.initial.flow_inputs(), profiles=profiles)
        mismatched = replace(
            self.initial,
            profiles=profiles,
            initial_state_sha256=changed_inputs.inputs_sha256,
        )
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "wrong-profiles.sqlite3") as archive:
            with self.assertRaisesRegex(ValueError, "differs from the immutable world catalog"):
                archive.initialize_world_flow(self.schedule, mismatched)
            self.assertEqual(archive.connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0], 0)

    def test_plain_match_append_cannot_split_an_attached_flow_season(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "append-boundary.sqlite3") as archive:
            first, _ = simulate_world_season(
                self.schedule, self.initial, archive, maximum_fixtures=1,
            )
            self.assertEqual(first.archived, 1)
            next_fixture = self.schedule.ordered_fixtures[1]
            next_record = WorldMatchRecord.create(
                self.schedule, next_fixture, simulate_fixture(self.schedule, next_fixture),
            )
            with self.assertRaisesRegex(ValueError, "require match, exposure and checkpoint"):
                archive.append(next_record)
            self.assertEqual(archive.connection.execute(
                "SELECT COUNT(*) FROM archived_matches"
            ).fetchone()[0], 1)
            self.assertEqual(archive.world_flow_fixture_ids(), (self.fixture.fixture_id,))

    def test_append_rejects_exposure_minutes_that_contradict_match_lines(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "forged.sqlite3") as archive:
            archive.initialize_world_flow(self.schedule, self.initial)
            fixture = self.fixture
            state = advance_world_condition_to(self.initial, fixture.scheduled_on)
            effective = _conditioned_fixture(state, fixture)
            competition = self.schedule.competition(fixture.competition_id)
            match = create_match(
                effective.home_sheet, effective.away_sheet, rules=competition.rules,
                seed=fixture_seed(self.schedule, fixture), match_id=fixture.match_id,
            )
            run_to_completion(match)
            record = WorldMatchRecord.create(self.schedule, fixture, match)
            updated, exposures, settlement = _settle_fixture(
                state, self.schedule, fixture, record, _condition_snapshot_sha256(state),
            )
            forged = replace(exposures[0], minutes_played=exposures[0].minutes_played + 1.0)
            forged_exposures = (forged, *exposures[1:])
            forged_hash = flow_snapshot_sha256(forged_exposures)
            forged_settlement = replace(settlement, exposure_sha256=forged_hash)
            forged_updated = replace(updated, last_exposure_sha256=forged_hash)

            with self.assertRaisesRegex(ValueError, "does not reconcile to the prior checkpoint"):
                archive.append_with_world_flow(
                    record, forged_updated, forged_exposures, forged_settlement,
                    expected_previous_state_sha256=self.initial.state_sha256,
                )
            self.assertEqual(archive.connection.execute(
                "SELECT COUNT(*) FROM archived_matches"
            ).fetchone()[0], 0)
            self.assertEqual(archive.world_flow_fixture_ids(), ())
            checkpoint = WorldFlowCheckpoint.from_json(archive.connection.execute(
                "SELECT checkpoint_json FROM world_flow_state WHERE singleton = 1"
            ).fetchone()[0])
            self.assertEqual(checkpoint.revision, 0)

    def test_archived_match_rejects_forged_player_ticks_after_hash_and_lines_are_recomputed(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "forged-minutes.sqlite3") as archive:
            archive.initialize_world_flow(self.schedule, self.initial)
            fixture = self.fixture
            state = advance_world_condition_to(self.initial, fixture.scheduled_on)
            effective = _conditioned_fixture(state, fixture)
            competition = self.schedule.competition(fixture.competition_id)
            match = create_match(
                effective.home_sheet, effective.away_sheet, rules=competition.rules,
                seed=fixture_seed(self.schedule, fixture), match_id=fixture.match_id,
            )
            run_to_completion(match)
            record = WorldMatchRecord.create(self.schedule, fixture, match)

            forged_match = record.match_state()
            player_id = fixture.home_sheet.starters[0].profile.player_id
            ticks_per_minute, remainder = divmod(60_000, forged_match.rules.tick_duration_ms)
            self.assertEqual(remainder, 0)
            forged_match.playing_ticks[player_id] += ticks_per_minute
            forged_json = forged_match.to_json()
            forged_lines = tuple(
                replace(
                    line,
                    minutes_played=(
                        line.minutes_played + ticks_per_minute * forged_match.rules.tick_duration_ms / 60_000
                        if line.player_id == player_id else line.minutes_played
                    ),
                )
                for line in record.player_lines
            )

            with self.assertRaisesRegex(ValueError, "playing-time totals do not reconcile"):
                replace(
                    record,
                    match_state_json=forged_json,
                    state_sha256=hashlib.sha256(forged_json.encode("utf-8")).hexdigest(),
                    player_lines=forged_lines,
                )
            self.assertEqual(archive.connection.execute(
                "SELECT COUNT(*) FROM archived_matches"
            ).fetchone()[0], 0)

    def test_direct_flow_append_rejects_a_rehashed_tampered_schedule(self):
        fixture = self.fixture
        changed_fixture = replace(fixture, kickoff_minute=fixture.kickoff_minute + 1)
        changed_schedule = replace(
            self.schedule,
            fixtures=tuple(changed_fixture if item.fixture_id == fixture.fixture_id else item
                           for item in self.schedule.fixtures),
        )
        competition = changed_schedule.competition(changed_fixture.competition_id)
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "changed-schedule.sqlite3") as archive:
            archive.initialize_world_flow(self.schedule, self.initial)
            input_json = immutable_snapshot_json(changed_fixture)
            input_sha256 = fixture_input_sha256(changed_fixture, competition)
            archive.connection.execute(
                "UPDATE world_fixtures SET scheduled_on = ?, kickoff_minute = ?, input_sha256 = ?, input_json = ? "
                "WHERE fixture_id = ?",
                (changed_fixture.scheduled_on.isoformat, changed_fixture.kickoff_minute,
                 input_sha256, input_json, changed_fixture.fixture_id),
            )

            state = advance_world_condition_to(self.initial, changed_fixture.scheduled_on)
            effective = _conditioned_fixture(state, changed_fixture)
            match = create_match(
                effective.home_sheet, effective.away_sheet, rules=competition.rules,
                seed=fixture_seed(changed_schedule, changed_fixture), match_id=changed_fixture.match_id,
            )
            run_to_completion(match)
            record = WorldMatchRecord.create(changed_schedule, changed_fixture, match)
            updated, exposures, settlement = _settle_fixture(
                state, changed_schedule, changed_fixture, record,
                _condition_snapshot_sha256(state),
            )

            with self.assertRaisesRegex(ValueError, "stored world-flow schedule differs"):
                archive.append_with_world_flow(
                    record, updated, exposures, settlement,
                    expected_previous_state_sha256=self.initial.state_sha256,
                )
            self.assertEqual(archive.connection.execute(
                "SELECT COUNT(*) FROM archived_matches"
            ).fetchone()[0], 0)
            self.assertEqual(archive.world_flow_fixture_ids(), ())

    def test_append_rejects_a_later_fixture_before_any_archive_write(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "out-of-order.sqlite3") as archive:
            archive.initialize_world_flow(self.schedule, self.initial)
            fixture = self.schedule.ordered_fixtures[1]
            state = advance_world_condition_to(self.initial, fixture.scheduled_on)
            effective = _conditioned_fixture(state, fixture)
            competition = self.schedule.competition(fixture.competition_id)
            match = create_match(
                effective.home_sheet, effective.away_sheet, rules=competition.rules,
                seed=fixture_seed(self.schedule, fixture), match_id=fixture.match_id,
            )
            run_to_completion(match)
            record = WorldMatchRecord.create(self.schedule, fixture, match)
            updated, exposures, settlement = _settle_fixture(
                state, self.schedule, fixture, record, _condition_snapshot_sha256(state),
            )

            with self.assertRaisesRegex(ValueError, "next chronological scheduled fixture"):
                archive.append_with_world_flow(
                    record, updated, exposures, settlement,
                    expected_previous_state_sha256=self.initial.state_sha256,
                )
            self.assertEqual(archive.connection.execute(
                "SELECT COUNT(*) FROM archived_matches"
            ).fetchone()[0], 0)
            self.assertEqual(archive.world_flow_fixture_ids(), ())
            checkpoint = WorldFlowCheckpoint.from_json(archive.connection.execute(
                "SELECT checkpoint_json FROM world_flow_state WHERE singleton = 1"
            ).fetchone()[0])
            self.assertEqual(checkpoint.revision, 0)

    def test_direct_append_rechecks_club_registration(self):
        registration = replace(
            self.initial.registration,
            squads=tuple(item for item in self.initial.registration.squads
                         if not (item.competition_id == self.fixture.competition_id
                                 and item.club_id == self.fixture.home_participant_id)),
        )
        initial = self._state(registration=registration)
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "unregistered.sqlite3") as archive:
            archive.initialize_world_flow(self.schedule, initial)
            state = advance_world_condition_to(initial, self.fixture.scheduled_on)
            effective = _conditioned_fixture(state, self.fixture)
            competition = self.schedule.competition(self.fixture.competition_id)
            match = create_match(
                effective.home_sheet, effective.away_sheet, rules=competition.rules,
                seed=fixture_seed(self.schedule, self.fixture), match_id=self.fixture.match_id,
            )
            run_to_completion(match)
            record = WorldMatchRecord.create(self.schedule, self.fixture, match)
            updated, exposures, settlement = _settle_fixture(
                state, self.schedule, self.fixture, record, _condition_snapshot_sha256(state),
            )

            with self.assertRaises(WorldFixtureIneligible):
                archive.append_with_world_flow(
                    record, updated, exposures, settlement,
                    expected_previous_state_sha256=initial.state_sha256,
                )
            self.assertEqual(archive.connection.execute(
                "SELECT COUNT(*) FROM archived_matches"
            ).fetchone()[0], 0)
            self.assertEqual(archive.world_flow_fixture_ids(), ())

    def test_direct_append_rejects_match_played_with_unconditioned_fixture_profiles(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "stale-inputs.sqlite3") as archive:
            archive.initialize_world_flow(self.schedule, self.initial)
            state = advance_world_condition_to(self.initial, self.fixture.scheduled_on)
            competition = self.schedule.competition(self.fixture.competition_id)
            match = create_match(
                self.fixture.home_sheet, self.fixture.away_sheet, rules=competition.rules,
                seed=fixture_seed(self.schedule, self.fixture), match_id=self.fixture.match_id,
            )
            run_to_completion(match)
            record = WorldMatchRecord.create(self.schedule, self.fixture, match)
            updated, exposures, settlement = _settle_fixture(
                state, self.schedule, self.fixture, record, _condition_snapshot_sha256(state),
            )

            with self.assertRaisesRegex(ValueError, "conditioned fixture profiles"):
                archive.append_with_world_flow(
                    record, updated, exposures, settlement,
                    expected_previous_state_sha256=self.initial.state_sha256,
                )
            self.assertEqual(archive.connection.execute(
                "SELECT COUNT(*) FROM archived_matches"
            ).fetchone()[0], 0)
            self.assertEqual(archive.world_flow_fixture_ids(), ())

    def test_resume_rejects_projection_tampering_after_all_row_hashes_are_recomputed(self):
        with self._temporary_archive() as temporary:
            path = Path(temporary) / "reprojected.sqlite3"
            with WorldArchiveStore(path) as archive:
                simulate_world_season(self.schedule, self.initial, archive, maximum_fixtures=1)
                exposure = archive.world_player_exposure_history(self.initial.profiles[0].player_id)[0]
                forged = replace(exposure, minutes_played=exposure.minutes_played + 1.0)
                forged_rows = []
                for profile in sorted(self.initial.profiles, key=lambda item: str(item.player_id)):
                    history = archive.world_player_exposure_history(profile.player_id)
                    item = next(row for row in history if row.fixture_id == self.fixture.fixture_id)
                    forged_rows.append(forged if item.player_id == forged.player_id else item)
                forged_exposures = tuple(forged_rows)
                forged_hash = flow_snapshot_sha256(forged_exposures)
                encoded = dumps(forged)
                archive.connection.execute(
                    "UPDATE world_flow_exposures SET resolution_json = ?, resolution_sha256 = ? "
                    "WHERE fixture_id = ? AND player_id = ?",
                    (encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                     self.fixture.fixture_id, str(forged.player_id)),
                )
                with self.assertRaisesRegex(ValueError, "do not reconcile to the archived match line"):
                    archive.world_player_exposure_history(forged.player_id)
                archive.connection.execute(
                    "UPDATE world_flow_fixtures SET exposure_sha256 = ? WHERE fixture_id = ?",
                    (forged_hash, self.fixture.fixture_id),
                )
                row = archive.connection.execute(
                    "SELECT checkpoint_json FROM world_flow_state WHERE singleton = 1"
                ).fetchone()
                checkpoint = replace(
                    WorldFlowCheckpoint.from_json(row["checkpoint_json"]),
                    last_exposure_sha256=forged_hash,
                )
                checkpoint_json = dumps(checkpoint)
                archive.connection.execute(
                    "UPDATE world_flow_state SET checkpoint_json = ?, checkpoint_sha256 = ? "
                    "WHERE singleton = 1",
                    (checkpoint_json, hashlib.sha256(checkpoint_json.encode("utf-8")).hexdigest()),
                )
            with WorldArchiveStore(path) as archive:
                with self.assertRaisesRegex(ValueError, "does not reconcile to match lines and P09 outcomes"):
                    simulate_world_season(self.schedule, self.initial, archive)

    def test_failed_eligibility_leaves_no_match_and_exposure_rows(self):
        registration = replace(self.initial.registration, squads=())
        initial = self._state(registration=registration)
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "ineligible.sqlite3") as archive:
            with patch("games.touchline.esb.world.competition_flow.injury_probability",
                       side_effect=lambda _profile, *, minutes_played, **_kwargs:
                       0.25 if minutes_played > 0 else 0.0):
                with self.assertRaises(WorldFixtureIneligible):
                    simulate_world_season(self.schedule, initial, archive, maximum_fixtures=1)
            self.assertEqual(archive.connection.execute("SELECT COUNT(*) FROM archived_matches").fetchone()[0], 0)
            self.assertEqual(archive.world_flow_fixture_ids(), ())

    def test_resume_rejects_corrupted_normalized_exposure_row(self):
        with self._temporary_archive() as temporary:
            path = Path(temporary) / "tampered.sqlite3"
            with WorldArchiveStore(path) as archive:
                simulate_world_season(self.schedule, self.initial, archive, maximum_fixtures=1)
                archive.connection.execute(
                    "UPDATE world_flow_exposures SET resolution_json = resolution_json || ' ' "
                    "WHERE fixture_id = ? AND player_id = ?",
                    (self.fixture.fixture_id, str(self.initial.profiles[0].player_id)),
                )
            with WorldArchiveStore(path) as archive:
                with self.assertRaisesRegex(ValueError, "failed its integrity check"):
                    simulate_world_season(self.schedule, self.initial, archive)

    def test_player_exposure_history_rejects_corrupt_row_indexes(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "bad-index.sqlite3") as archive:
            simulate_world_season(self.schedule, self.initial, archive, maximum_fixtures=1)
            player_id = str(self.initial.profiles[0].player_id)
            archive.connection.execute(
                "UPDATE world_flow_exposures SET match_id = 'match:wrong-index' "
                "WHERE fixture_id = ? AND player_id = ?",
                (self.fixture.fixture_id, player_id),
            )
            with self.assertRaisesRegex(ValueError, "row indexes"):
                archive.world_player_exposure_history(player_id)

    def test_player_exposure_history_rejects_flow_fixture_match_index(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "bad-flow-match.sqlite3") as archive:
            simulate_world_season(self.schedule, self.initial, archive, maximum_fixtures=1)
            archive.connection.execute(
                "UPDATE world_flow_fixtures SET match_id = 'match:wrong-flow-index' WHERE fixture_id = ?",
                (self.fixture.fixture_id,),
            )
            with self.assertRaisesRegex(ValueError, "lineage does not reconcile"):
                archive.world_player_exposure_history(self.initial.profiles[0].player_id)

    def test_player_exposure_history_rejects_match_hash_and_date_lineage_tampering(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "bad-lineage.sqlite3") as archive:
            simulate_world_season(self.schedule, self.initial, archive, maximum_fixtures=1)
            player_id = self.initial.profiles[0].player_id
            original = archive.world_player_exposure_history(player_id)[0]
            for forged in (
                replace(original, match_state_sha256="b" * 64),
                replace(original, occurred_on=WorldDate(original.occurred_on.day + timedelta(days=1))),
            ):
                encoded = dumps(forged)
                archive.connection.execute(
                    "UPDATE world_flow_exposures SET resolution_json = ?, resolution_sha256 = ? "
                    "WHERE fixture_id = ? AND player_id = ?",
                    (encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                     forged.fixture_id, str(forged.player_id)),
                )
                with self.assertRaisesRegex(ValueError, "lineage does not reconcile"):
                    archive.world_player_exposure_history(player_id)
                restored = dumps(original)
                archive.connection.execute(
                    "UPDATE world_flow_exposures SET resolution_json = ?, resolution_sha256 = ? "
                    "WHERE fixture_id = ? AND player_id = ?",
                    (restored, hashlib.sha256(restored.encode("utf-8")).hexdigest(),
                     original.fixture_id, str(original.player_id)),
                )

    def test_injuries_retain_fixture_match_exposure_lineage_and_block_next_call(self):
        medical = tuple(MedicalProfile(
            item.player_id, baseline_probability_per_90=0.25,
        ) for item in self.initial.profiles)
        initial = self._state(medical_profiles=medical)
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "injuries.sqlite3") as archive:
            with patch("games.touchline.esb.world.competition_flow.injury_probability",
                       side_effect=lambda _profile, *, minutes_played, **_kwargs:
                       0.25 if minutes_played > 0 else 0.0):
                progress, state = simulate_world_season(self.schedule, initial, archive, maximum_fixtures=1)
            self.assertEqual(progress.archived, 1)
            self.assertGreater(len(state.injury_history), 0)
            injury_by_id = {item.injury_id: item for item in state.injury_history}
            for profile in initial.profiles:
                history = archive.world_player_exposure_history(profile.player_id)
                resolution = next(item for item in history if item.fixture_id == self.fixture.fixture_id)
                if resolution.injury_id is not None:
                    injury = injury_by_id[resolution.injury_id]
                    self.assertEqual(injury.source_exposure_id, resolution.exposure_id)
                    self.assertEqual(injury.player_id, resolution.player_id)
                    self.assertEqual(injury.occurred_on, resolution.occurred_on)
            with patch("games.touchline.esb.world.competition_flow.injury_probability",
                       side_effect=lambda _profile, *, minutes_played, **_kwargs:
                       0.25 if minutes_played > 0 else 0.0):
                with self.assertRaises(WorldFixtureIneligible):
                    simulate_world_season(self.schedule, initial, archive, maximum_fixtures=1)
            self.assertEqual(archive.world_flow_fixture_ids(), (self.fixture.fixture_id,))

    def test_medical_stream_changes_without_changing_match_stream(self):
        high_risk_profiles = tuple(MedicalProfile(
            item.player_id, baseline_probability_per_90=0.25,
        ) for item in self.initial.profiles)
        first_state = self._state(medical_profiles=high_risk_profiles, seed=11)
        second_state = self._state(medical_profiles=high_risk_profiles, seed=29)
        hashes = []
        exposures = []
        for state in (first_state, second_state):
            with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "isolated.sqlite3") as archive:
                with patch("games.touchline.esb.world.competition_flow.injury_probability",
                           side_effect=lambda _profile, *, minutes_played, **_kwargs:
                           0.25 if minutes_played > 0 else 0.0):
                    simulate_world_season(self.schedule, state, archive, maximum_fixtures=1)
                summary = archive.match_summary(self.fixture.match_id)
                hashes.append(summary["state_sha256"])
                player_id = self.fixture.home_sheet.starters[0].profile.player_id
                exposures.append(next(item for item in archive.world_player_exposure_history(player_id)
                                      if item.fixture_id == self.fixture.fixture_id))
        self.assertEqual(hashes[0], hashes[1])
        self.assertEqual(exposures[0].injury_probability, exposures[1].injury_probability)
        self.assertNotEqual(exposures[0].injury_roll, exposures[1].injury_roll)

    def test_probe_is_fresh_process_deterministic_and_headless(self):
        root = Path(__file__).resolve().parents[3]
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        outputs = [subprocess.run(
            [sys.executable, "-m", "games.touchline.checks.competition_flow_probe", "--half-ticks", "2"],
            cwd=root, env=environment, capture_output=True, text=True, check=True,
        ).stdout for _ in range(2)]
        self.assertEqual(outputs[0], outputs[1])
        report = json.loads(outputs[0])
        self.assertEqual(report["resume_run"]["archived"], 4)
        self.assertEqual(report["resume_run"]["resumed"], 2)
        self.assertEqual(report["resume_run"]["pending"], 0)
        self.assertEqual(len(report["exposure_rows"]), 32)

        script = """
import builtins, importlib, io, pathlib, sqlite3, sys
def blocked(*args, **kwargs): raise AssertionError('import-time I/O')
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
sqlite3.connect = blocked
importlib.import_module('games.touchline.esb.world.competition_flow')
assert not any(name == 'curses' or name.startswith('termstation') for name in sys.modules)
"""
        subprocess.run([sys.executable, "-c", script], cwd=root, env=environment,
                       capture_output=True, text=True, check=True)

    def _simulate(self, state, maximum_fixtures=None):
        temporary = self._temporary_archive()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "world.sqlite3"
        # Keep the connection alive only for this helper call; the archive data
        # is queried inside the owning tests that need it.
        with WorldArchiveStore(path) as archive:
            return simulate_world_season(
                self.schedule, state, archive, maximum_fixtures=maximum_fixtures,
            )


if __name__ == "__main__":
    unittest.main()
