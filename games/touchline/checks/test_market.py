from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from games.touchline.esb.economy.market import (
    AgentMandate,
    MarketBook,
    MarketCandidate,
    MarketEventKind,
    OfferedRole,
    OfferStatus,
    PlayerMarketProfile,
    TransferOffer,
    add_agent_mandate,
    add_candidate,
    add_player_profile,
    appraise_offer,
    expire_offers,
    offer_cost,
    offer_status,
    resolve_player_choice,
    seller_respond,
    submit_offer,
    withdraw_offer,
)
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.time import WorldDate

ROOT = Path(__file__).resolve().parents[3]


def day(value: int) -> WorldDate:
    return WorldDate(date(2026, 10, value))


def profile(player_id: str = "player:listed", **changes: object) -> PlayerMarketProfile:
    values: dict[str, object] = {
        "player_id": player_id,
        "minimum_weekly_wage_minor": 1_000,
        "target_weekly_wage_minor": 2_000,
        "minimum_contract_weeks": 8,
        "target_contract_weeks": 12,
        "desired_role": OfferedRole.REGULAR,
        "preferred_place_ids": ("place:north",),
        "required_policy_tags": ("policy:fair",),
        "preferred_policy_tags": ("policy:fair",),
        "avoided_policy_tags": ("policy:closed",),
        "minimum_club_reputation_bps": 7_000,
    }
    values.update(changes)
    return PlayerMarketProfile(**values)  # type: ignore[arg-type]


def candidate(*, player_id: str = "player:listed", free: bool = False) -> MarketCandidate:
    return MarketCandidate(
        player_id,
        None if free else "club:seller",
        None if free else "contract:listed",
        0 if free else 12_000,
        "GBP",
        day(1),
        day(30),
    )


def market(*, player_id: str = "player:listed", free: bool = False) -> MarketBook:
    state = add_candidate(MarketBook(), candidate(player_id=player_id, free=free))
    return add_player_profile(state, profile(player_id))


def offer(
    offer_id: str,
    buyer_id: str,
    *,
    player_id: str = "player:listed",
    seller_id: str | None = "club:seller",
    submitted: int = 1,
    expires: int = 10,
    fee: int = 12_345,
    wage: int = 2_000,
    weeks: int = 12,
    role: OfferedRole = OfferedRole.REGULAR,
    place: str = "place:north",
    policies: tuple[str, ...] = ("policy:fair",),
    reputation: int = 8_000,
    agent_id: str | None = None,
    commission_bps: int = 0,
    supersedes: str | None = None,
) -> TransferOffer:
    return TransferOffer(
        offer_id,
        player_id,
        buyer_id,
        seller_id,
        day(submitted),
        day(expires),
        "GBP",
        fee,
        wage,
        weeks,
        role,
        place,
        policies,
        reputation,
        agent_id,
        commission_bps,
        supersedes,
    )


def agent_mandate(
    *,
    player_id: str = "player:listed",
    agent_id: str = "agent:representative",
    start: int = 1,
    expiry: int = 20,
    may_accept: bool = True,
    may_decline: bool = True,
    minimum_wage: int = 1_000,
    minimum_weeks: int = 8,
    maximum_commission_bps: int = 500,
) -> AgentMandate:
    return AgentMandate(
        f"mandate:{agent_id}:{start}", agent_id, player_id, day(start), day(expiry),
        may_accept, may_decline, minimum_wage, minimum_weeks, maximum_commission_bps,
    )


class MarketOfferTests(unittest.TestCase):
    def test_listing_matching_currency_and_free_agent_fee_rules(self) -> None:
        state = market()
        with self.assertRaisesRegex(ValueError, "current seller"):
            submit_offer(state, offer("offer:wrong-seller", "club:buyer", seller_id="club:other"))
        with self.assertRaisesRegex(ValueError, "currency"):
            submit_offer(state, replace(offer("offer:wrong-currency", "club:buyer"), currency="USD"))
        with self.assertRaisesRegex(ValueError, "market currency"):
            MarketCandidate("player:unicode", "club:seller", "contract:unicode", 0,
                            "ÄBC", day(1), day(2))

        free_state = market(player_id="player:free", free=True)
        with self.assertRaisesRegex(ValueError, "free-agent offers"):
            offer("offer:free-fee", "club:buyer", player_id="player:free",
                  seller_id=None, fee=1)
        free_offer = offer(
            "offer:free-no-fee", "club:buyer", player_id="player:free",
            seller_id=None, fee=0,
        )
        free_state = submit_offer(free_state, free_offer)
        with self.assertRaisesRegex(ValueError, "no selling club"):
            seller_respond(free_state, free_offer.offer_id, "club:seller", accept=True, on=day(2))
        chosen_book, choice = resolve_player_choice(free_state, "player:free", day(2))
        self.assertEqual(choice.chosen_offer_id, free_offer.offer_id)
        self.assertEqual(offer_status(chosen_book, free_offer.offer_id), OfferStatus.PLAYER_ACCEPTED)

    def test_seller_transition_is_scoped_live_and_exact_retry_is_idempotent(self) -> None:
        state = submit_offer(market(), offer("offer:live", "club:buyer", expires=4))
        with self.assertRaisesRegex(ValueError, "does not own"):
            seller_respond(state, "offer:live", "club:other", accept=True, on=day(2))
        approved = seller_respond(state, "offer:live", "club:seller", accept=True, on=day(2))
        self.assertIs(seller_respond(approved, "offer:live", "club:seller", accept=True, on=day(2)), approved)
        with self.assertRaisesRegex(ValueError, "only to an open offer"):
            seller_respond(approved, "offer:live", "club:seller", accept=False, on=day(3))

        expired = expire_offers(state, day(5))
        self.assertEqual(offer_status(expired, "offer:live"), OfferStatus.EXPIRED)
        self.assertIs(expire_offers(expired, day(8)), expired)
        with self.assertRaisesRegex(ValueError, "outside the offer window"):
            seller_respond(state, "offer:live", "club:seller", accept=True, on=day(5))

    def test_revisions_keep_lineage_and_reject_branched_or_unlinked_resubmission(self) -> None:
        state = submit_offer(market(), offer("offer:first", "club:buyer", expires=8))
        state = seller_respond(state, "offer:first", "club:seller", accept=False, on=day(2))
        with self.assertRaisesRegex(ValueError, "retain lineage"):
            submit_offer(state, offer("offer:unlinked", "club:buyer", submitted=3))

        revised = offer("offer:revision", "club:buyer", submitted=3, supersedes="offer:first")
        state = submit_offer(state, revised)
        self.assertEqual(offer_status(state, "offer:first"), OfferStatus.SUPERSEDED)
        state = seller_respond(state, revised.offer_id, "club:seller", accept=False, on=day(4))
        next_revision = offer("offer:revision-two", "club:buyer", submitted=5,
                              supersedes=revised.offer_id)
        state = submit_offer(state, next_revision)
        self.assertEqual(offer_status(state, revised.offer_id), OfferStatus.SUPERSEDED)
        with self.assertRaisesRegex(ValueError, "latest offer"):
            submit_offer(state, offer("offer:branch", "club:buyer", submitted=6,
                                      supersedes=revised.offer_id))

    def test_withdrawal_and_deadline_expiration_retain_terminal_history(self) -> None:
        state = market()
        state = submit_offer(state, offer("offer:withdraw", "club:buyer-a", expires=4))
        state = submit_offer(state, offer("offer:deadline", "club:buyer-b", expires=3))
        withdrawn = withdraw_offer(state, "offer:withdraw", "club:buyer-a", on=day(2))
        self.assertIs(withdraw_offer(withdrawn, "offer:withdraw", "club:buyer-a", on=day(2)), withdrawn)
        expired = expire_offers(withdrawn, day(4))
        self.assertEqual(offer_status(expired, "offer:withdraw"), OfferStatus.WITHDRAWN)
        self.assertEqual(offer_status(expired, "offer:deadline"), OfferStatus.EXPIRED)
        with self.assertRaisesRegex(ValueError, "unresolved offer"):
            withdraw_offer(expired, "offer:deadline", "club:buyer-b", on=day(4))


class MarketChoiceTests(unittest.TestCase):
    def test_competing_offers_keep_costs_appraisals_and_one_winner(self) -> None:
        state = market()
        mandate = agent_mandate()
        state = add_agent_mandate(state, mandate)
        preferred = offer("offer:a", "club:buyer-a", agent_id="agent:representative",
                          commission_bps=333)
        alternative = offer("offer:b", "club:buyer-b", place="place:south", reputation=9_000)
        pending = offer("offer:c", "club:buyer-c", place="place:south")
        state = submit_offer(submit_offer(submit_offer(state, preferred), alternative), pending)
        state = seller_respond(state, "offer:a", "club:seller", accept=True, on=day(2))
        state = seller_respond(state, "offer:b", "club:seller", accept=True, on=day(2))

        cost = offer_cost(preferred)
        self.assertEqual(cost.guaranteed_wages_minor, 24_000)
        self.assertEqual(cost.agent_commission_minor, 799)
        self.assertEqual(cost.total_guaranteed_cost_minor, 37_144)
        book, choice = resolve_player_choice(state, "player:listed", day(3))
        self.assertEqual(choice.chosen_offer_id, "offer:a")
        self.assertEqual([(item.offer_id, item.overall_score_bps) for item in choice.appraisals],
                         [("offer:a", 10_000), ("offer:b", 9_000)])
        self.assertEqual(offer_status(book, "offer:a"), OfferStatus.PLAYER_ACCEPTED)
        self.assertEqual(offer_status(book, "offer:b"), OfferStatus.PLAYER_REJECTED)
        self.assertEqual(offer_status(book, "offer:c"), OfferStatus.CLOSED_COMPETITOR)
        closure = next(item for item in book.events if item.kind is MarketEventKind.CLOSED_COMPETITOR)
        self.assertEqual(closure.related_offer_id, "offer:a")
        replayed_book, replayed_choice = resolve_player_choice(book, "player:listed", day(7))
        self.assertIs(replayed_book, book)
        self.assertEqual(replayed_choice, choice)
        self.assertEqual(sum(item.kind is MarketEventKind.PLAYER_ACCEPTED for item in book.events), 1)

    def test_player_preferences_expose_weighted_components_and_hard_constraints(self) -> None:
        preferences = profile()
        valid_terms = offer("offer:terms", "club:buyer")
        appraisal = appraise_offer(preferences, valid_terms)
        self.assertEqual(
            (appraisal.wage_score_bps, appraisal.security_score_bps, appraisal.role_score_bps,
             appraisal.place_score_bps, appraisal.policy_score_bps, appraisal.reputation_score_bps),
            (10_000, 10_000, 10_000, 10_000, 10_000, 10_000),
        )
        inadequate = offer(
            "offer:inadequate", "club:buyer", wage=900, weeks=4, role=OfferedRole.PROSPECT,
            place="place:south", policies=("policy:closed",), reputation=6_000,
        )
        appraisal = appraise_offer(preferences, inadequate)
        self.assertFalse(appraisal.acceptable)
        self.assertEqual(
            appraisal.reasons,
            ("below_minimum_wage", "term_too_short", "required_policy_missing",
             "avoided_policy_present", "club_reputation_below_minimum", "below_preference_threshold"),
        )

    def test_choice_expires_stale_seller_approval_before_appraisal(self) -> None:
        state = submit_offer(market(), offer("offer:stale", "club:buyer", expires=3))
        state = seller_respond(state, "offer:stale", "club:seller", accept=True, on=day(2))
        expired, choice = resolve_player_choice(state, "player:listed", day(4))
        self.assertIsNone(choice.chosen_offer_id)
        self.assertEqual(choice.appraisals, ())
        self.assertEqual(offer_status(expired, "offer:stale"), OfferStatus.EXPIRED)

    def test_acceptance_must_close_other_live_offers_even_after_reload(self) -> None:
        state = submit_offer(
            submit_offer(market(), offer("offer:accepted", "club:buyer-a")),
            offer("offer:still-open", "club:buyer-b"),
        )
        state = seller_respond(state, "offer:accepted", "club:seller", accept=True, on=day(2))
        accepted, choice = resolve_player_choice(state, "player:listed", day(3))
        self.assertEqual(choice.chosen_offer_id, "offer:accepted")
        self.assertEqual(offer_status(accepted, "offer:still-open"), OfferStatus.CLOSED_COMPETITOR)
        with self.assertRaisesRegex(ValueError, "already accepted"):
            seller_respond(accepted, "offer:still-open", "club:seller", accept=True, on=day(4))

        closure_id = next(item.event_id for item in accepted.events
                          if item.kind is MarketEventKind.CLOSED_COMPETITOR)
        with self.assertRaisesRegex(ValueError, "resolve all competing live offers"):
            replace(accepted, events=tuple(item for item in accepted.events
                                           if item.event_id != closure_id))
        payload = json.loads(dumps(accepted))
        payload["payload"]["events"] = [
            item for item in payload["payload"]["events"]
            if item["event_id"] != closure_id
        ]
        with self.assertRaises(SerializationError):
            loads(json.dumps(payload), MarketBook)


class AgentMandateTests(unittest.TestCase):
    def test_agent_acceptance_obeys_active_terms_and_decline_permission(self) -> None:
        state = add_agent_mandate(market(), agent_mandate(may_decline=False))
        for item in (
            offer("offer:agent-a", "club:buyer-a", wage=2_200, weeks=16),
            offer("offer:agent-b", "club:buyer-b", wage=2_000, weeks=12),
        ):
            state = submit_offer(state, item)
        for item in state.offers:
            state = seller_respond(state, item.offer_id, "club:seller", accept=True, on=day(2))
        accepted, choice = resolve_player_choice(
            state, "player:listed", day(3), actor_id="agent:representative",
        )
        self.assertEqual(choice.chosen_offer_id, "offer:agent-a")
        decision_events = [item for item in accepted.events if item.kind in (
            MarketEventKind.PLAYER_ACCEPTED, MarketEventKind.PLAYER_REJECTED,
        )]
        self.assertEqual([item.kind for item in decision_events], [MarketEventKind.PLAYER_ACCEPTED])
        self.assertEqual(offer_status(accepted, "offer:agent-b"), OfferStatus.CLOSED_COMPETITOR)

        with self.assertRaisesRegex(ValueError, "active mandate"):
            resolve_player_choice(state, "player:listed", day(21), actor_id="agent:representative")
        with self.assertRaisesRegex(ValueError, "active mandate"):
            resolve_player_choice(state, "player:listed", day(3), actor_id="agent:unknown")

    def test_agent_scope_can_limit_terms_and_authority(self) -> None:
        state = add_agent_mandate(
            market(), agent_mandate(minimum_wage=2_500, minimum_weeks=16),
        )
        terms = offer("offer:outside-agent-scope", "club:buyer", wage=2_000, weeks=12)
        state = submit_offer(state, terms)
        state = seller_respond(state, terms.offer_id, "club:seller", accept=True, on=day(2))
        same_state, no_choice = resolve_player_choice(
            state, "player:listed", day(3), actor_id="agent:representative",
        )
        self.assertIs(same_state, state)
        self.assertIsNone(no_choice.chosen_offer_id)
        self.assertEqual(no_choice.appraisals, ())

        cannot_accept = add_agent_mandate(
            market(), agent_mandate(may_accept=False, may_decline=True),
        )
        terms = offer("offer:declined-by-agent", "club:buyer")
        cannot_accept = submit_offer(cannot_accept, terms)
        cannot_accept = seller_respond(cannot_accept, terms.offer_id, "club:seller", accept=True, on=day(2))
        declined, choice = resolve_player_choice(
            cannot_accept, "player:listed", day(3), actor_id="agent:representative",
        )
        self.assertIsNone(choice.chosen_offer_id)
        self.assertEqual(offer_status(declined, terms.offer_id), OfferStatus.PLAYER_REJECTED)


class MarketPersistenceTests(unittest.TestCase):
    def test_market_book_round_trip_and_tampered_appraisal_are_rejected(self) -> None:
        state = add_agent_mandate(market(), agent_mandate())
        first = offer("offer:roundtrip-a", "club:buyer-a", agent_id="agent:representative",
                      commission_bps=250)
        second = offer("offer:roundtrip-b", "club:buyer-b", place="place:south")
        state = submit_offer(submit_offer(state, first), second)
        state = seller_respond(state, first.offer_id, "club:seller", accept=True, on=day(2))
        state = seller_respond(state, second.offer_id, "club:seller", accept=True, on=day(2))
        state, _ = resolve_player_choice(state, "player:listed", day(3))
        encoded = dumps(state)
        restored = loads(encoded, MarketBook)
        self.assertEqual(restored, state)
        self.assertEqual(dumps(restored), encoded)

        data = json.loads(encoded)
        player_event = next(item for item in data["payload"]["events"]
                            if item["kind"] in ("player_accepted_in_principle", "player_rejected"))
        player_event["appraisal"]["wage_score_bps"] -= 1
        with self.assertRaises(SerializationError):
            loads(json.dumps(data), MarketBook)

    def test_fresh_process_probe_is_deterministic_and_import_is_headless(self) -> None:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        command = [sys.executable, "-m", "games.touchline.checks.market_probe"]
        first = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        second = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        self.assertEqual(first.stdout, second.stdout)
        result = json.loads(first.stdout)
        self.assertEqual(result["chosen_offer_id"], "offer:p15b-preferred")
        self.assertEqual(result["closed_offer_count"], 1)
        self.assertEqual(result["currency"], "GBP")

        code = """\
import builtins
import io
import pathlib
import sys
def blocked(*args, **kwargs):
    raise AssertionError('market import attempted file access')
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
pathlib.Path.read_text = blocked
pathlib.Path.read_bytes = blocked
import games.touchline.esb.economy.market
assert 'curses' not in sys.modules
assert 'termstation_ui' not in sys.modules
"""
        subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    unittest.main()
