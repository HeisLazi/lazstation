from __future__ import annotations

import dataclasses
import math
import os
import subprocess
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

from games.touchline.esb.ids import EventId
from games.touchline.esb.people.preferences import (
    OpportunityId,
    PersonalPreferenceHistory,
    PreferenceAssessment,
    PreferenceDomain,
    PreferenceFeature,
    PreferenceOpportunity,
    PreferenceStance,
    assess_opportunity_preferences,
    new_self_reported_preference,
    record_self_reported_preference,
)
from games.touchline.esb.people.relationships import PersonId, WorldMoment
from games.touchline.esb.serialization import dumps, loads
from games.touchline.esb.time import WorldDate

ROOT = Path(__file__).resolve().parents[3]
BASE = WorldDate(date(2026, 10, 7))
PLAYER = PersonId("player:preference-owner")
OTHER = PersonId("player:preference-other")

PLACE = PreferenceFeature(PreferenceDomain.PLACE, "place:windhoek")
LEAGUE = PreferenceFeature(
    PreferenceDomain.COMPETITION, "competition:namibia-premier-league"
)
LIFESTYLE = PreferenceFeature(
    PreferenceDomain.LIFESTYLE, "lifestyle:coastal-climate"
)
POLICY = PreferenceFeature(
    PreferenceDomain.CLUB_POLICY, "policy:academy-minutes"
)


def moment(sequence: int, days: int = 0) -> WorldMoment:
    return WorldMoment(WorldDate(BASE.day + timedelta(days=days)), sequence)


def statement(
    *,
    event: str,
    feature: PreferenceFeature = PLACE,
    stance: PreferenceStance = PreferenceStance.FAVOUR,
    at: WorldMoment | None = None,
    salience: float = 0.7,
    certainty: float = 0.9,
    person_id: PersonId = PLAYER,
):
    return new_self_reported_preference(
        person_id=person_id,
        source_event_id=EventId(event),
        at=at or moment(1),
        feature=feature,
        stance=stance,
        salience=salience,
        certainty=certainty,
    )


def opportunity(*features: PreferenceFeature, at: WorldMoment | None = None):
    return PreferenceOpportunity(
        OpportunityId("opportunity:windhoek-role"), at or moment(5), tuple(features)
    )


class PersonalPreferenceTests(unittest.TestCase):
    def test_exact_typed_features_require_explicit_domain_ids(self) -> None:
        for domain, feature_id in (
            (PreferenceDomain.PLACE, "place:windhoek"),
            (PreferenceDomain.COMPETITION, "competition:npl"),
            (PreferenceDomain.LIFESTYLE, "lifestyle:coastal"),
            (PreferenceDomain.CLUB_POLICY, "policy:academy-minutes"),
        ):
            self.assertEqual(PreferenceFeature(domain, feature_id).domain, domain)
        with self.assertRaisesRegex(ValueError, "domain's explicit prefix"):
            PreferenceFeature(PreferenceDomain.PLACE, "country:namibia")
        with self.assertRaisesRegex(TypeError, "supported domain"):
            PreferenceFeature("place", "place:windhoek")  # type: ignore[arg-type]

    def test_statement_ids_are_stable_and_exact_replay_is_idempotent(self) -> None:
        item = statement(event="event:stated-windhoek")
        history = PersonalPreferenceHistory(PLAYER)
        recorded = record_self_reported_preference(history, item)
        self.assertIs(record_self_reported_preference(recorded, item), recorded)
        changed = statement(
            event="event:stated-windhoek", stance=PreferenceStance.AVOID
        )
        self.assertEqual(changed.preference_id, item.preference_id)
        with self.assertRaisesRegex(ValueError, "conflicting statement content"):
            record_self_reported_preference(recorded, changed)
        self.assertEqual(history.statements, ())

    def test_one_report_event_can_name_distinct_features_at_the_same_moment(self) -> None:
        history = PersonalPreferenceHistory(PLAYER)
        for feature in (PLACE, LIFESTYLE, POLICY):
            history = record_self_reported_preference(
                history,
                statement(event="event:preference-interview", feature=feature),
            )
        self.assertEqual(len(history.statements), 3)
        self.assertEqual({item.source_event_id for item in history.statements},
                         {EventId("event:preference-interview")})

    def test_latest_explicit_statement_is_read_as_of_opportunity_time(self) -> None:
        history = PersonalPreferenceHistory(PLAYER)
        first = statement(event="event:place-favour", at=moment(1))
        revision = statement(
            event="event:place-avoid",
            stance=PreferenceStance.AVOID,
            at=moment(4),
            salience=0.95,
            certainty=0.8,
        )
        history = record_self_reported_preference(history, first)
        history = record_self_reported_preference(history, revision)

        before_revision = assess_opportunity_preferences(
            history, person_id=PLAYER, opportunity=opportunity(PLACE, at=moment(3))
        )
        after_revision = assess_opportunity_preferences(
            history, person_id=PLAYER, opportunity=opportunity(PLACE, at=moment(5))
        )
        self.assertEqual(before_revision.readings[0].stance, PreferenceStance.FAVOUR)
        self.assertEqual(before_revision.readings[0].preference_id, first.preference_id)
        self.assertEqual(after_revision.readings[0].stance, PreferenceStance.AVOID)
        self.assertEqual(after_revision.readings[0].preference_id, revision.preference_id)
        self.assertEqual(after_revision.readings[0].source_event_id, revision.source_event_id)
        self.assertEqual(after_revision.readings[0].salience, 0.95)

    def test_unknown_is_distinct_from_open_and_unmentioned_features_stay_unknown(self) -> None:
        history = PersonalPreferenceHistory(PLAYER)
        open_statement = statement(
            event="event:open-league",
            feature=LEAGUE,
            stance=PreferenceStance.OPEN,
        )
        history = record_self_reported_preference(history, open_statement)
        assessed = assess_opportunity_preferences(
            history,
            person_id=PLAYER,
            opportunity=opportunity(LEAGUE, PLACE, LIFESTYLE, POLICY),
        )
        by_feature = {item.feature: item for item in assessed.readings}
        self.assertEqual(by_feature[LEAGUE].stance, PreferenceStance.OPEN)
        self.assertIsNone(by_feature[PLACE].stance)
        self.assertIsNone(by_feature[PLACE].preference_id)
        self.assertIsNone(by_feature[LIFESTYLE].stance)
        self.assertIsNone(by_feature[POLICY].stance)

    def test_feature_matching_is_exact_and_never_inherits_parent_regions(self) -> None:
        history = record_self_reported_preference(
            PersonalPreferenceHistory(PLAYER),
            statement(event="event:windhoek-only", feature=PLACE),
        )
        namibia = PreferenceFeature(PreferenceDomain.PLACE, "place:namibia")
        different_city = PreferenceFeature(PreferenceDomain.PLACE, "place:swakopmund")
        assessed = assess_opportunity_preferences(
            history,
            person_id=PLAYER,
            opportunity=opportunity(namibia, different_city),
        )
        self.assertEqual(len(assessed.readings), 2)
        self.assertTrue(all(item.stance is None for item in assessed.readings))

    def test_assessment_is_per_feature_evidence_not_a_scalar_decision(self) -> None:
        history = PersonalPreferenceHistory(PLAYER)
        history = record_self_reported_preference(
            history,
            statement(event="event:place-evidence", feature=PLACE,
                      stance=PreferenceStance.FAVOUR),
        )
        history = record_self_reported_preference(
            history,
            statement(event="event:policy-evidence", feature=POLICY,
                      stance=PreferenceStance.AVOID, at=moment(2)),
        )
        assessment = assess_opportunity_preferences(
            history,
            person_id=PLAYER,
            opportunity=opportunity(POLICY, PLACE, LIFESTYLE),
        )
        by_feature = {item.feature: item.stance for item in assessment.readings}
        self.assertEqual(by_feature[PLACE], PreferenceStance.FAVOUR)
        self.assertEqual(by_feature[POLICY], PreferenceStance.AVOID)
        self.assertIsNone(by_feature[LIFESTYLE])
        self.assertFalse(hasattr(assessment, "compatibility_score"))
        self.assertFalse(hasattr(assessment, "decision"))

    def test_assessment_rejects_forged_lineage_and_empty_feature_sets(self) -> None:
        history = record_self_reported_preference(
            PersonalPreferenceHistory(PLAYER),
            statement(event="event:assessment-lineage", feature=PLACE),
        )
        assessment = assess_opportunity_preferences(
            history,
            person_id=PLAYER,
            opportunity=opportunity(PLACE, LIFESTYLE),
        )
        known_index = next(
            index for index, item in enumerate(assessment.readings)
            if item.feature == PLACE
        )
        changed_readings = list(assessment.readings)
        changed_readings[known_index] = dataclasses.replace(
            changed_readings[known_index],
            source_event_id=EventId("event:forged-preference-source"),
        )
        with self.assertRaisesRegex(ValueError, "person, source and feature"):
            dataclasses.replace(assessment, readings=tuple(changed_readings))
        with self.assertRaisesRegex(ValueError, "at least one opportunity feature"):
            dataclasses.replace(assessment, readings=())

    def test_history_is_owned_by_one_person_and_rejects_cross_person_writes_or_reads(self) -> None:
        history = PersonalPreferenceHistory(PLAYER)
        other_statement = statement(
            event="event:other-person", person_id=OTHER
        )
        with self.assertRaisesRegex(ValueError, "another person"):
            record_self_reported_preference(history, other_statement)
        own_history = record_self_reported_preference(
            PersonalPreferenceHistory(OTHER), other_statement
        )
        with self.assertRaisesRegex(ValueError, "belongs to another person"):
            assess_opportunity_preferences(
                own_history,
                person_id=PLAYER,
                opportunity=opportunity(PLACE),
            )
        self.assertEqual(history.statements, ())

    def test_history_rejects_out_of_order_or_colliding_source_moments(self) -> None:
        history = record_self_reported_preference(
            PersonalPreferenceHistory(PLAYER),
            statement(event="event:later", at=moment(4)),
        )
        with self.assertRaisesRegex(ValueError, "world chronology"):
            record_self_reported_preference(
                history,
                statement(event="event:earlier", feature=LEAGUE, at=moment(3)),
            )
        with self.assertRaisesRegex(ValueError, "multiple world moments"):
            record_self_reported_preference(
                history,
                statement(event="event:later", feature=LEAGUE, at=moment(5)),
            )
        with self.assertRaisesRegex(ValueError, "multiple preference source events"):
            record_self_reported_preference(
                history,
                statement(event="event:collision", feature=LEAGUE, at=moment(4)),
            )
        self.assertEqual(len(history.statements), 1)

    def test_history_and_assessment_round_trip_and_are_canonically_ordered(self) -> None:
        history = PersonalPreferenceHistory(PLAYER)
        for feature in (POLICY, PLACE, LIFESTYLE, LEAGUE):
            history = record_self_reported_preference(
                history,
                statement(event="event:profile", feature=feature),
            )
        self.assertEqual(
            tuple(item.feature for item in history.statements),
            tuple(sorted((POLICY, PLACE, LIFESTYLE, LEAGUE),
                         key=lambda item: (item.domain.value, item.feature_id))),
        )
        assessment = assess_opportunity_preferences(
            history,
            person_id=PLAYER,
            opportunity=opportunity(POLICY, PLACE, LEAGUE),
        )
        self.assertEqual(loads(dumps(history), PersonalPreferenceHistory), history)
        self.assertEqual(loads(dumps(assessment), PreferenceAssessment), assessment)
        self.assertEqual(dumps(assessment), dumps(loads(dumps(assessment), PreferenceAssessment)))

    def test_invalid_salience_certainty_and_feature_sets_are_rejected(self) -> None:
        for value in (-0.01, 1.01, math.nan, math.inf, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                statement(event="event:bad-value", salience=value)  # type: ignore[arg-type]
        for value in (-0.01, 1.01, math.nan, math.inf, True):
            with self.subTest(certainty=value), self.assertRaises(ValueError):
                statement(event="event:bad-certainty", certainty=value)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "cannot repeat"):
            opportunity(PLACE, PLACE)
        with self.assertRaisesRegex(TypeError, "immutable feature tuple"):
            PreferenceOpportunity(
                OpportunityId("opportunity:mutable"), moment(2), [PLACE]  # type: ignore[arg-type]
            )

    def test_preference_model_has_no_identity_or_performance_inputs(self) -> None:
        fields = {item.name for item in dataclasses.fields(type(statement(event="event:fields")))}
        self.assertNotIn("nationality", fields)
        self.assertNotIn("capability", fields)
        self.assertNotIn("relationship", fields)
        self.assertNotIn("performance", fields)

    def test_personal_preferences_do_not_change_the_separate_p15_market_appraisal(self) -> None:
        from games.touchline.esb.economy.market import (
            OfferedRole,
            PlayerMarketProfile,
            TransferOffer,
            appraise_offer,
        )

        market_profile = PlayerMarketProfile(
            player_id=str(PLAYER),
            minimum_weekly_wage_minor=1_000,
            target_weekly_wage_minor=2_000,
            minimum_contract_weeks=8,
            target_contract_weeks=12,
            desired_role=OfferedRole.REGULAR,
            preferred_place_ids=("place:north",),
            required_policy_tags=("policy:fair",),
            preferred_policy_tags=("policy:fair",),
            avoided_policy_tags=("policy:closed",),
            minimum_club_reputation_bps=7_000,
        )
        terms = TransferOffer(
            "offer:separate-preference-test",
            str(PLAYER),
            "club:north",
            "club:current",
            BASE,
            WorldDate(BASE.day + timedelta(days=30)),
            "GBP",
            10_000,
            2_000,
            12,
            OfferedRole.REGULAR,
            "place:north",
            ("policy:fair",),
            8_000,
        )
        market_before = appraise_offer(market_profile, terms)
        personal_history = record_self_reported_preference(
            PersonalPreferenceHistory(PLAYER),
            statement(
                event="event:personal-place-avoidance",
                feature=PreferenceFeature(PreferenceDomain.PLACE, "place:north"),
                stance=PreferenceStance.AVOID,
            ),
        )
        personal_reading = assess_opportunity_preferences(
            personal_history,
            person_id=PLAYER,
            opportunity=opportunity(
                PreferenceFeature(PreferenceDomain.PLACE, "place:north")
            ),
        )
        self.assertEqual(personal_reading.readings[0].stance, PreferenceStance.AVOID)
        self.assertEqual(appraise_offer(market_profile, terms), market_before)
        with self.assertRaisesRegex(TypeError, "player preferences and offer terms"):
            appraise_offer(personal_history, terms)  # type: ignore[arg-type]

    def test_probe_is_byte_stable_and_module_import_is_headless(self) -> None:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable, "-m", "games.touchline.checks.preference_probe"]
        first = subprocess.run(command, cwd=ROOT, env=env, check=True,
                               capture_output=True, text=True)
        second = subprocess.run(command, cwd=ROOT, env=env, check=True,
                                capture_output=True, text=True)
        self.assertEqual(first.stdout, second.stdout)

        headless = r"""
import builtins, io, sys
def denied(*args, **kwargs):
    raise AssertionError('preference domain import attempted file access')
builtins.open = denied
io.open = denied
import games.touchline.esb.people.preferences
assert 'curses' not in sys.modules
assert 'games.touchline.main' not in sys.modules
assert 'games.touchline.esb.media.publication' not in sys.modules
assert 'games.touchline.esb.economy.market' not in sys.modules
"""
        subprocess.run([sys.executable, "-c", headless], cwd=ROOT, env=env,
                       check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
