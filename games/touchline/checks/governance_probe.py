"""Small deterministic P12 governance fixture for process-isolation checks."""

from __future__ import annotations

from datetime import date

from games.touchline.esb.club.governance import (
    Appointment,
    AuthorityAction,
    AuthorityGrant,
    AuthorityPolicy,
    BudgetBook,
    BudgetProposal,
    ClubGovernance,
    ClubRole,
    create_budget_proposal,
    decide_budget_proposal,
)
from games.touchline.esb.ids import ClubId
from games.touchline.esb.serialization import dumps
from games.touchline.esb.time import WorldDate

START = WorldDate(date(2026, 10, 5))


def build_probe_record() -> ClubGovernance:
    club_id = ClubId("club:p12-probe")
    owner = Appointment(
        "appointment:p12-probe-owner", club_id, "person:p12-owner", ClubRole.OWNER,
        START, None,
        (AuthorityGrant(AuthorityAction.PROPOSE_BUDGET, 100_000),
         AuthorityGrant(AuthorityAction.ALLOCATE_BUDGET)),
    )
    manager = Appointment(
        "appointment:p12-probe-manager", club_id, "person:p12-manager", ClubRole.MANAGER,
        START, None,
        (AuthorityGrant(AuthorityAction.PROPOSE_BUDGET, 10_000),
         AuthorityGrant(AuthorityAction.ALLOCATE_BUDGET, 5_000)),
    )
    state = ClubGovernance(
        club_id, AuthorityPolicy(club_id, board_approval_above_minor=4_000),
        BudgetBook(club_id, "NAD", 40_000), appointments=(owner, manager),
    )
    proposal = BudgetProposal(
        "proposal:p12-probe", club_id, "recruitment", 3_000, "NAD",
        manager.appointment_id, START, "synthetic approved recruitment allocation",
    )
    proposed = create_budget_proposal(state, manager.appointment_id, proposal, START)
    if not proposed.accepted:
        raise AssertionError(proposed.rejection)
    result = decide_budget_proposal(
        proposed.state, manager.appointment_id, proposal.proposal_id, True, START,
    )
    if not result.accepted:
        raise AssertionError(result.rejection)
    return result.state


if __name__ == "__main__":
    print(dumps(build_probe_record()))
