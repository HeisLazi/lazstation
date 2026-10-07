from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date

from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.registration import (
    ClubCompetitionSquad, PlayerTrainingRecord, RegistrationBook,
    RegistrationPolicy, check_existing_registration, check_registration, purchase_loan_player,
    register_loan_player, return_loan_player,
)


def day(value: int) -> WorldDate:
    return WorldDate(date(2026, 1, value))


def registration_book(*, borrower_players: tuple[str, ...] = ("player:borrower-homegrown",)) -> RegistrationBook:
    return RegistrationBook(
        policies=(RegistrationPolicy(
            "competition:league", "rules:league-v1", day(1), WorldDate(date(2026, 12, 31)),
            maximum_squad_size=4, minimum_homegrown_players=1,
            maximum_non_homegrown_players=2,
        ),),
        player_training=(
            PlayerTrainingRecord("player:loaned", ("club:owner",)),
            PlayerTrainingRecord("player:owner-homegrown", ("club:owner",)),
            PlayerTrainingRecord("player:borrower-homegrown", ("club:borrower",)),
            PlayerTrainingRecord("player:borrower-other", ("club:other",)),
            PlayerTrainingRecord("player:borrower-third", ("club:third",)),
            PlayerTrainingRecord("player:borrower-extra", ("club:borrower",)),
        ),
        squads=(
            ClubCompetitionSquad(
                "competition:league", "club:owner",
                ("player:loaned", "player:owner-homegrown"),
            ),
            ClubCompetitionSquad(
                "competition:league", "club:borrower", borrower_players,
            ),
        ),
    )


def two_competition_book() -> RegistrationBook:
    original = registration_book()
    second_policy = replace(
        original.policies[0], competition_id="competition:cup", ruleset_id="rules:cup-v1",
    )
    second_squads = tuple(
        replace(item, competition_id="competition:cup") for item in original.squads
    )
    return RegistrationBook(
        original.policies + (second_policy,), original.player_training,
        original.squads + second_squads,
    )


class RegistrationLifecycleTests(unittest.TestCase):
    def test_existing_registration_remains_valid_after_window_closes(self) -> None:
        book = registration_book()
        checked = check_existing_registration(
            book, "competition:league", "club:borrower",
            "player:borrower-homegrown", WorldDate(date(2027, 1, 1)),
        )
        self.assertTrue(checked.eligible)
        self.assertEqual(checked.reasons, ())
        missing = check_existing_registration(
            book, "competition:league", "club:borrower",
            "player:loaned", WorldDate(date(2027, 1, 1)),
        )
        self.assertFalse(missing.eligible)
        self.assertEqual(missing.reasons, ("not_currently_registered",))

    def test_loan_moves_registration_and_preserves_then_restores_owner_slot(self) -> None:
        before = registration_book()
        moved = register_loan_player(
            before, "player:loaned", "club:owner", "club:borrower",
            ("competition:league",), day(10),
        )
        owner = next(item for item in moved.squads if item.club_id == "club:owner")
        borrower = next(item for item in moved.squads if item.club_id == "club:borrower")
        self.assertNotIn("player:loaned", owner.registered_player_ids)
        self.assertIn("player:loaned", owner.loan_reserve_player_ids)
        self.assertIn("player:loaned", borrower.registered_player_ids)

        returned = return_loan_player(
            moved, "player:loaned", "club:owner", "club:borrower",
            ("competition:league",),
        )
        owner = next(item for item in returned.squads if item.club_id == "club:owner")
        borrower = next(item for item in returned.squads if item.club_id == "club:borrower")
        self.assertIn("player:loaned", owner.registered_player_ids)
        self.assertNotIn("player:loaned", owner.loan_reserve_player_ids)
        self.assertNotIn("player:loaned", borrower.registered_player_ids)

    def test_purchase_keeps_borrower_registration_and_releases_owner_reservation(self) -> None:
        moved = register_loan_player(
            registration_book(), "player:loaned", "club:owner", "club:borrower",
            ("competition:league",), day(10),
        )
        purchased = purchase_loan_player(
            moved, "player:loaned", "club:owner", "club:borrower",
            ("competition:league",),
        )
        owner = next(item for item in purchased.squads if item.club_id == "club:owner")
        borrower = next(item for item in purchased.squads if item.club_id == "club:borrower")
        self.assertNotIn("player:loaned", owner.loan_reserve_player_ids)
        self.assertIn("player:loaned", borrower.registered_player_ids)

    def test_loan_reserve_is_unique_and_requires_one_other_active_registration(self) -> None:
        moved = register_loan_player(
            registration_book(), "player:loaned", "club:owner", "club:borrower",
            ("competition:league",), day(10),
        )
        with self.assertRaisesRegex(ValueError, "reserved by two clubs"):
            RegistrationBook(
                moved.policies, moved.player_training,
                moved.squads + (ClubCompetitionSquad(
                    "competition:league", "club:other", (), ("player:loaned",),
                ),),
            )
        with self.assertRaisesRegex(ValueError, "requires one active registration"):
            RegistrationBook(
                moved.policies, moved.player_training,
                tuple(replace(squad, registered_player_ids=())
                      if squad.club_id == "club:borrower" else squad
                      for squad in moved.squads),
            )

    def test_registration_moves_are_idempotent_and_reject_partial_competition_state(self) -> None:
        source = two_competition_book()
        competitions = ("competition:league", "competition:cup")
        loaned = register_loan_player(
            source, "player:loaned", "club:owner", "club:borrower", competitions, day(10),
        )
        self.assertIs(register_loan_player(
            loaned, "player:loaned", "club:owner", "club:borrower", competitions, day(10),
        ), loaned)

        returned = return_loan_player(
            loaned, "player:loaned", "club:owner", "club:borrower", competitions,
        )
        self.assertIs(return_loan_player(
            returned, "player:loaned", "club:owner", "club:borrower", competitions,
        ), returned)
        purchased = purchase_loan_player(
            loaned, "player:loaned", "club:owner", "club:borrower", competitions,
        )
        self.assertIs(purchase_loan_player(
            purchased, "player:loaned", "club:owner", "club:borrower", competitions,
        ), purchased)

        loaned_by_squad = {(item.competition_id, item.club_id): item for item in loaned.squads}
        mixed_squads = tuple(
            loaned_by_squad[(item.competition_id, item.club_id)]
            if item.competition_id == "competition:league" else item
            for item in source.squads
        )
        mixed = RegistrationBook(source.policies, source.player_training, mixed_squads)
        with self.assertRaisesRegex(ValueError, "before the move"):
            register_loan_player(
                mixed, "player:loaned", "club:owner", "club:borrower", competitions, day(10),
            )
        with self.assertRaisesRegex(ValueError, "every competition"):
            return_loan_player(
                mixed, "player:loaned", "club:owner", "club:borrower", competitions,
            )
        with self.assertRaisesRegex(ValueError, "every competition"):
            purchase_loan_player(
                mixed, "player:loaned", "club:owner", "club:borrower", competitions,
            )
    def test_configured_window_roster_and_homegrown_rules_gate_registration(self) -> None:
        self.assertIn(
            "registration_window_closed",
            check_registration(registration_book(), "competition:league", "club:borrower",
                               "player:loaned", WorldDate(date(2027, 1, 1)),
                               moving_from_club_id="club:owner").reasons,
        )
        full = registration_book(borrower_players=(
            "player:borrower-homegrown", "player:borrower-other",
            "player:borrower-third", "player:borrower-extra",
        ))
        full = RegistrationBook(
            (replace(full.policies[0], maximum_non_homegrown_players=4),),
            full.player_training, full.squads,
        )
        self.assertIn(
            "squad_limit_reached",
            check_registration(full, "competition:league", "club:borrower",
                               "player:loaned", day(10),
                               moving_from_club_id="club:owner").reasons,
        )
        with self.assertRaisesRegex(ValueError, "registration failed"):
            register_loan_player(full, "player:loaned", "club:owner", "club:borrower",
                                 ("competition:league",), day(10))

    def test_duplicate_registration_across_clubs_and_unknown_evidence_are_rejected(self) -> None:
        book = registration_book()
        with self.assertRaisesRegex(ValueError, "two clubs"):
            RegistrationBook(
                book.policies, book.player_training,
                book.squads + (ClubCompetitionSquad(
                    "competition:league", "club:other", ("player:loaned",),
                ),),
            )
        with self.assertRaisesRegex(KeyError, "no registration training record"):
            check_registration(book, "competition:league", "club:borrower", "player:unknown", day(10))

    def test_registration_book_round_trip_and_rejects_tampered_decision_version(self) -> None:
        book = registration_book()
        self.assertEqual(RegistrationBook.from_json(book.to_json()), book)
        self.assertEqual(RegistrationBook.from_json(book.to_json()).to_json(), book.to_json())
        payload = __import__("json").loads(book.to_json())
        payload["payload"]["schema_version"] = 2
        with self.assertRaises(SerializationError):
            loads(__import__("json").dumps(payload), RegistrationBook)


if __name__ == "__main__":
    unittest.main()
