from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError, dataclass
from datetime import date
from pathlib import Path

from games.touchline.checks.replay_scenario import new_replay_state, run_synthetic_updates
from games.touchline.esb.commands import (
    CommandEffect,
    CommandEnvelope,
    CommandLedger,
    CommandProcessor,
    CommandRejection,
)
from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import (
    new_club_id,
    new_command_id,
    new_event_id,
    new_player_id,
    validate_id,
)
from games.touchline.esb.model import (
    Capability,
    CapabilitySnapshot,
    CareerState,
    ClubKnowledge,
    HistoryKind,
    HistoryReference,
    KnowledgeEntry,
    MatchState,
    Measurement,
    Money,
    PlayerIdentity,
    Position2D,
)
from games.touchline.esb.randomness import RandomStreams
from games.touchline.esb.schedule import (
    ScheduledWork,
    SettlementKey,
    SettlementReceipt,
    order_scheduled_work,
)
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.state import SimulationState
from games.touchline.esb.time import MatchClock, WorldDate

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class SlotState:
    available: int


def _slot_command(command_id: str, key: str, units: int) -> CommandEnvelope:
    return CommandEnvelope(
        command_id=new_command_id("p01-core-02", command_id),
        idempotency_key=key,
        command_type="reserve_slots",
        payload_json=json.dumps({"units": units}),
    )


def _slot_processor() -> CommandProcessor[SlotState]:
    def validate(state: SlotState, command: CommandEnvelope) -> CommandRejection | None:
        units = command.payload["units"]
        if type(units) is not int or units <= 0:
            return CommandRejection("invalid_units", "units must be a positive integer")
        if units > state.available:
            return CommandRejection("insufficient_slots", "not enough slots remain")
        return None

    def apply(state: SlotState, command: CommandEnvelope) -> CommandEffect:
        units = command.payload["units"]
        state.available -= units
        event = EventEnvelope(
            event_id=new_event_id("p01-core-02", str(command.command_id)),
            aggregate_type="career",
            aggregate_id="career:p01-test",
            sequence=0,
            kind="synthetic_slots_reserved",
            world_date=WorldDate(date(2026, 9, 24)),
            payload_json=json.dumps({"units": units}),
            outcome_json=json.dumps({"available": state.available}),
        )
        return CommandEffect(
            events=(event,),
            result_json=json.dumps({"available": state.available}),
        )

    return CommandProcessor(validate, apply)


class CoreReplayTests(unittest.TestCase):
    def test_core_01_resume_in_another_process_matches_uninterrupted_run(self) -> None:
        uninterrupted = run_synthetic_updates(new_replay_state(), 8)
        interrupted = run_synthetic_updates(new_replay_state(), 3)

        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run(
            [sys.executable, "-m", "games.touchline.checks.replay_worker", "5"],
            cwd=REPO_ROOT,
            input=dumps(interrupted),
            text=True,
            capture_output=True,
            check=True,
            env=env,
        )
        resumed = loads(result.stdout, SimulationState)
        self.assertEqual(dumps(resumed), dumps(uninterrupted))
        self.assertEqual([event.sequence for event in resumed.events], list(range(8)))
        self.assertEqual([event.event_id for event in resumed.events], [event.event_id for event in uninterrupted.events])
        for stream in ("football", "world", "reporting"):
            self.assertEqual(
                resumed.random_streams.stream(stream).next_u64(),
                uninterrupted.random_streams.stream(stream).next_u64(),
            )

    def test_reporting_draws_do_not_consume_the_football_stream(self) -> None:
        with_reports = RandomStreams.seeded(90210)
        without_reports = RandomStreams.seeded(90210)
        self.assertEqual(
            with_reports.stream("football").next_u64(),
            without_reports.stream("football").next_u64(),
        )
        with self.assertRaises(ValueError):
            RandomStreams(root_seed=17, streams={})
        for _ in range(100):
            with_reports.stream("reporting").next_u64()
        self.assertEqual(
            with_reports.stream("football").next_u64(),
            without_reports.stream("football").next_u64(),
        )


class CommandBoundaryTests(unittest.TestCase):
    def test_core_02_invalid_command_is_atomic_and_retry_is_once_only(self) -> None:
        processor = _slot_processor()
        original = SlotState(available=3)
        ledger = CommandLedger()

        invalid = processor.execute(original, ledger, _slot_command("invalid", "bad-request", 4))
        self.assertFalse(invalid.receipt.accepted)
        self.assertEqual(invalid.receipt.rejection.code, "insufficient_slots")
        self.assertEqual(invalid.state, original)
        self.assertIs(invalid.ledger, ledger)
        self.assertEqual(invalid.ledger.events, ())
        self.assertEqual(invalid.ledger.receipts, ())

        command = _slot_command("valid", "reserve-round-1", 2)
        first = processor.execute(original, ledger, command)
        self.assertTrue(first.receipt.accepted)
        self.assertEqual(first.state.available, 1)
        self.assertEqual(len(first.ledger.events), 1)
        self.assertEqual(len(first.ledger.receipts), 1)

        retry = processor.execute(first.state, first.ledger, command)
        self.assertTrue(retry.replayed)
        self.assertIs(retry.state, first.state)
        self.assertIs(retry.ledger, first.ledger)
        self.assertEqual(retry.state.available, 1)
        self.assertEqual(len(retry.ledger.events), 1)
        self.assertEqual(len(retry.ledger.receipts), 1)

        conflicting = processor.execute(
            first.state,
            first.ledger,
            _slot_command("different-body", "reserve-round-1", 1),
        )
        self.assertFalse(conflicting.receipt.accepted)
        self.assertEqual(conflicting.receipt.rejection.code, "idempotency_key_reused")
        self.assertIs(conflicting.state, first.state)
        self.assertIs(conflicting.ledger, first.ledger)

    def test_validation_side_effects_are_confined_to_the_validation_copy(self) -> None:
        original = SlotState(available=3)

        def mutate_then_reject(state: SlotState, command: CommandEnvelope) -> CommandRejection:
            state.available = 0
            return CommandRejection("denied", "deliberate rejection after a bad validator mutation")

        def never_apply(state: SlotState, command: CommandEnvelope) -> CommandEffect:
            self.fail("rejected command must never reach apply")

        processor = CommandProcessor(mutate_then_reject, never_apply)
        ledger = CommandLedger()
        result = processor.execute(original, ledger, _slot_command("invalid-mutation", "bad-mutation", 1))
        self.assertEqual(result.state.available, 3)
        self.assertIs(result.state, original)
        self.assertIs(result.ledger, ledger)


class RecordContractTests(unittest.TestCase):
    def test_time_units_and_equal_tick_event_order_are_explicit(self) -> None:
        clock = MatchClock(tick=8, tick_duration_ms=250)
        self.assertEqual(clock.elapsed_milliseconds, 2_000)
        self.assertEqual(clock.advance(2), MatchClock(tick=10, tick_duration_ms=250))
        world_date = WorldDate(date(2026, 9, 24))
        self.assertEqual(world_date.isoformat, "2026-09-24")

        match_id = "match:order"
        events = tuple(
            EventEnvelope(
                event_id=new_event_id("equal-tick", index),
                aggregate_type="match",
                aggregate_id=match_id,
                sequence=index,
                kind="test_event",
                match_id=match_id,
                match_tick=8,
                world_date=world_date,
            )
            for index in (1, 0)
        )
        self.assertEqual([event.sequence for event in sorted(events, key=lambda event: (event.match_tick, event.sequence))], [0, 1])
        self.assertEqual(Position2D(10.5, 20.0).x_m, 10.5)
        self.assertEqual(Money(101, "GBP").amount_minor, 101)
        self.assertEqual(Measurement("top_speed", 9.2, "m/s").unit, "m/s")

    def test_records_are_separate_immutable_where_promised_and_keep_unknowns(self) -> None:
        player_id = new_player_id("record-test", "p1")
        club_id = new_club_id("record-test", "club")
        snapshot = CapabilitySnapshot(
            player_id=player_id,
            version=1,
            capabilities=(Capability("anticipation", 0.61),),
            measurements=(Measurement("height", 1.82, "m"),),
        )
        with self.assertRaises(FrozenInstanceError):
            snapshot.version = 2  # type: ignore[misc]

        identity = PlayerIdentity(player_id=player_id)
        self.assertEqual(identity.history, ())
        self.assertIsNone(identity.birth_date)
        unknown = KnowledgeEntry("player:unknown", "preferred_foot", unavailable_reason="not_observed")
        knowledge = ClubKnowledge(club_id, WorldDate(date(2026, 9, 24)), (unknown,))
        self.assertIsNone(knowledge.entries[0].value_json)
        with self.assertRaises(ValueError):
            KnowledgeEntry("player:unknown", "rating", value_json="null")
        with self.assertRaises(ValueError):
            KnowledgeEntry("player:unknown", "rating", value_json='{"rating":NaN}')
        with self.assertRaises(ValueError):
            Capability(player_id.__str__(), 1.01)

        career = CareerState("career:one", club_id, WorldDate(date(2026, 9, 24)))
        match = MatchState("match:one", club_id, "club:away", MatchClock(0, 250))
        self.assertEqual(career.club_id, match.home_club_id)
        self.assertNotIsInstance(career, MatchState)

        history = HistoryReference(HistoryKind.EXPERIENCE, new_event_id("experience", "e1"), WorldDate(date(2026, 9, 20)))
        self.assertEqual(history.kind, HistoryKind.EXPERIENCE)
        for record in (snapshot, identity, career, match, knowledge):
            self.assertEqual(loads(dumps(record), type(record)), record)

    def test_schedule_order_and_settlement_identity_are_repeatable(self) -> None:
        first_date = WorldDate(date(2026, 9, 25))
        second_date = WorldDate(date(2026, 9, 26))
        work = (
            ScheduledWork("work:b", first_date, 1, "training"),
            ScheduledWork("work:c", second_date, 0, "fixture"),
            ScheduledWork("work:a", first_date, 0, "recovery"),
        )
        self.assertEqual([item.work_id for item in order_scheduled_work(work)], ["work:a", "work:b", "work:c"])
        key = SettlementKey("match-result", "match:one")
        receipt = SettlementReceipt(key, second_date, new_event_id("settlement", "match:one"), Money(500, "GBP"))
        self.assertEqual(key.idempotency_key, SettlementKey("match-result", "match:one").idempotency_key)
        self.assertNotEqual(
            SettlementKey("a/b", "c").idempotency_key,
            SettlementKey("a", "b/c").idempotency_key,
        )
        self.assertEqual(loads(dumps(receipt), SettlementReceipt), receipt)

    def test_versioned_round_trip_and_invalid_schema_leave_input_data_alone(self) -> None:
        state = run_synthetic_updates(new_replay_state(), 2)
        encoded = dumps(state)
        decoded = loads(encoded, SimulationState)
        self.assertEqual(dumps(decoded), encoded)
        self.assertEqual(state.events, decoded.events)
        with self.assertRaises(SerializationError):
            loads(encoded.replace('"schema_version":1', '"schema_version":999', 1), SimulationState)
        self.assertEqual(dumps(state), encoded)

    def test_stable_ids_do_not_depend_on_process_hash_randomization(self) -> None:
        first = new_player_id("stable", "academy", 17)
        second = new_player_id("stable", "academy", 17)
        self.assertEqual(first, second)
        self.assertEqual(validate_id(str(first), kind="player ID"), str(first))
        with self.assertRaises(ValueError):
            validate_id("contains spaces")

    def test_domain_imports_do_not_open_files_or_load_terminal_sdk(self) -> None:
        script = r'''
import builtins, importlib, io, pathlib, sys
def blocked(*args, **kwargs):
    raise AssertionError("domain import attempted file I/O")
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
for module in (
    "games.touchline.esb.ids", "games.touchline.esb.time", "games.touchline.esb.model",
    "games.touchline.esb.randomness", "games.touchline.esb.events", "games.touchline.esb.commands",
    "games.touchline.esb.schedule", "games.touchline.esb.serialization", "games.touchline.esb.state",
):
    importlib.import_module(module)
assert "curses" not in sys.modules
assert "termstation_ui" not in sys.modules
assert not any(name.startswith("termstation.") for name in sys.modules)
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
