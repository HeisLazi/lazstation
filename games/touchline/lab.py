"""Standalone terminal entry point for the P07 Tactical Laboratory.

Run with ``python3 -m games.touchline.lab``. This UI does not use the legacy
career screen or the shared TerminalStation SDK.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from games.touchline.esb.match.spatial import Pitch
from games.touchline.esb.model import Position2D
from games.touchline.esb.tactics import TacticalAction, TacticalPhase
from games.touchline.esb.tactical_lab import (
    LAB_SCENARIOS,
    SLOT_INDEX,
    PositionSnapshot,
    TacticalLabPlan,
    TacticalLabRun,
    create_run,
    default_plan,
    load_plan,
    save_plan,
    scenario_by_id,
    set_instruction_action,
    set_player_placement,
)


_ACTION_CYCLE = (
    TacticalAction.MOVE_INSIDE,
    TacticalAction.HOLD_WIDTH,
    TacticalAction.OVERLAP,
    TacticalAction.UNDERLAP,
    TacticalAction.SUPPORT,
    TacticalAction.OFFER_OUTLET,
    TacticalAction.COVER_DEPTH,
    TacticalAction.RETREAT,
)
_PHASE_BY_SCENARIO = {
    "build_up": TacticalPhase.BUILD_UP,
    "pressing": TacticalPhase.DEFENSIVE_BLOCK,
    "compact": TacticalPhase.DEFENSIVE_BLOCK,
    "wide_attack": TacticalPhase.ESTABLISHED_ATTACK,
}
_SYMBOL_BY_SLOT = {
    "GK": "G", "LCB": "1", "RCB": "2", "LB": "b", "RB": "r",
    "DM": "D", "LCM": "c", "RCM": "m", "LW": "w", "RW": "W", "ST": "S",
}


def _put(screen, row: int, column: int, value: object) -> None:
    height, width = screen.getmaxyx()
    if row < 0 or row >= height or column < 0 or column >= width - 1:
        return
    text = str(value)
    try:
        screen.addnstr(row, column, text, max(0, width - column - 1))
    except Exception:
        # Resizes may invalidate one draw operation; the next iteration redraws.
        return


def _draw_pitch(screen, y: int, x: int, width: int, height: int,
                samples, *, selected_slot: str | None = None) -> None:
    width = min(width, max(12, screen.getmaxyx()[1] - x - 1))
    height = min(height, max(5, screen.getmaxyx()[0] - y - 2))
    if width < 12 or height < 5:
        return
    _put(screen, y, x, "+" + "-" * (width - 2) + "+")
    for row in range(1, height - 1):
        _put(screen, y + row, x, "|")
        _put(screen, y + row, x + width - 1, "|")
    _put(screen, y + height - 1, x, "+" + "-" * (width - 2) + "+")
    inner_width, inner_height = width - 2, height - 2
    markers = sorted(
        samples,
        key=lambda sample: (sample.slot_id == selected_slot, sample.team_id, sample.slot_id or ""),
    )
    for sample in markers:
        px = int(round(sample.position.x_m / Pitch().length_m * max(0, inner_width - 1)))
        py = int(round(sample.position.y_m / Pitch().width_m * max(0, inner_height - 1)))
        col, row = x + 1 + px, y + 1 + py
        marker = "@" if sample.team_id == "home" and sample.slot_id == selected_slot else (
            _SYMBOL_BY_SLOT.get(sample.slot_id or "", "?")
            if sample.team_id == "home" else _SYMBOL_BY_SLOT.get(sample.slot_id or "", "?").lower()
        )
        _put(screen, row, col, marker)


def _phase(plan: TacticalLabPlan) -> TacticalPhase:
    return _PHASE_BY_SCENARIO[plan.scenario_id]


def _instruction_action(plan: TacticalLabPlan, phase: TacticalPhase,
                        slot_id: str) -> TacticalAction:
    phase_plan = next((item for item in plan.tactic.phases if item.phase is phase), None)
    if phase_plan:
        instruction = next((item for item in phase_plan.instructions
                            if item.slot_id == slot_id), None)
        if instruction:
            return instruction.actions[0]
    return TacticalAction.MOVE_INSIDE


def _cycle_instruction(plan: TacticalLabPlan, slot_id: str) -> TacticalLabPlan:
    phase = _phase(plan)
    current = _instruction_action(plan, phase, slot_id)
    try:
        index = _ACTION_CYCLE.index(current)
    except ValueError:
        index = -1
    return set_instruction_action(plan, phase, slot_id, _ACTION_CYCLE[(index + 1) % len(_ACTION_CYCLE)])


def _placement(plan: TacticalLabPlan, slot_id: str) -> Position2D:
    return next(item.position for item in plan.placements if item.slot_id == slot_id)


def _draw_chooser(screen, selected: int) -> None:
    screen.erase()
    _put(screen, 0, 1, "EKSE SLAAN BALL  /  TACTICAL LAB")
    _put(screen, 2, 1, "Choose a spatial proof scenario")
    for index, scenario in enumerate(LAB_SCENARIOS):
        prefix = ">" if index == selected else " "
        _put(screen, 4 + index * 2, 2, f"{prefix} {scenario.name}")
        _put(screen, 5 + index * 2, 5, scenario.description)
    _put(screen, screen.getmaxyx()[0] - 3, 1, "↑/↓ or J/K choose   ENTER open   Q quit")
    _put(screen, screen.getmaxyx()[0] - 2, 1, "Synthetic proof teams · controlled open-play starts")
    screen.refresh()


def _draw_editor(screen, plan: TacticalLabPlan, selected_slot_index: int,
                 status: str) -> None:
    screen.erase()
    scenario = scenario_by_id(plan.scenario_id)
    slots = tuple(SLOT_INDEX)
    slot_id = slots[selected_slot_index]
    position = _placement(plan, slot_id)
    phase = _phase(plan)
    _put(screen, 0, 1, "TACTICAL LAB  /  FORMATION + INSTRUCTIONS")
    _put(screen, 1, 1, f"{scenario.name} · seed {plan.seed} · controlled spatial checkpoint")
    _put(screen, 2, 1, "Pitch coordinates are metres. Move any selected home role freely on the field.")
    _draw_pitch(
        screen, 4, 1, min(37, max(22, screen.getmaxyx()[1] // 2 - 2)), 9,
        [type("Marker", (), {"team_id": "home", "slot_id": item.slot_id,
                              "position": item.position}) for item in plan.placements],
        selected_slot=slot_id,
    )
    roster_x = min(40, screen.getmaxyx()[1] // 2 + 1)
    _put(screen, 4, roster_x, "HOME XI  ·  selected @")
    for index, item in enumerate(plan.placements):
        marker = ">" if index == selected_slot_index else " "
        _put(screen, 5 + index, roster_x,
             f"{marker}{item.slot_id:<3} {item.position.x_m:5.1f},{item.position.y_m:5.1f}")
    _put(screen, 16, 1, f"Selected {slot_id}  {position.x_m:.1f}m / {position.y_m:.1f}m")
    _put(screen, 17, 1, f"Instruction: {phase.value} / {slot_id} / {_instruction_action(plan, phase, slot_id).value}")
    _put(screen, 19, 1, "ARROWS/HJKL place · N/P select role · I action · S save · O load")
    _put(screen, 20, 1, "R run from checkpoint · Q scenarios · coordinates change actual P06 movement")
    _put(screen, 22, 1, status or "Save path: the lab data directory passed on the command line")
    _put(screen, 23, 1, "Rules preset: short P05 lab profile · campaign rules remain unchanged")
    screen.refresh()


def _snapshot_samples(snapshot: PositionSnapshot):
    return snapshot.positions


def _draw_replay(screen, run: TacticalLabRun, selected_index: int,
                 playing: bool, status: str) -> None:
    screen.erase()
    records = run.events
    if not records:
        selected_index = 0
    else:
        selected_index = min(len(records) - 1, max(0, selected_index))
    record = records[selected_index] if records else None
    snapshot = record.snapshot if record else run.checkpoint.snapshot
    event = record.event if record else None
    scenario = scenario_by_id(run.plan.scenario_id)
    mode = "RUNNING" if playing else "PAUSED"
    _put(screen, 0, 1, f"TACTICAL LAB  /  REPLAY  ·  {mode}")
    _put(screen, 1, 1, f"{scenario.name} · {run.match.period.value} · {run.match.phase.value} · tick {run.match.play.clock.tick}")
    _put(screen, 2, 1,
         f"Start: {run.checkpoint.label} · tick {run.checkpoint.snapshot.match_tick}")
    if event is not None:
        _put(screen, 3, 1,
             f"Event {selected_index + 1}/{len(records)} · {event.kind} · tick {event.match_tick} · seq {event.sequence}")
        _put(screen, 4, 1, f"{event.event_id} · recorded state tick {snapshot.match_tick}")
    else:
        _put(screen, 3, 1, run.checkpoint.label)
        _put(screen, 4, 1, "No match events recorded yet")
    carrier = str(snapshot.possession_player_id) if snapshot.possession_player_id else "none"
    _put(screen, 5, 1,
         f"Ball {snapshot.ball_position.x_m:.1f},{snapshot.ball_position.y_m:.1f}m · possession {snapshot.possession_team_id or 'none'} / {carrier}")
    _draw_pitch(screen, 7, 1, min(35, max(22, screen.getmaxyx()[1] // 2 - 3)), 9,
                _snapshot_samples(snapshot))
    left = sorted(
        (item for item in snapshot.positions if item.team_id == "home"),
        key=lambda item: SLOT_INDEX.get(item.slot_id or "", 99),
    )
    right = sorted(
        (item for item in snapshot.positions if item.team_id == "away"),
        key=lambda item: SLOT_INDEX.get(item.slot_id or "", 99),
    )
    left_x = min(37, screen.getmaxyx()[1] // 2 - 3)
    right_x = min(left_x + 20, screen.getmaxyx()[1] - 19)
    _put(screen, 7, left_x, "HOME POSITIONS")
    _put(screen, 7, right_x, "AWAY POSITIONS")
    for index in range(min(len(left), len(right), 11)):
        home, away = left[index], right[index]
        _put(screen, 8 + index, left_x,
             f"{home.slot_id or '--':<3} {home.position.x_m:5.1f},{home.position.y_m:4.1f}")
        _put(screen, 8 + index, right_x,
             f"{away.slot_id or '--':<3} {away.position.x_m:5.1f},{away.position.y_m:4.1f}")
    _put(screen, 19, 1, status or "Positions are captured at the end of each engine transition.")
    _put(screen, 21, 1, "SPACE run/pause · . step · F finish · [/] select event · E editor · Q quit")
    screen.refresh()


def _editor(stdscr, data_dir: Path, plan: TacticalLabPlan) -> tuple[str, TacticalLabPlan, TacticalLabRun | None]:
    import curses

    selected_slot_index = tuple(SLOT_INDEX).index("LB")
    status = ""
    slots = tuple(SLOT_INDEX)
    while True:
        _draw_editor(stdscr, plan, selected_slot_index, status)
        key = stdscr.getch()
        slot_id = slots[selected_slot_index]
        if key in (ord("q"), ord("Q")):
            return "chooser", plan, None
        if key in (
            curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_RIGHT,
            ord("h"), ord("j"), ord("k"), ord("l"),
        ):
            old = _placement(plan, slot_id)
            dx = -1.0 if key in (curses.KEY_LEFT, ord("h")) else (
                1.0 if key in (curses.KEY_RIGHT, ord("l")) else 0.0
            )
            dy = -1.0 if key in (curses.KEY_UP, ord("k")) else (
                1.0 if key in (curses.KEY_DOWN, ord("j")) else 0.0
            )
            new = Position2D(
                min(Pitch().length_m, max(0.0, old.x_m + dx)),
                min(Pitch().width_m, max(0.0, old.y_m + dy)),
            )
            plan = set_player_placement(plan, slot_id, new)
            status = f"{slot_id} placement set to {new.x_m:.1f},{new.y_m:.1f}m"
        elif key in (ord("n"), ord("N"), ord("p"), ord("P")):
            delta = 1 if key in (ord("n"), ord("N")) else -1
            selected_slot_index = (selected_slot_index + delta) % len(slots)
            status = ""
        elif key in (ord("i"), ord("I")):
            plan = _cycle_instruction(plan, slot_id)
            status = f"{slot_id} instruction changed to {_instruction_action(plan, _phase(plan), slot_id).value}"
        elif key in (ord("s"), ord("S")):
            try:
                path = save_plan(plan, data_dir)
                status = f"Plan saved · {path.name}"
            except (OSError, ValueError) as exc:
                status = f"Plan save failed · {exc}"
        elif key in (ord("o"), ord("O")):
            try:
                plan = load_plan(data_dir)
                selected_slot_index = min(selected_slot_index, len(plan.placements) - 1)
                status = "Plan loaded · current.json"
            except (OSError, ValueError) as exc:
                status = f"Plan load failed · {exc}"
        elif key in (ord("r"), ord("R"), 10, 13, curses.KEY_ENTER):
            return "replay", plan, create_run(plan)


def _replay(stdscr, run: TacticalLabRun) -> str:
    import curses

    selected_index = max(0, len(run.events) - 1)
    playing = False
    status = ""
    while True:
        stdscr.timeout(140 if playing else -1)
        _draw_replay(stdscr, run, selected_index, playing, status)
        key = stdscr.getch()
        if key == -1 and playing:
            run.step()
            if run.events:
                selected_index = len(run.events) - 1
            if run.finished:
                playing = False
                status = "Run reached its configured terminal state"
            continue
        if key in (ord("q"), ord("Q")):
            return "quit"
        if key in (ord("e"), ord("E")):
            return "editor"
        if key == ord(" "):
            playing = not playing and not run.finished
            status = "Playback running" if playing else "Playback paused"
        elif key in (ord("."),):
            playing = False
            run.step()
            selected_index = max(0, len(run.events) - 1)
            status = "Advanced one match transition"
        elif key in (ord("f"), ord("F")):
            playing = False
            run.run_to_completion()
            selected_index = max(0, len(run.events) - 1)
            status = "Quick run completed"
        elif key == ord("[") and run.events:
            selected_index = max(0, selected_index - 1)
            status = "Selected earlier recorded event"
        elif key == ord("]") and run.events:
            selected_index = min(len(run.events) - 1, selected_index + 1)
            status = "Selected later recorded event"


def _run(stdscr, data_dir: Path, seed: int) -> int:
    import curses

    stdscr.keypad(True)
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    selected_scenario = 0
    plan = default_plan(LAB_SCENARIOS[selected_scenario].scenario_id, seed=seed)
    page = "chooser"
    run: TacticalLabRun | None = None
    while True:
        if page == "chooser":
            _draw_chooser(stdscr, selected_scenario)
            key = stdscr.getch()
            if key in (ord("q"), ord("Q")):
                return 0
            if key in (curses.KEY_UP, curses.KEY_LEFT, ord("k"), ord("K")):
                selected_scenario = (selected_scenario - 1) % len(LAB_SCENARIOS)
            elif key in (curses.KEY_DOWN, curses.KEY_RIGHT, ord("j"), ord("J")):
                selected_scenario = (selected_scenario + 1) % len(LAB_SCENARIOS)
            elif key in (10, 13, curses.KEY_ENTER):
                plan = default_plan(LAB_SCENARIOS[selected_scenario].scenario_id, seed=seed)
                page = "editor"
        elif page == "editor":
            page, plan, run = _editor(stdscr, data_dir, plan)
        elif page == "replay":
            if run is None:
                page = "editor"
            else:
                result = _replay(stdscr, run)
                if result == "quit":
                    return 0
                if result == "editor":
                    page = "editor"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        / "ekse-slaan-ball" / "tactical-lab",
        help="directory for tactic plans (default: application data directory)",
    )
    parser.add_argument("--seed", type=int, default=8217, help="deterministic proof seed")
    args = parser.parse_args(argv)
    if args.seed < 0:
        parser.error("--seed must be non-negative")

    import curses

    try:
        return int(curses.wrapper(_run, args.data_dir, args.seed) or 0)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"tactical lab: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
