"""Play Touchline through its terminal controls and verify persisted outcomes.

Run from the repository root:

    PYTHONDONTWRITEBYTECODE=1 python3 -m games.touchline.checks.player_bot

The bot uses isolated saves and a PTY. It drives the same keyboard routes as a
player, captures named screens, resumes between matchdays, and checks the saved
career ledger. It never edits match state directly.
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
from games.touchline import content, main as game  # noqa: E402

# Curses enables xterm's application-cursor mode via keypad(True), so send the
# terminfo cursor sequences the game actually receives. The shared PTY helper's
# default normal-mode sequences are ignored by the active curses screen.
ptytest.KEY_BYTES.update({
    "UP": b"\x1bOA", "DOWN": b"\x1bOB",
    "RIGHT": b"\x1bOC", "LEFT": b"\x1bOD",
})


class PlayerBotFailure(RuntimeError):
    """The keyboard player found a broken screen, process or career invariant."""


def _key(name: str, wait: float = 0.035) -> dict[str, object]:
    # ncurses waits briefly after ESC to distinguish a lone escape from the
    # beginning of a cursor sequence. Let a bare Escape resolve on its own.
    delay = max(wait, 0.18) if name.upper() in ("ESC", "ESCAPE") else wait
    return {"type": "key", "key": name, "wait": delay}


def _snapshot(name: str) -> dict[str, object]:
    return {"type": "snapshot", "name": name}


def inspect_ui_frame(screen: str, text: str, *, terminal: str) -> list[dict[str, object]]:
    """Report suspicious orphan text that appears in an otherwise empty panel row.

    PTY screenshots are also saved verbatim for human review. This narrow
    heuristic calls out short alphabetic fragments near the right side of a
    bordered row; it does not fail a playthrough or claim every layout defect.
    """
    findings: list[dict[str, object]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not (line.startswith("║") and line.endswith("║")):
            continue
        interior = line[1:-1]
        fragment = interior.strip()
        if (re.fullmatch(r"[A-Za-z]{1,3}", fragment)
                and interior.find(fragment) >= len(interior) // 2):
            findings.append({
                "screen": screen,
                "terminal": terminal,
                "line": line_number,
                "kind": "orphan_short_text",
                "text": fragment,
                "message": "possible orphan or clipped text in an otherwise empty panel row",
            })
    return findings


class TouchlinePlayerBot:
    """A repeatable but varied manager policy which plays only via PTY keys."""

    def __init__(self, save_dir: Path, *, cols: int = 80, rows: int = 24,
                 seed: int = 9142, rounds: int = content.SEASON_ROUNDS,
                 settle: float = 0.035) -> None:
        if cols < 70 or rows < 18:
            raise ValueError("Touchline requires a terminal of at least 70x18")
        if type(rounds) is not int or not 1 <= rounds <= content.SEASON_ROUNDS:
            raise ValueError(f"rounds must be in 1..{content.SEASON_ROUNDS}")
        if type(seed) is not int:
            raise TypeError("bot seed must be an integer")
        self.save_dir = save_dir
        self.cols, self.rows = cols, rows
        self.seed, self.rounds, self.settle = seed, rounds, settle
        current_pythonpath = os.environ.get("PYTHONPATH", "")
        pythonpath = str(SDK_DIR)
        if current_pythonpath:
            pythonpath += os.pathsep + current_pythonpath
        self.env = {
            "TERMSTATION": "1",
            "TERMSTATION_NAME": "Touchline Player Bot",
            "TERMSTATION_SLUG": "touchline",
            "TERMSTATION_SAVE_DIR": str(save_dir),
            # This regression bot covers the explicitly retained legacy UI
            # path. P17 has a separate player bot for the spatial matchday.
            "TOUCHLINE_MATCH_ENGINE": "legacy",
            "PYTHONPATH": pythonpath,
            "PYTHONDONTWRITEBYTECODE": "1",
            "ESCDELAY": "25",
        }
        self.report: dict[str, Any] = {
            "terminal": f"{cols}x{rows}", "bot_seed": seed,
            "target_rounds": rounds, "scenarios": [],
            "managed_matches": 0, "quick_sim_rounds": 0,
            "quick_simulated_matches": 0,
            "checks": [], "ui_findings": [],
        }

    @property
    def save_path(self) -> Path:
        return self.save_dir / "save.json"

    def _run(self, label: str, events: list[dict[str, object]], *,
             frames: dict[str, dict[str, list[str]]] | None = None,
             cols: int | None = None, rows: int | None = None,
             timeout: float = 60.0) -> None:
        script = {"timeout": timeout, "expect_exit": True,
                  "assertions": {"exit_code": 0, "frames": frames or {}}}
        result = ptytest.run_scenario(
            [sys.executable, str(GAME_DIR / "main.py")],
            cols or self.cols, rows or self.rows, events,
            settle=self.settle, timeout=timeout, expect_exit=True,
            wait_before=0.85, env=self.env)
        failures = ptytest.check_assertions(script, result)
        details = {
            "name": label,
            "keys": [str(event["key"]) for event in events if event.get("type") == "key"],
            "snapshots": list(result.snapshots), "exit_code": result.exit_code,
            "timed_out": result.timed_out,
        }
        ui_findings = [finding
                       for name, snapshot in result.snapshots.items()
                       for finding in inspect_ui_frame(
                           name, snapshot.text,
                           terminal=f"{snapshot.cols}x{snapshot.rows}")]
        details["ui_findings"] = ui_findings
        self.report["ui_findings"].extend(
            {"scenario": label, **finding} for finding in ui_findings)
        frame_dir = self.save_dir / "frames" / re.sub(r"[^A-Za-z0-9_.-]+", "_", label)
        frame_dir.mkdir(parents=True, exist_ok=True)
        for frame_name, frame in result.snapshots.items():
            safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", frame_name)
            (frame_dir / f"{safe_name}.txt").write_text(frame.text + "\n", encoding="utf-8")
        details["frame_directory"] = str(frame_dir)
        self.report["scenarios"].append(details)
        if failures:
            failed_names = {failure.split("'", 2)[1]
                            for failure in failures if "snapshot '" in failure}
            frames_text = "\n\n".join(
                f"--- {name} ---\n{snapshot.text}"
                for name, snapshot in result.snapshots.items())
            if failed_names:
                frames_text = "\n\n".join(
                    f"--- {name} ---\n{result.snapshots[name].text}"
                    for name in sorted(failed_names) if name in result.snapshots)
            raise PlayerBotFailure(
                f"{label}: {', '.join(failures)}\n"
                f"PTY tail:\n{ptytest.plain_output(result.output)[-5000:]}\n"
                f"Captured screens:\n{frames_text[-12000:]}")
        self.report["checks"].append(f"{label}: PTY exited 0; {len(result.snapshots)} screens captured")

    def _read_career(self) -> dict[str, Any]:
        try:
            data = json.loads(self.save_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PlayerBotFailure(f"isolated save was not readable: {exc}") from exc
        career = data.get("career") if isinstance(data, dict) else None
        if not isinstance(career, dict):
            raise PlayerBotFailure("game did not persist a career record")
        return career

    def _verify_career(self, label: str, *, season: int, round_number: int,
                       season_complete: bool, result_count: int | None = None) -> dict[str, Any]:
        career = self._read_career()
        if career.get("version") != 2:
            raise PlayerBotFailure(f"{label}: unexpected career schema {career.get('version')!r}")
        actual = (career.get("season"), career.get("round"), career.get("season_complete"))
        expected = (season, round_number, season_complete)
        if actual != expected:
            raise PlayerBotFailure(f"{label}: expected season/round/completion {expected}, got {actual}")
        results = career.get("results", [])
        played_ids = career.get("played_ids", [])
        all_result_ids = [row.get("id") for row in results]
        season_results = [row for row in results if int(row.get("season", season)) == season]
        season_result_ids = [row["id"] for row in season_results]
        if len(all_result_ids) != len(set(all_result_ids)):
            raise PlayerBotFailure(f"{label}: archived result IDs are duplicated")
        if played_ids != season_result_ids:
            raise PlayerBotFailure(f"{label}: result IDs are missing or duplicated")
        table_matches = sum(int(row.get("played", 0)) for row in career["table"].values())
        if table_matches != 2 * len(season_results):
            raise PlayerBotFailure(
                f"{label}: current-season table played total {table_matches} does not reconcile "
                f"to {len(season_results)} results")
        if result_count is not None and len(results) != result_count:
            raise PlayerBotFailure(f"{label}: expected {result_count} settled fixtures, got {len(results)}")
        live_match = career.get("live_match")
        if live_match is not None:
            game.validate_match(live_match)
        self.report["checks"].append(
            f"{label}: save schema, season state, unique archived IDs and current-season table/result totals reconcile")
        return career

    def _new_career_and_managed_match(self) -> None:
        club_index = self.seed % len(content.CLUBS)
        other_cols, other_rows = ((110, 30) if self.cols < 88 else (80, 24))
        events: list[dict[str, object]] = []
        events.extend(_key("DOWN") for _ in range(club_index))
        events.extend((_snapshot("club-choice"), _key("ENTER"), _snapshot("home"),
                       _key("2"), _snapshot("squad"), _key("UP"), _key("x"),
                       _snapshot("squad-selection"), _key("1"), _key("3"),
                       _snapshot("plan"), _key("i"), _key("p"), _key("+"),
                       _key("4"), _snapshot("training"), _key("DOWN"), _key("ENTER"),
                       _key("i"), _key("5"), _snapshot("market"), _key("UP"),
                       _key("s"), _key("o"), _snapshot("offer"), _key("RIGHT"),
                       _key("UP"), _key("ESC"), _key("6"), _snapshot("table"),
                       _key("UP"), _key("DOWN"), _key("7"), _snapshot("history"),
                       _key("UP"), _key("DOWN"), _key("?"), _snapshot("help"),
                       _key("ESC"), _key("1"),
                       {"type": "resize", "cols": other_cols, "rows": other_rows},
                       _snapshot("resized-home"),
                       {"type": "resize", "cols": self.cols, "rows": self.rows},
                       _snapshot("home-restored"), _key("LEFT"), _key("ENTER"),
                       _snapshot("team-talk"), _key("ESC"), _snapshot("pre-kickoff-pause"),
                       _key("m"), _snapshot("team-talk-resumed"), _key("UP")))
        talk_index = (self.seed + 1) % len(content.TEAM_TALKS)
        events.extend(_key("DOWN") for _ in range(talk_index))
        events.extend((_key("ENTER"), _snapshot("match-live"), _key("TAB"),
                       _snapshot("match-events"), _key("UP"), _key("DOWN"),
                       _key("TAB"), _snapshot("match-stats"), _key("TAB"),
                       _key("1"), _key("2"), _key("3"), _key("ENTER"),
                       _snapshot("first-window"), _key("ESC"),
                       _snapshot("match-paused"), _key("M"), _snapshot("match-resumed"),
                       _key("4"), _snapshot("changes-cancel-test"), _key("ESC"),
                       _snapshot("match-after-cancel"), _key("4"), _snapshot("changes"),
                       _key("TAB"), _key("DOWN"),
                       _snapshot("change-pair"), _key("ENTER"),
                       _snapshot("substituted"), _key("TAB"), _snapshot("post-change-stats")))
        alternate = {"type": "resize", "cols": other_cols, "rows": other_rows}
        restore = {"type": "resize", "cols": self.cols, "rows": self.rows}
        events.extend((alternate, _snapshot("match-resized"), restore,
                       _snapshot("match-restored")))
        events.extend(_key("ENTER") for _ in range(5))
        events.extend((_snapshot("full-time"), _key("ENTER"),
                       _snapshot("round-settled"), _key("q")))
        frames = {
            "club-choice": {"contains": ["CHOOSE YOUR CLUB", "CLUB PROFILE"]},
            "home": {"contains": ["EKSE SLAAN BALL", "NEXT MATCH"]},
            "squad": {"contains": ["SQUAD"]},
            "plan": {"contains": ["MATCH PLAN"]},
            "training": {"contains": ["WEEKLY PLAN"]},
            "market": {"contains": ["SCOUTING DESK"]},
            "offer": {"contains": ["CONTRACT TABLE"]},
            "table": {"contains": ["FIXTURES"]},
            "history": {"contains": ["CAREER RESULTS", "WORLD NEWS"]},
            "help": {"contains": ["GAME CONTROLS"]},
            "team-talk": {"contains": ["BEFORE KICKOFF", "YOUR WORDS"]},
            "pre-kickoff-pause": {"contains": ["MATCH IN PROGRESS"]},
            "match-live": {"contains": ["LATEST MOMENT"]},
            "match-events": {"contains": ["EVENTS"]},
            "match-stats": {"contains": ["MATCH DATA"]},
            "changes-cancel-test": {"contains": ["MATCH CHANGES", "0/5 used"]},
            "match-after-cancel": {"contains": ["MATCHDAY /"],
                                   "not_contains": ["replaces"]},
            "changes": {"contains": ["ON PITCH", "AVAILABLE", "0/5 used"]},
            "change-pair": {"contains": ["PAIR"]},
            "substituted": {"contains": ["replaces"]},
            "full-time": {"contains": ["FULL TIME"]},
            "round-settled": {"contains": ["NEXT MATCH"]},
        }
        self._run("new career, desk tour, managed match and save", events, frames=frames)
        career = self._verify_career("first managed round", season=1, round_number=1,
                                     season_complete=False, result_count=6)
        result = career["results"][-6]
        if result["home_goals"] < 0 or result["away_goals"] < 0:
            raise PlayerBotFailure("first managed match stored a negative score")
        self.report["managed_matches"] += 1
        # The other fixtures in the opening round are settled by the normal
        # round runner while the bot manages its selected fixture live.
        self.report["quick_simulated_matches"] += max(0, len(content.CLUBS) // 2 - 1)
        self.report["bot_club"] = career["club_id"]
        self.report["checks"].append("first match finished through six live windows and one selected substitution")

    def _quick_sim_round(self, round_number: int) -> None:
        resumed_frame = "resumed-home"
        events = [_snapshot(resumed_frame), _key("m"), _snapshot("team-talk")]
        talk_index = (round_number + self.seed) % len(content.TEAM_TALKS)
        events.extend(_key("DOWN") for _ in range(talk_index))
        # Vary the manager's instructions across the season, then use the
        # game's normal quick-sim command for the remaining match windows.
        events.extend((_key("ENTER"), _key(str(1 + round_number % 3)), _key("q"),
                       _snapshot("quick-full-time"), _key("ENTER"),
                       _snapshot("round-settled"), _key("Q")))
        frames = {
            "resumed-home": {"contains": ["NEXT MATCH"]},
            "team-talk": {"contains": ["BEFORE KICKOFF", "YOUR WORDS"]},
            "quick-full-time": {"contains": ["FULL TIME"]},
            "round-settled": {"contains": [
                "SEASON 1 REVIEW" if round_number + 1 == content.SEASON_ROUNDS
                else "NEXT MATCH"]},
        }
        self._run(f"resume and quick-sim round {round_number + 1}", events, frames=frames)
        self._verify_career(f"round {round_number + 1}", season=1,
                            round_number=round_number + 1,
                            season_complete=round_number + 1 == content.SEASON_ROUNDS,
                            result_count=(round_number + 1) * 6)
        self.report["quick_sim_rounds"] += 1
        self.report["quick_simulated_matches"] += len(content.CLUBS) // 2

    def _advance_season_and_resume(self) -> None:
        events = [_snapshot("season-review"), _key("ENTER"),
                  _snapshot("season-two-home"), _key("Q")]
        self._run("season completion and save resume", events, frames={
            "season-review": {"contains": ["SEASON 1 REVIEW"]},
            "season-two-home": {"contains": ["S2 · W01/10", "NEXT MATCH"]},
        })
        self._verify_career("season transition", season=2, round_number=0,
                            season_complete=False, result_count=60)
        events = [_snapshot("season-two-resume"), _key("M"), _snapshot("season-two-talk"),
                  _key("ENTER"), _key("Q"), _snapshot("season-two-full-time"),
                  _key("ENTER"), _snapshot("season-two-round-settled"), _key("Q")]
        self._run("season two opening match", events, frames={
            "season-two-resume": {"contains": ["NEXT MATCH"]},
            "season-two-talk": {"contains": ["BEFORE KICKOFF"]},
            "season-two-full-time": {"contains": ["FULL TIME"]},
            "season-two-round-settled": {"contains": ["NEXT MATCH"]},
        })
        self._verify_career("season two first round", season=2, round_number=1,
                            season_complete=False, result_count=66)
        self.report["quick_sim_rounds"] += 1
        self.report["quick_simulated_matches"] += len(content.CLUBS) // 2

    def play(self) -> dict[str, Any]:
        if self.save_path.exists():
            raise ValueError(f"refusing to overwrite existing save: {self.save_path}")
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self._new_career_and_managed_match()
        for round_number in range(1, self.rounds):
            self._quick_sim_round(round_number)
        if self.rounds == content.SEASON_ROUNDS:
            self._advance_season_and_resume()
        else:
            self._run("save-and-reopen home", [_snapshot("resumed-home"), _key("Q")], frames={
                "resumed-home": {"contains": ["NEXT MATCH"]},
            })
            self._verify_career("save resume", season=1, round_number=self.rounds,
                                season_complete=False, result_count=self.rounds * 6)
        self.report["save_file"] = str(self.save_path)
        return self.report


def parse_size(value: str) -> tuple[int, int]:
    try:
        cols_text, rows_text = value.lower().split("x", 1)
        cols, rows = int(cols_text), int(rows_text)
    except (ValueError, AttributeError) as exc:
        raise argparse.ArgumentTypeError("terminal size must look like 80x24") from exc
    if cols < 70 or rows < 18:
        raise argparse.ArgumentTypeError("terminal size must be at least 70x18")
    return cols, rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=parse_size, nargs="+", default=[(80, 24), (110, 30)])
    parser.add_argument("--rounds", type=int, default=content.SEASON_ROUNDS,
                        help=f"managed rounds to play (default: {content.SEASON_ROUNDS})")
    parser.add_argument("--seed", type=int, default=9142,
                        help="controls bot choices and selected starting club")
    parser.add_argument("--save-root", type=Path,
                        help="empty isolated directory for retained saves/reports")
    args = parser.parse_args(argv)
    if not 1 <= args.rounds <= content.SEASON_ROUNDS:
        parser.error(f"--rounds must be in 1..{content.SEASON_ROUNDS}")
    if args.save_root:
        save_root = args.save_root.expanduser().resolve()
        if save_root.exists() and any(save_root.iterdir()):
            parser.error(f"--save-root must be empty: {save_root}")
        save_root.mkdir(parents=True, exist_ok=True)
    else:
        save_root = Path(tempfile.mkdtemp(prefix="touchline-player-bot-"))
    reports = []
    try:
        for cols, rows in args.sizes:
            label = f"{cols}x{rows}"
            runner = TouchlinePlayerBot(save_root / label, cols=cols, rows=rows,
                                        seed=args.seed, rounds=args.rounds)
            reports.append(runner.play())
        combined = {"save_root": str(save_root), "runs": reports}
        report_path = save_root / "report.json"
        report_path.write_text(json.dumps(combined, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
        print(json.dumps(combined, indent=2, sort_keys=True))
        return 0
    except (PlayerBotFailure, OSError, ValueError) as exc:
        print(f"player_bot: FAIL: {exc}", file=sys.stderr)
        print(f"player_bot: save root retained at {save_root}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
