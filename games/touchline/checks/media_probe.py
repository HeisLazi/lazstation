"""Deterministic fresh-process probe for P14 media projection."""

from __future__ import annotations

import json
from datetime import date

from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import ClubId, EventId, MatchId
from games.touchline.esb.media.publication import (
    EditorialFrame,
    EventWorldMoment,
    MatchMediaSource,
    MatchPlayerClub,
    MediaLedger,
    Outlet,
    OutletTier,
    publish_story,
)
from games.touchline.esb.people.relationships import WorldMoment
from games.touchline.esb.serialization import dumps
from games.touchline.esb.time import WorldDate


def run_probe() -> dict[str, object]:
    match_id = MatchId("match:p14-probe")
    home = ClubId("club:p14-probe-home")
    away = ClubId("club:p14-probe-away")
    match_event = EventEnvelope(
        EventId("event:p14-probe-goal"),
        "match",
        str(match_id),
        4,
        "goal",
        match_id,
        960,
        payload_json=json.dumps({
            "actor_id": "player:p14-probe-striker",
            "assist_player_id": "player:p14-probe-midfielder",
            "team_id": "home",
            "scoring_team_id": "home",
            "tracking_debug": "omitted from the public projection",
        }, sort_keys=True, separators=(",", ":")),
        outcome_json='{"home_score":2,"away_score":1,"private_xg":0.42}',
    )
    source = MatchMediaSource(
        match_id,
        home,
        away,
        (
            MatchPlayerClub("player:p14-probe-midfielder", "home", home),
            MatchPlayerClub("player:p14-probe-striker", "home", home),
            MatchPlayerClub("player:p14-probe-visitor", "away", away),
        ),
        (match_event,),
        (EventWorldMoment(match_event.event_id, WorldMoment(WorldDate(date(2026, 10, 5)), 32)),),
        EventId("event:p14-probe-calendar-source"),
    )
    outlet = Outlet(
        "outlet:p14-probe-regional",
        "Probe regional sports desk",
        OutletTier.REGIONAL,
        (home,),
        80_000,
    )
    ledger, story = publish_story(
        MediaLedger((outlet,)),
        source,
        source_event_id=match_event.event_id,
        outlet_id=outlet.outlet_id,
        published_at=WorldMoment(WorldDate(date(2026, 10, 5)), 40),
        frame=EditorialFrame.STRAIGHT,
    )
    return {
        "story_id": str(story.story_id),
        "modeled_reach": story.modeled_reach,
        "formula": story.formula_version,
        "public_kind": story.fact.kind.value,
        "encoded_ledger": json.loads(dumps(ledger)),
    }


def main() -> None:
    print(json.dumps(run_probe(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
