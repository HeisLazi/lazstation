"""Drive the P17 spatial career matchday through real terminal input.

Run from the repository root:

    PYTHONDONTWRITEBYTECODE=1 python3 -m games.touchline.checks.matchday_bot

Each run uses an isolated save, creates and edits a formation, starts a spatial
career checkpoint, exits and resumes the process, queues a substitution in
play, quick-simulates the same match, settles the round, and captures the map,
event feed and reports at both target terminal sizes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
GAME_DIR = ROOT / "games" / "touchline"
SDK_DIR = ROOT / "sdk"
TOOLS_DIR = ROOT / "tools"
for import_path in (str(ROOT), str(SDK_DIR), str(TOOLS_DIR)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

import ptytest  # noqa: E402
from games.touchline import main as game  # noqa: E402
from games.touchline.esb.career_adapter import (  # noqa: E402
    SPATIAL_ENGINE_ID,
    VersionedCareerSave,
    resume_spatial_career_match,
)

ptytest.KEY_BYTES.update({
    "UP": b"\x1bOA", "DOWN": b"\x1bOB",
    "RIGHT": b"\x1bOC", "LEFT": b"\x1bOD",
})


def _key(value: str, wait: float = 1.3) -> dict[str, object]:
    return {"type": "key", "key": value, "wait": wait}


def _snapshot(value: str, wait: float | None = None) -> dict[str, object]:
    event: dict[str, object] = {"type": "snapshot", "name": value}
    if wait is not None:
        event["wait"] = wait
    return event


def _pitch_map_rows(screen: str) -> list[str]:
    lines = screen.splitlines()
    top = next((index for index, line in enumerate(lines)
                if "┌" in line and "┐" in line), None)
    if top is None:
        return []
    left = lines[top].index("┌")
    right = lines[top].index("┐", left)
    bottom = next((index for index in range(top + 1, len(lines))
                   if "└" in lines[index][left:right + 1]), None)
    if bottom is None:
        return []
    return [line[left:right + 1] for line in lines[top:bottom + 1]]


def _moved_player_markers(before: str, after: str) -> list[str]:
    """Return stable player symbols whose map cells changed, excluding the ball."""
    player_symbols = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz") - {"o"}

    def positions(screen: str) -> dict[str, tuple[tuple[int, int], ...]]:
        found: dict[str, list[tuple[int, int]]] = {}
        for row, line in enumerate(_pitch_map_rows(screen)):
            for col, char in enumerate(line):
                if char in player_symbols:
                    found.setdefault(char, []).append((row, col))
        return {char: tuple(cells) for char, cells in found.items()}

    earlier, later = positions(before), positions(after)
    return sorted(char for char in earlier.keys() & later.keys()
                  if earlier[char] != later[char])


class MatchdayBotError(RuntimeError):
    pass


class SpatialMatchdayBot:
    def __init__(self, *, cols: int, rows: int, output: Path,
                 settle: float = 1.3) -> None:
        self.cols, self.rows, self.output = cols, rows, output
        self.save_dir = output / f"{cols}x{rows}" / "save"
        self.save_dir.mkdir(parents=True, exist_ok=True)
        pythonpath = os.pathsep.join((str(SDK_DIR), str(TOOLS_DIR), str(ROOT)))
        self.env = {
            "TERMSTATION": "1",
            "TERMSTATION_NAME": "Touchline Spatial Matchday Bot",
            "TERMSTATION_SLUG": "touchline",
            "TERMSTATION_SAVE_DIR": str(self.save_dir),
            "PYTHONPATH": pythonpath,
            "PYTHONDONTWRITEBYTECODE": "1",
            "ESCDELAY": "25",
        }
        self.settle = settle
        self.report: dict[str, Any] = {
            "terminal": f"{cols}x{rows}",
            "scenarios": [],
            "checks": [],
            "ui_findings": [],
        }

    @property
    def save_path(self) -> Path:
        return self.save_dir / "save.json"

    def _capture(self, label: str, events: list[dict[str, object]], *,
                 assertions: dict[str, dict[str, list[str]]] | None = None,
                 output_contains: list[str] | None = None,
                 timeout: float = 300.0) -> None:
        # The live match draws only between fixed simulation chunks. Wait for
        # the frame after each input before capturing it, so a slow chunk does
        # not make the screenshot represent the screen from before that input.
        capture_events: list[dict[str, object]] = []
        for event in events:
            if event.get("type") == "snapshot":
                capture_events.append({
                    "type": "wait", "seconds": event.get("wait", self.settle)})
            capture_events.append(event)
        inherited_engine = os.environ.pop("TOUCHLINE_MATCH_ENGINE", None)
        try:
            result = ptytest.run_scenario(
                [sys.executable, str(GAME_DIR / "main.py")],
                self.cols, self.rows, capture_events,
                settle=self.settle,
                timeout=timeout,
                expect_exit=True,
                wait_before=0.8,
                env=self.env,
            )
        finally:
            if inherited_engine is not None:
                os.environ["TOUCHLINE_MATCH_ENGINE"] = inherited_engine
        script = {"assertions": {"exit_code": 0, "frames": assertions or {}}}
        failures = ptytest.check_assertions(script, result)
        plain_output = ptytest.plain_output(result.output)
        failures.extend(
            f"terminal output is missing {needle!r}"
            for needle in (output_contains or []) if needle not in plain_output
        )
        frame_dir = self.output / f"{self.cols}x{self.rows}" / re.sub(
            r"[^A-Za-z0-9_.-]+", "_", label)
        frame_dir.mkdir(parents=True, exist_ok=True)
        findings: list[dict[str, object]] = []
        for name, snapshot in result.snapshots.items():
            (frame_dir / f"{name}.txt").write_text(snapshot.text + "\n", encoding="utf-8")
            for line_no, line in enumerate(snapshot.text.splitlines(), start=1):
                left, right = line.find("╚"), line.rfind("╝")
                if left >= 0 and right > left and any(
                        char != "═" for char in line[left + 1:right]):
                    findings.append({"screen": name, "line": line_no,
                                     "kind": "bottom_bezel_overwritten",
                                     "text": line[left:right + 1]})
                if (line.startswith("║") and line.endswith("║")
                        and re.fullmatch(r"\s*[A-Za-z]{1,3}\s*", line[1:-1])):
                    findings.append({"screen": name, "line": line_no,
                                     "kind": "orphan_short_text", "text": line[1:-1].strip()})
        self.report["ui_findings"].extend(
            {"scenario": label, **finding} for finding in findings)
        scenario = {
            "name": label,
            "keys": [event.get("key") for event in events if event.get("type") == "key"],
            "snapshots": list(result.snapshots),
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "frame_directory": str(frame_dir),
            "ui_findings": findings,
        }
        self.report["scenarios"].append(scenario)
        if failures:
            text = "\n\n".join(f"--- {name} ---\n{item.text}"
                                 for name, item in result.snapshots.items())
            raise MatchdayBotError(
                f"{label}: {'; '.join(failures)}\n"
                f"PTY output tail:\n{ptytest.plain_output(result.output)[-5000:]}\n"
                f"Screens:\n{text[-15000:]}"
            )
        self.report["checks"].append(
            f"{label}: exited 0; captured {len(result.snapshots)} terminal screens")

    def _read_spatial_save(self) -> tuple[dict[str, Any], VersionedCareerSave]:
        try:
            raw = json.loads(self.save_path.read_text(encoding="utf-8"))
            runtime = game.migrate_save(raw)
        except (OSError, ValueError, TypeError) as exc:
            raise MatchdayBotError(f"could not reload isolated matchday save: {exc}") from exc
        adapter = runtime.get("_career_adapter_state")
        career = runtime.get("career")
        if not isinstance(career, dict) or not isinstance(adapter, VersionedCareerSave):
            raise MatchdayBotError("save did not resume through the versioned career adapter")
        if adapter.spatial_match_json is None:
            raise MatchdayBotError("exit/restart did not preserve the active spatial match")
        return career, adapter

    def _substitution_indices(self) -> tuple[int, int, str, str]:
        career, adapter = self._read_spatial_save()
        session = resume_spatial_career_match(adapter)
        team_id = game._spatial_user_team(session, career)
        roster = session.match.teams[team_id]
        active_ids = [player_id for player_id in roster.starting_ids
                      if player_id in session.match.play.players]
        active_ids.extend(sorted((player_id for player_id, state in session.match.play.players.items()
                                  if state.team_id == team_id and player_id not in active_ids),
                                 key=str))
        outgoing_index = next((index for index, player_id in enumerate(active_ids)
                               if session.match.play.players[player_id].profile.primary_role.value != "goalkeeper"
                               and session.match.play.possession_id != player_id), None)
        bench = list(roster.eligible_bench())
        incoming_index = next((index for index, profile in enumerate(bench)
                               if profile.primary_role.value != "goalkeeper"), None)
        if outgoing_index is None or incoming_index is None:
            raise MatchdayBotError("fixture has no legal outfield substitution pair")
        return outgoing_index, incoming_index, str(active_ids[outgoing_index]), str(bench[incoming_index].player_id)

    def play(self) -> dict[str, Any]:
        first = [
            _snapshot("club-choice"), _key("ENTER"), _snapshot("career-home"),
            _key("m"), _snapshot("formation-setup"),
            _key("f"), _snapshot("formation-changed"),
            _key("t"), _snapshot("plan-changed"),
            _key("A"), _snapshot("marker-selected"),
            _key("d"), _snapshot("formation-placed"),
            _key("ENTER", wait=2.0), _snapshot("kickoff-pitch"), _key("."),
            _snapshot("one-second-step"), _key(" ", wait=4.0),
            _snapshot("watched-pitch"), _key(" ", wait=3.0),
            _snapshot("paused-pitch"), _key("z", wait=2.0),
            _snapshot("close-pitch-shortcut"), _key("z", wait=2.0),
            _snapshot("full-pitch-map"), _key("1"), _snapshot("selected-player"),
            _key("z"), _snapshot("selected-close-pitch"),
            _key("B"), _snapshot("ball-focus"),
            _key("B"), _snapshot("player-focus"),
            _key("]"), _snapshot("close-pitch-cycle"), _key("z"),
            _snapshot("selected-full-pitch"), _key("TAB"), _snapshot("event-chronology"),
            _key("TAB"), _snapshot("player-stats"),
            _key("TAB"), _snapshot("lineup-keys"),
            _key("TAB"), _snapshot("live-pitch-again"), _key("ESC"),
            _snapshot("paused-home"), _key("q"),
        ]
        self._capture("create-shape-and-first-step", first, assertions={
            "club-choice": {"contains": ["CHOOSE YOUR CLUB"]},
            "formation-setup": {"contains": ["MATCHDAY", "SHAPE", "PLAN", "SLOT",
                                               "local x/y", "w Y-2m", "s Y+2m",
                                               "a X-2m", "d X+2m", "wasd place",
                                               "1–9,0,A select"]},
            "formation-changed": {"contains": ["SHAPE · YOU 3-5-2", "local x/y"]},
            "plan-changed": {"contains": ["Man-oriented press"]},
            "marker-selected": {"contains": ["SELECTED @11/11", "local x/y"]},
            "formation-placed": {"contains": ["SELECTED @11/11", "local x/y"]},
            "kickoff-pitch": {"contains": ["MATCHDAY", "1H", "LIVE BALL"]},
            "one-second-step": {"contains": ["LIVE BALL", "events"]},
            "watched-pitch": {"contains": ["WATCH", "ticks/update", "Carrier",
                                             "Tab views", "Z pitch", "Esc"]},
            "close-pitch-shortcut": {"contains": ["[PITCH]", "FOCUS", "Z full"]},
            "full-pitch-map": {"contains": ["[PITCH]", "HOME", "AWAY", "Z zoom",
                                              "Keys 1–9,0,A,C–Z / a–k select"]},
            "selected-player": {"contains": ["FULL PITCH", "SEL", "LAST"]},
            "selected-close-pitch": {"contains": ["FOCUS", "X≈", "Y≈", "SEL", "LAST",
                                                      "B ball/player · Z full/zoom",
                                                      "LATEST EVENTS"]},
            "ball-focus": {"contains": ["PITCH · CLOSE · BALL", "LATEST EVENTS"]},
            "player-focus": {"contains": ["PITCH · CLOSE · PLAYER", "B ball/player"]},
            "close-pitch-cycle": {"contains": ["FOCUS", "X≈", "Y≈", "SEL", "LAST"]},
            "selected-full-pitch": {"contains": ["FULL PITCH", "SEL", "LAST"]},
            "event-chronology": {"contains": ["CHRONOLOGY", "KEY", "M all"],
                                 "not_contains": [" MOVE · "]},
            "player-stats": {"contains": ["G goals", "A assists", "S shots", "PA/PC pass attempts/completed"]},
            "paused-home": {"contains": ["Live match paused"],
                            "not_contains": ["Pre-kickoff"]},
            "lineup-keys": {"contains": ["HOME", "AWAY", "BENCH"]},
        })
        formation_screen = (self.output / f"{self.cols}x{self.rows}"
                            / "create-shape-and-first-step"
                            / "formation-changed.txt").read_text(encoding="utf-8")
        formation_map = _pitch_map_rows(formation_screen)
        if sum(line.count("2") for line in formation_map) != 1:
            raise MatchdayBotError(
                "the 3-5-2 formation preview does not render home player 2 exactly once")
        if len(formation_map) < 3:
            raise MatchdayBotError("formation preview did not render the pitch map")
        pitch_ratio = ((len(formation_map[0]) - 2) / (len(formation_map) - 2))
        if not 2.8 <= pitch_ratio <= 3.2:
            raise MatchdayBotError(
                f"formation preview is distorted for terminal cells ({pitch_ratio:.2f}:1)")
        selected_setup = (self.output / f"{self.cols}x{self.rows}"
                          / "create-shape-and-first-step" / "marker-selected.txt").read_text(
                              encoding="utf-8")
        placed_setup = (self.output / f"{self.cols}x{self.rows}"
                        / "create-shape-and-first-step" / "formation-placed.txt").read_text(
                            encoding="utf-8")
        position_pattern = re.compile(r"local x/y ([0-9.]+)/([0-9.]+)m")
        selected_position = position_pattern.search(selected_setup)
        placed_position = position_pattern.search(placed_setup)
        if not selected_position or not placed_position:
            raise MatchdayBotError("formation preview did not show selected player coordinates")
        x_before, y_before = map(float, selected_position.groups())
        x_after, y_after = map(float, placed_position.groups())
        if abs(x_after - x_before - 2.0) > 0.11 or y_after != y_before:
            raise MatchdayBotError(
                f"D placement did not move the selected player +2m on X: "
                f"({x_before}, {y_before}) → ({x_after}, {y_after})")
        career, adapter = self._read_spatial_save()
        first_id = str(adapter.current_match_id)
        if not first_id or adapter.current_match_engine_id != SPATIAL_ENGINE_ID:
            raise MatchdayBotError("career did not save the P08 spatial engine identity")
        self.report["checks"].append(
            "default launch with TOUCHLINE_MATCH_ENGINE absent starts spatial matchday")
        session = resume_spatial_career_match(adapter)
        if session.match.play.clock.tick < 2:
            raise MatchdayBotError("watch mode did not advance the live match clock")
        first_screen = (self.output / f"{self.cols}x{self.rows}"
                        / "create-shape-and-first-step" / "kickoff-pitch.txt").read_text(
                            encoding="utf-8")
        watched_screen = (self.output / f"{self.cols}x{self.rows}"
                          / "create-shape-and-first-step" / "watched-pitch.txt").read_text(
                              encoding="utf-8")
        moved_players = _moved_player_markers(first_screen, watched_screen)
        if not moved_players:
            raise MatchdayBotError("watched play did not visibly move any player markers")
        self.report["checks"].append("career setup saved a resumable spatial checkpoint and formation")
        self.report["checks"].append(
            f"watch mode advanced the clock and visibly moved player markers {moved_players}")

        outgoing_index, incoming_index, outgoing_id, incoming_id = self._substitution_indices()
        career, adapter = self._read_spatial_save()
        session = resume_spatial_career_match(adapter)
        team_id = game._spatial_user_team(session, career)
        roster = session.match.teams[team_id]
        visible_outgoing_names = [
            game._player_name(career, player_id) for player_id in roster.starting_ids
            if player_id in session.match.play.players
        ]
        second: list[dict[str, object]] = [
            _snapshot("resumed-live-pitch", wait=4.0), _key("."), _key("s"),
        ]
        second.extend(_key("DOWN") for _ in range(outgoing_index))
        second.append(_key("TAB"))
        second.extend(_key("DOWN") for _ in range(incoming_index))
        second.extend((_snapshot("substitution-pair"), _key("ENTER"),
                       _snapshot("substitution-queued"), _key("q", wait=0.1),
                       _key("ENTER", wait=0.1), _snapshot("settled-home"),
                       _key("r", wait=0.3), _snapshot("last-match-report"),
                       _key("ESC"), _snapshot("final"), _key("q", wait=0.1)))
        self._capture("resume-substitute-quick-sim-and-settle", second, assertions={
            "resumed-live-pitch": {"contains": ["1H", "ball", "events"]},
            "substitution-pair": {"contains": ["CHANGES", "ON PITCH", "BENCH"]},
            "substitution-queued": {"contains": ["CHANGE QUEUED", "next stoppage"]},
            "settled-home": {"contains": ["Last:", "R match report"]},
            "last-match-report": {"contains": ["MATCH REPORT", "GOAL CHRONOLOGY",
                                                  "PLAYING TIME"]},
            "final": {"contains": ["NEXT MATCH", "Round 2"]},
        }, output_contains=["FULL TIME", "MATCH FINISHED", "Quick-sim reached full time"],
           timeout=1200)
        substitution_screen = (self.output / f"{self.cols}x{self.rows}"
                               / "resume-substitute-quick-sim-and-settle"
                               / "substitution-pair.txt").read_text(encoding="utf-8")
        missing_names = [name for name in visible_outgoing_names
                         if name not in substitution_screen]
        if missing_names:
            raise MatchdayBotError(
                "substitution list hid eligible players: " + ", ".join(missing_names))
        if "central_midfielder" in substitution_screen:
            raise MatchdayBotError("substitution list shows an unformatted internal role id")
        queued_screen = (self.output / f"{self.cols}x{self.rows}"
                         / "resume-substitute-quick-sim-and-settle"
                         / "substitution-queued.txt").read_text(encoding="utf-8")
        incoming_name = game._player_name(career, incoming_id)
        outgoing_name = game._player_name(career, outgoing_id)
        for name in (incoming_name, outgoing_name):
            if name not in queued_screen:
                raise MatchdayBotError(
                    f"persistent queued-change indicator hid player name {name!r}")
        del outgoing_index, incoming_index

        # The game has closed the P08 checkpoint and resolved other scheduled
        # fixtures. Inspect the durable data, including playing time for the
        # substitute, without changing it.
        raw = json.loads(self.save_path.read_text(encoding="utf-8"))
        runtime = game.migrate_save(raw)
        saved_career = runtime["career"]
        result = next((item for item in reversed(saved_career["results"])
                       if item.get("id") == first_id), None)
        if not isinstance(result, dict) or result.get("engine_id") != SPATIAL_ENGINE_ID:
            raise MatchdayBotError("settled career history lost the spatial engine result")
        report_screen = (self.output / f"{self.cols}x{self.rows}"
                         / "resume-substitute-quick-sim-and-settle"
                         / "last-match-report.txt").read_text(encoding="utf-8")
        expected_score = (
            f"{game.club_by_id(result['home'])['name']}  "
            f"{result['home_goals']}–{result['away_goals']}  "
            f"{game.club_by_id(result['away'])['name']}"
        )
        if expected_score not in report_screen:
            raise MatchdayBotError(
                f"saved match report hid the settled score {expected_score!r}")
        minutes = result.get("stats", {}).get("minutes", {})
        if float(minutes.get(incoming_id, 0.0)) <= 0:
            raise MatchdayBotError("queued substitution did not give the incoming player match time")
        if saved_career.get("round") != 1 or runtime["_career_adapter_state"].spatial_match_json is not None:
            raise MatchdayBotError("spatial match settlement did not close its checkpoint and round")
        result_ids = [item.get("id") for item in saved_career.get("results", [])]
        if len(result_ids) != len(set(result_ids)):
            raise MatchdayBotError("round closure produced duplicate career result IDs")
        self.report["checks"].extend((
            "queued substitute appears in the settled playing-time projection",
            "spatial result is archived once; round advances and the checkpoint clears",
        ))
        return self.report


def _parse_size(raw: str) -> tuple[int, int]:
    cols, separator, rows = raw.lower().partition("x")
    if not separator:
        raise argparse.ArgumentTypeError("terminal size must be COLSxROWS")
    return int(cols), int(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=_parse_size,
                        default=[(80, 24), (110, 30)])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or Path(tempfile.mkdtemp(prefix="touchline-matchday-bot-"))
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    for cols, rows in args.sizes:
        bot = SpatialMatchdayBot(cols=cols, rows=rows, output=output)
        reports.append(bot.play())
        (output / f"{cols}x{rows}" / "report.json").write_text(
            json.dumps(bot.report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
    combined = {"output": str(output), "terminals": reports}
    (output / "report.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps(combined, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
