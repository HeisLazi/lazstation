"""Versioned, competition-specific squad registration (P15c).

Registration is deliberately separate from employment ownership. A player on
loan is temporarily registered for the borrower while the owner's squad slot
is reserved, then moves back on return or becomes the borrower's on purchase.
Rules are explicit per competition and can be varied without changing player
or club identity records.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from games.touchline.esb.ids import derive_id, validate_id
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.time import WorldDate


@dataclass(frozen=True)
class RegistrationPolicy:
    competition_id: str
    ruleset_id: str
    opens_on: WorldDate
    closes_on: WorldDate
    maximum_squad_size: int
    minimum_homegrown_players: int = 0
    maximum_non_homegrown_players: int | None = None

    def __post_init__(self) -> None:
        validate_id(self.competition_id, kind="registration competition ID")
        validate_id(self.ruleset_id, kind="registration ruleset ID")
        if not isinstance(self.opens_on, WorldDate) or not isinstance(self.closes_on, WorldDate):
            raise TypeError("registration policy requires explicit dates")
        if self.closes_on < self.opens_on:
            raise ValueError("registration window closes before it opens")
        if type(self.maximum_squad_size) is not int or self.maximum_squad_size <= 0:
            raise ValueError("registration squad limit must be a positive integer")
        if (type(self.minimum_homegrown_players) is not int
                or not 0 <= self.minimum_homegrown_players <= self.maximum_squad_size):
            raise ValueError("minimum homegrown count must fit within the squad limit")
        if (self.maximum_non_homegrown_players is not None
                and (type(self.maximum_non_homegrown_players) is not int
                     or not 0 <= self.maximum_non_homegrown_players <= self.maximum_squad_size)):
            raise ValueError("non-homegrown limit must fit within the squad limit")


@dataclass(frozen=True)
class PlayerTrainingRecord:
    player_id: str
    trained_at_club_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="registration player ID")
        if not isinstance(self.trained_at_club_ids, tuple):
            raise TypeError("training club history must be an immutable tuple")
        for club_id in self.trained_at_club_ids:
            validate_id(club_id, kind="training club ID")
        if len(self.trained_at_club_ids) != len(set(self.trained_at_club_ids)):
            raise ValueError("training club history cannot repeat a club")

    def is_homegrown_for(self, club_id: str) -> bool:
        validate_id(club_id, kind="homegrown club ID")
        return club_id in self.trained_at_club_ids


@dataclass(frozen=True)
class ClubCompetitionSquad:
    competition_id: str
    club_id: str
    registered_player_ids: tuple[str, ...] = ()
    loan_reserve_player_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.competition_id, kind="squad competition ID")
        validate_id(self.club_id, kind="squad club ID")
        for label, values in (("registered players", self.registered_player_ids),
                              ("loan reserve players", self.loan_reserve_player_ids)):
            if not isinstance(values, tuple):
                raise TypeError(f"{label} must be an immutable tuple")
            for player_id in values:
                validate_id(player_id, kind="squad player ID")
            if len(values) != len(set(values)):
                raise ValueError(f"{label} cannot repeat a player")
        if set(self.registered_player_ids) & set(self.loan_reserve_player_ids):
            raise ValueError("a squad player cannot be registered and loan-reserved together")


@dataclass(frozen=True)
class RegistrationBook:
    policies: tuple[RegistrationPolicy, ...] = ()
    player_training: tuple[PlayerTrainingRecord, ...] = ()
    squads: tuple[ClubCompetitionSquad, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported registration schema version")
        groups = (("policies", self.policies, RegistrationPolicy),
                  ("training records", self.player_training, PlayerTrainingRecord),
                  ("squads", self.squads, ClubCompetitionSquad))
        for label, values, expected in groups:
            if not isinstance(values, tuple) or any(not isinstance(item, expected) for item in values):
                raise TypeError(f"registration {label} must be immutable {expected.__name__} records")
        if len({item.competition_id for item in self.policies}) != len(self.policies):
            raise ValueError("competition registration policies must be unique")
        if len({item.player_id for item in self.player_training}) != len(self.player_training):
            raise ValueError("player training records must be unique")
        if len({(item.competition_id, item.club_id) for item in self.squads}) != len(self.squads):
            raise ValueError("club/competition registration squads must be unique")
        facts = {item.player_id for item in self.player_training}
        for squad in self.squads:
            if any(player_id not in facts for player_id in squad.registered_player_ids + squad.loan_reserve_player_ids):
                raise ValueError("registered and reserved players require training records")
            policy = next((item for item in self.policies if item.competition_id == squad.competition_id), None)
            if policy is not None:
                squad_size = len(squad.registered_player_ids) + len(squad.loan_reserve_player_ids)
                if squad_size > policy.maximum_squad_size:
                    raise ValueError("registered and reserved squad exceeds its configured size")
                non_homegrown = sum(
                    not next(record for record in self.player_training if record.player_id == player_id)
                    .is_homegrown_for(squad.club_id)
                    for player_id in squad.registered_player_ids
                )
                if (policy.maximum_non_homegrown_players is not None
                        and non_homegrown > policy.maximum_non_homegrown_players):
                    raise ValueError("registered squad exceeds its non-homegrown limit")
                if squad_size == policy.maximum_squad_size:
                    homegrown = sum(
                        next(record for record in self.player_training if record.player_id == player_id)
                        .is_homegrown_for(squad.club_id)
                        for player_id in squad.registered_player_ids
                    )
                    if homegrown < policy.minimum_homegrown_players:
                        raise ValueError("full registered squad fails its minimum homegrown rule")
        competition_ids = ({item.competition_id for item in self.policies}
                           | {item.competition_id for item in self.squads})
        for competition_id in competition_ids:
            assigned: dict[str, str] = {}
            reserved: dict[str, str] = {}
            for squad in self.squads:
                if squad.competition_id != competition_id:
                    continue
                overlap = set(assigned) & set(squad.registered_player_ids)
                if overlap:
                    raise ValueError("a player cannot be actively registered to two clubs in one competition")
                for player_id in squad.registered_player_ids:
                    assigned[player_id] = squad.club_id
                for player_id in squad.loan_reserve_player_ids:
                    if player_id in reserved:
                        raise ValueError("a player cannot have loan slots reserved by two clubs")
                    reserved[player_id] = squad.club_id
            for player_id, owner_club_id in reserved.items():
                registered_club_id = assigned.get(player_id)
                if registered_club_id is None or registered_club_id == owner_club_id:
                    raise ValueError("loan reserve requires one active registration at another club")

    def to_json(self) -> str:
        return dumps(self)

    @classmethod
    def from_json(cls, value: str) -> RegistrationBook:
        try:
            return loads(value, cls)
        except SerializationError as exc:
            raise ValueError(f"invalid registration book: {exc}") from exc


@dataclass(frozen=True)
class RegistrationCheck:
    check_id: str
    competition_id: str
    club_id: str
    player_id: str
    assessed_on: WorldDate
    ruleset_id: str
    eligible: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        for label, value in (("registration check ID", self.check_id),
                             ("registration competition ID", self.competition_id),
                             ("registration club ID", self.club_id),
                             ("registration player ID", self.player_id),
                             ("registration ruleset ID", self.ruleset_id)):
            validate_id(value, kind=label)
        if not isinstance(self.assessed_on, WorldDate):
            raise TypeError("registration assessment requires a WorldDate")
        if type(self.eligible) is not bool or not isinstance(self.reasons, tuple):
            raise TypeError("registration decision requires a boolean and immutable reasons")
        if any(not isinstance(item, str) or not item for item in self.reasons):
            raise ValueError("registration reasons must be non-empty codes")
        if self.eligible != (not self.reasons):
            raise ValueError("eligible registration checks cannot contain blocking reasons")


def _squad(book: RegistrationBook, competition_id: str, club_id: str) -> ClubCompetitionSquad:
    return next((item for item in book.squads
                 if item.competition_id == competition_id and item.club_id == club_id),
                ClubCompetitionSquad(competition_id, club_id))


def check_registration(book: RegistrationBook, competition_id: str, club_id: str,
                       player_id: str, on: WorldDate, *,
                       moving_from_club_id: str | None = None) -> RegistrationCheck:
    if not isinstance(book, RegistrationBook) or not isinstance(on, WorldDate):
        raise TypeError("registration check requires a RegistrationBook and date")
    for value, label in ((competition_id, "competition ID"), (club_id, "club ID"),
                         (player_id, "player ID")):
        validate_id(value, kind=label)
    if moving_from_club_id is not None:
        validate_id(moving_from_club_id, kind="moving registration source club ID")
        if moving_from_club_id == club_id:
            raise ValueError("registration source and destination clubs must differ")
    policy = next((item for item in book.policies if item.competition_id == competition_id), None)
    if policy is None:
        raise KeyError(f"no registration rules for competition {competition_id}")
    facts = next((item for item in book.player_training if item.player_id == player_id), None)
    if facts is None:
        raise KeyError(f"no registration training record for player {player_id}")
    squad = _squad(book, competition_id, club_id)
    reasons: list[str] = []
    if not policy.opens_on <= on <= policy.closes_on:
        reasons.append("registration_window_closed")
    if player_id in squad.registered_player_ids:
        reasons.append("already_registered")
    if player_id in squad.loan_reserve_player_ids:
        reasons.append("already_reserved_by_club")
    elsewhere = any(
        item.competition_id == competition_id and item.club_id != club_id
        and item.club_id != moving_from_club_id
        and player_id in item.registered_player_ids
        for item in book.squads
    )
    if elsewhere:
        reasons.append("registered_to_another_club")
    current_size = len(squad.registered_player_ids) + len(squad.loan_reserve_player_ids)
    if current_size >= policy.maximum_squad_size:
        reasons.append("squad_limit_reached")
    homegrown = facts.is_homegrown_for(club_id)
    non_homegrown = not homegrown
    if non_homegrown and policy.maximum_non_homegrown_players is not None:
        registered_non_homegrown = sum(
            not next(record for record in book.player_training if record.player_id == item).is_homegrown_for(club_id)
            for item in squad.registered_player_ids
        )
        if registered_non_homegrown >= policy.maximum_non_homegrown_players:
            reasons.append("non_homegrown_limit_reached")
    if not homegrown and policy.minimum_homegrown_players:
        homegrown_count = sum(
            next(record for record in book.player_training if record.player_id == item).is_homegrown_for(club_id)
            for item in squad.registered_player_ids
        )
        remaining_capacity = max(0, policy.maximum_squad_size - current_size - 1)
        if homegrown_count + remaining_capacity < policy.minimum_homegrown_players:
            reasons.append("minimum_homegrown_not_reachable")
    ordered_reasons = tuple(dict.fromkeys(reasons))
    return RegistrationCheck(
        derive_id("registration-check", "p15c-registration-check-v1", competition_id,
                  club_id, player_id, on.isoformat, policy.ruleset_id),
        competition_id, club_id, player_id, on, policy.ruleset_id,
        not ordered_reasons, ordered_reasons,
    )


def check_existing_registration(book: RegistrationBook, competition_id: str,
                                club_id: str, player_id: str,
                                on: WorldDate) -> RegistrationCheck:
    """Confirm a current registration can continue outside a registration window."""
    if not isinstance(book, RegistrationBook) or not isinstance(on, WorldDate):
        raise TypeError("existing-registration check requires a RegistrationBook and date")
    for value, label in ((competition_id, "competition ID"), (club_id, "club ID"),
                         (player_id, "player ID")):
        validate_id(value, kind=label)
    policy = next((item for item in book.policies if item.competition_id == competition_id), None)
    if policy is None:
        raise KeyError(f"no registration rules for competition {competition_id}")
    squad = _squad(book, competition_id, club_id)
    eligible = player_id in squad.registered_player_ids
    reasons = () if eligible else ("not_currently_registered",)
    return RegistrationCheck(
        derive_id("registration-check", "p15c-registration-continued-v1",
                  competition_id, club_id, player_id, on.isoformat, policy.ruleset_id),
        competition_id, club_id, player_id, on, policy.ruleset_id, eligible, reasons,
    )


def register_new_player(
    book: RegistrationBook,
    player_id: str,
    club_id: str,
    trained_at_club_ids: tuple[str, ...],
    competition_ids: tuple[str, ...],
    on: WorldDate,
) -> tuple[RegistrationBook, tuple[RegistrationCheck, ...]]:
    """Add explicit training history and register a new player in every named competition.

    The entire operation is immutable and all checks run against the evolving
    candidate snapshot before a replacement book is returned. Callers therefore
    cannot commit only a subset of the requested competition registrations.
    """
    if not isinstance(book, RegistrationBook) or not isinstance(on, WorldDate):
        raise TypeError("new-player registration requires a book and explicit date")
    validate_id(player_id, kind="registration player ID")
    validate_id(club_id, kind="registration club ID")
    if not isinstance(trained_at_club_ids, tuple):
        raise TypeError("new-player training history must be an immutable tuple")
    training = PlayerTrainingRecord(player_id, trained_at_club_ids)
    if not isinstance(competition_ids, tuple) or not competition_ids:
        raise ValueError("new-player registration requires at least one competition")
    for competition_id in competition_ids:
        validate_id(competition_id, kind="registration competition ID")
    if competition_ids != tuple(sorted(set(competition_ids))):
        raise ValueError("new-player competitions must be unique and ID-ordered")
    if any(item.player_id == player_id for item in book.player_training):
        raise ValueError("new-player registration requires a previously unknown player")
    configured = {item.competition_id for item in book.policies}
    if any(item not in configured for item in competition_ids):
        raise KeyError("new-player registration names an unconfigured competition")

    candidate = RegistrationBook(
        book.policies,
        tuple(sorted(book.player_training + (training,), key=lambda item: item.player_id)),
        book.squads,
    )
    checks = tuple(
        check_registration(candidate, competition_id, club_id, player_id, on)
        for competition_id in competition_ids
    )
    denied = tuple(
        f"{item.competition_id}:{reason}"
        for item in checks for reason in item.reasons
    )
    if denied:
        raise ValueError("new-player registration failed: " + ", ".join(denied))

    squads = {(item.competition_id, item.club_id): item for item in candidate.squads}
    for check in checks:
        current = squads.get(
            (check.competition_id, check.club_id),
            ClubCompetitionSquad(check.competition_id, check.club_id),
        )
        squads[(check.competition_id, check.club_id)] = replace(
            current,
            registered_player_ids=tuple(sorted(current.registered_player_ids + (player_id,))),
        )
    updated = RegistrationBook(
        candidate.policies, candidate.player_training,
        tuple(sorted(squads.values(), key=lambda item: (item.competition_id, item.club_id))),
    )
    return updated, checks


def _release_retired_player(book: RegistrationBook, player_id: str) -> RegistrationBook:
    """Remove retired player slots but keep sourced training history for archives."""
    if not isinstance(book, RegistrationBook):
        raise TypeError("retirement registration release requires a RegistrationBook")
    validate_id(player_id, kind="retired registration player ID")
    if not any(item.player_id == player_id for item in book.player_training):
        return book
    updated = tuple(
        replace(
            squad,
            registered_player_ids=tuple(
                item for item in squad.registered_player_ids if item != player_id
            ),
            loan_reserve_player_ids=tuple(
                item for item in squad.loan_reserve_player_ids if item != player_id
            ),
        )
        for squad in book.squads
    )
    if updated == book.squads:
        return book
    return RegistrationBook(book.policies, book.player_training, updated)


def _validate_loan_registration_args(
    book: RegistrationBook,
    player_id: str,
    owner_club_id: str,
    borrower_club_id: str,
    competition_ids: tuple[str, ...],
) -> None:
    if not isinstance(book, RegistrationBook):
        raise TypeError("loan registration changes require a RegistrationBook")
    for value, label in ((player_id, "loan player ID"), (owner_club_id, "loan owner club ID"),
                         (borrower_club_id, "loan borrower club ID")):
        validate_id(value, kind=label)
    if owner_club_id == borrower_club_id:
        raise ValueError("loan owner and borrower must be different clubs")
    if not isinstance(competition_ids, tuple) or not competition_ids:
        raise ValueError("a loan must name at least one competition registration")
    for competition_id in competition_ids:
        validate_id(competition_id, kind="loan competition ID")
    if len(competition_ids) != len(set(competition_ids)):
        raise ValueError("loan competition list cannot repeat a competition")
    configured = {item.competition_id for item in book.policies}
    if any(item not in configured for item in competition_ids):
        raise KeyError("loan registration references a competition without configured rules")


def _loan_registration_states(book: RegistrationBook, player_id: str, owner_club_id: str,
                              borrower_club_id: str,
                              competition_ids: tuple[str, ...]) -> tuple[str, ...]:
    states: list[str] = []
    for competition_id in competition_ids:
        owner = _squad(book, competition_id, owner_club_id)
        borrower = _squad(book, competition_id, borrower_club_id)
        owner_registered = player_id in owner.registered_player_ids
        owner_reserved = player_id in owner.loan_reserve_player_ids
        borrower_registered = player_id in borrower.registered_player_ids
        if owner_registered and not owner_reserved and not borrower_registered:
            states.append("source")
        elif not owner_registered and owner_reserved and borrower_registered:
            states.append("loaned")
        elif not owner_registered and not owner_reserved and borrower_registered:
            states.append("purchased")
        else:
            states.append("conflict")
    return tuple(states)


def register_loan_player(book: RegistrationBook, player_id: str, owner_club_id: str,
                         borrower_club_id: str, competition_ids: tuple[str, ...],
                         on: WorldDate) -> RegistrationBook:
    _validate_loan_registration_args(book, player_id, owner_club_id,
                                     borrower_club_id, competition_ids)
    if not isinstance(on, WorldDate):
        raise TypeError("loan registration requires a WorldDate")
    states = _loan_registration_states(book, player_id, owner_club_id,
                                       borrower_club_id, competition_ids)
    if all(state == "loaned" for state in states):
        return book
    if not all(state == "source" for state in states):
        raise ValueError("loaned player must be registered at the owning club before the move")
    checks = tuple(check_registration(
        book, competition_id, borrower_club_id, player_id, on,
        moving_from_club_id=owner_club_id,
    )
                   for competition_id in competition_ids)
    denied = tuple(f"{item.competition_id}:{reason}" for item in checks for reason in item.reasons)
    if denied:
        raise ValueError("loan registration failed: " + ", ".join(denied))
    updated: list[ClubCompetitionSquad] = []
    for competition_id in competition_ids:
        owner = _squad(book, competition_id, owner_club_id)
        borrower = _squad(book, competition_id, borrower_club_id)
        updated.append(replace(
            owner,
            registered_player_ids=tuple(item for item in owner.registered_player_ids if item != player_id),
            loan_reserve_player_ids=owner.loan_reserve_player_ids + (player_id,),
        ))
        updated.append(replace(borrower, registered_player_ids=borrower.registered_player_ids + (player_id,)))
    squads = {(item.competition_id, item.club_id): item for item in book.squads}
    squads.update({(item.competition_id, item.club_id): item for item in updated})
    return RegistrationBook(book.policies, book.player_training,
                           tuple(sorted(squads.values(), key=lambda item: (item.competition_id, item.club_id))))


def return_loan_player(book: RegistrationBook, player_id: str, owner_club_id: str,
                       borrower_club_id: str, competition_ids: tuple[str, ...]) -> RegistrationBook:
    _validate_loan_registration_args(book, player_id, owner_club_id,
                                     borrower_club_id, competition_ids)
    states = _loan_registration_states(book, player_id, owner_club_id,
                                       borrower_club_id, competition_ids)
    # A completed return restores the exact source state. The high-level loan
    # lifecycle verifies that a loan was active before requesting this move.
    if all(state == "source" for state in states):
        return book
    if not all(state == "loaned" for state in states):
        raise ValueError("return requires every competition to hold the same active loan state")
    updated: list[ClubCompetitionSquad] = []
    for competition_id in competition_ids:
        owner = _squad(book, competition_id, owner_club_id)
        borrower = _squad(book, competition_id, borrower_club_id)
        if player_id not in owner.loan_reserve_player_ids or player_id not in borrower.registered_player_ids:
            raise ValueError("return requires the owner's reserved slot and the borrower's registration")
        updated.append(replace(
            owner,
            registered_player_ids=owner.registered_player_ids + (player_id,),
            loan_reserve_player_ids=tuple(item for item in owner.loan_reserve_player_ids if item != player_id),
        ))
        updated.append(replace(
            borrower,
            registered_player_ids=tuple(item for item in borrower.registered_player_ids if item != player_id),
        ))
    squads = {(item.competition_id, item.club_id): item for item in book.squads}
    squads.update({(item.competition_id, item.club_id): item for item in updated})
    return RegistrationBook(book.policies, book.player_training,
                           tuple(sorted(squads.values(), key=lambda item: (item.competition_id, item.club_id))))


def purchase_loan_player(book: RegistrationBook, player_id: str, owner_club_id: str,
                         borrower_club_id: str, competition_ids: tuple[str, ...]) -> RegistrationBook:
    _validate_loan_registration_args(book, player_id, owner_club_id,
                                     borrower_club_id, competition_ids)
    states = _loan_registration_states(book, player_id, owner_club_id,
                                       borrower_club_id, competition_ids)
    if all(state == "purchased" for state in states):
        return book
    if not all(state == "loaned" for state in states):
        raise ValueError("purchase requires every competition to hold the same active loan state")
    updated: list[ClubCompetitionSquad] = []
    for competition_id in competition_ids:
        owner = _squad(book, competition_id, owner_club_id)
        borrower = _squad(book, competition_id, borrower_club_id)
        if player_id not in owner.loan_reserve_player_ids or player_id not in borrower.registered_player_ids:
            raise ValueError("purchase requires the owner's reserved slot and the borrower's registration")
        updated.append(replace(
            owner,
            loan_reserve_player_ids=tuple(item for item in owner.loan_reserve_player_ids if item != player_id),
        ))
    squads = {(item.competition_id, item.club_id): item for item in book.squads}
    squads.update({(item.competition_id, item.club_id): item for item in updated})
    return RegistrationBook(book.policies, book.player_training,
                           tuple(sorted(squads.values(), key=lambda item: (item.competition_id, item.club_id))))


__all__ = [
    "ClubCompetitionSquad", "PlayerTrainingRecord", "RegistrationBook",
    "RegistrationCheck", "RegistrationPolicy", "check_existing_registration", "check_registration",
    "purchase_loan_player", "register_loan_player", "return_loan_player",
]
