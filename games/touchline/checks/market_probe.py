"""Deterministic fresh-process probe for P15b offer negotiation."""

from __future__ import annotations

import json
from datetime import date

from games.touchline.esb.economy.market import (
    MarketBook,
    MarketCandidate,
    MarketEventKind,
    OfferedRole,
    PlayerMarketProfile,
    TransferOffer,
    add_candidate,
    add_player_profile,
    offer_cost,
    offer_status,
    resolve_player_choice,
    seller_respond,
    submit_offer,
)
from games.touchline.esb.serialization import dumps
from games.touchline.esb.time import WorldDate


def _day(value: int) -> WorldDate:
    return WorldDate(date(2026, 10, value))


def _offer(offer_id: str, buyer_id: str, place_id: str) -> TransferOffer:
    return TransferOffer(
        offer_id,
        "player:p15b-probe",
        buyer_id,
        "club:p15b-seller",
        _day(1),
        _day(10),
        "GBP",
        12_000,
        2_000,
        12,
        OfferedRole.REGULAR,
        place_id,
        ("policy:fair",),
        8_000,
    )


def run_probe() -> dict[str, object]:
    candidate = MarketCandidate(
        "player:p15b-probe",
        "club:p15b-seller",
        "contract:p15b-probe",
        12_000,
        "GBP",
        _day(1),
        _day(30),
    )
    preferences = PlayerMarketProfile(
        "player:p15b-probe",
        1_000,
        2_000,
        8,
        12,
        OfferedRole.REGULAR,
        ("place:north",),
        ("policy:fair",),
        ("policy:fair",),
        ("policy:closed",),
        7_000,
    )
    state = add_candidate(MarketBook(), candidate)
    state = add_player_profile(state, preferences)
    preferred = _offer("offer:p15b-preferred", "club:p15b-buyer-a", "place:north")
    alternative = _offer("offer:p15b-alternative", "club:p15b-buyer-b", "place:south")
    state = submit_offer(submit_offer(state, preferred), alternative)
    state = seller_respond(state, preferred.offer_id, "club:p15b-seller", accept=True, on=_day(2))
    state, choice = resolve_player_choice(state, "player:p15b-probe", _day(3))
    cost = offer_cost(preferred)
    return {
        "chosen_offer_id": choice.chosen_offer_id,
        "closed_offer_count": sum(event.kind is MarketEventKind.CLOSED_COMPETITOR for event in state.events),
        "currency": cost.currency,
        "chosen_offer_status": offer_status(state, preferred.offer_id).value,
        "alternative_status": offer_status(state, alternative.offer_id).value,
        "total_guaranteed_cost_minor": cost.total_guaranteed_cost_minor,
        "encoded_market": json.loads(dumps(state)),
    }


def main() -> None:
    print(json.dumps(run_probe(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
