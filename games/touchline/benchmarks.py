"""Run a seeded, headless benchmark of the existing Touchline match engine.

Use ``python3 -m games.touchline.benchmarks --count 20 --seed 1`` from the
repository root. Add ``--workload season`` for complete seasons. Results go to
stdout unless an exclusive ``--output`` path is supplied. Career saves are
never written.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from games.touchline._baseline import (
    engine_metadata,
    environment_metadata,
    guard_sdk_effects,
    load_legacy_game,
    manifest_metadata,
)


def build_parser(club_ids: Sequence[str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", choices=("match", "season"), default="match",
                        help="benchmark individual matches or complete seasons")
    parser.add_argument("--seed", type=int, default=1,
                        help="starting simulation seed (default: 1)")
    parser.add_argument("--count", type=int,
                        help="number of matches/seasons (defaults to 20 matches or 1 season)")
    parser.add_argument("--club", choices=club_ids, default=club_ids[0],
                        help="managed club for a season workload")
    parser.add_argument("--home", choices=club_ids, default=club_ids[0],
                        help="home club (default: first authored club)")
    parser.add_argument("--away", choices=club_ids, default=club_ids[1],
                        help="away club (default: second authored club)")
    parser.add_argument("--output", type=Path,
                        help="optional new JSON output file; existing files are refused")
    return parser


def run_benchmark(args: argparse.Namespace, game: Any) -> dict[str, Any]:
    count = args.count if args.count is not None else (1 if args.workload == "season" else 20)
    if count < 1:
        raise ValueError("--count must be at least 1")
    if args.workload == "match" and args.home == args.away:
        raise ValueError("--home and --away must identify different clubs")

    setup_seconds = 0.0
    career = None
    if args.workload == "match":
        setup_start = time.perf_counter()
        career = game.new_career(args.home, seed=args.seed)
        setup_seconds = time.perf_counter() - setup_start

    totals = {
        "matches": 0,
        "seasons": 0,
        "periods": 0,
        "full_match_events": 0,
        "stored_season_highlights": 0,
        "goals": 0,
        "shots": 0,
        "shots_on_target": 0,
        "serialized_result_bytes": 0,
    }
    simulation_seconds = 0.0
    wall_start = time.perf_counter()
    discarded_awards: list[str] = []
    with guard_sdk_effects(game, discard_awards=args.workload == "season") as awards:
        if args.workload == "match":
            for index in range(count):
                match_start = time.perf_counter()
                match = game.simulate_match(
                    career,
                    args.home,
                    args.away,
                    match_seed=args.seed + index,
                    round_index=index,
                )
                simulation_seconds += time.perf_counter() - match_start

                totals["matches"] += 1
                totals["periods"] += int(match["period"])
                totals["full_match_events"] += len(match["events"])
                for club_id in (args.home, args.away):
                    stats = match["stats"][club_id]
                    totals["goals"] += int(stats["goals"])
                    totals["shots"] += int(stats["shots"])
                    totals["shots_on_target"] += int(stats["on_target"])
                result_view = match
                totals["serialized_result_bytes"] += len(json.dumps(
                    result_view, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                ).encode("utf-8"))
        else:
            for index in range(count):
                setup_start = time.perf_counter()
                career = game.new_career(args.club, seed=args.seed + index)
                setup_seconds += time.perf_counter() - setup_start
                season_start = time.perf_counter()
                game.simulate_full_season(career)
                simulation_seconds += time.perf_counter() - season_start
                season = int(career["season"])
                season_results = [result for result in career["results"]
                                  if int(result["season"]) == season]
                totals["seasons"] += 1
                totals["matches"] += len(season_results)
                totals["periods"] += len(season_results) * int(game.content.MATCH_PERIODS)
                totals["stored_season_highlights"] += sum(
                    len(result["events"]) for result in season_results)
                totals["goals"] += sum(int(result["home_goals"])
                                       + int(result["away_goals"])
                                       for result in season_results)
                for result in season_results:
                    for stats in result["stats"].values():
                        totals["shots"] += int(stats["shots"])
                        totals["shots_on_target"] += int(stats["on_target"])
                result_view = {
                    "season": season,
                    "results": season_results,
                    "season_history": career["season_history"][-1],
                }
                totals["serialized_result_bytes"] += len(json.dumps(
                    result_view, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                ).encode("utf-8"))
        discarded_awards.extend(awards)
    wall_seconds = time.perf_counter() - wall_start

    game_info = manifest_metadata()
    dataset = {
        "kind": "authored current career content",
        "clubs": len(game.content.CLUBS),
        "players": len(career["players"]),
    }
    if args.workload == "match":
        dataset.update({"home": args.home, "away": args.away})
    else:
        dataset["managed_club"] = args.club
    return {
        "format_version": 1,
        "game": {
            "name": game_info.get("name"),
            "slug": game_info.get("slug"),
            "manifest_version": game_info.get("version"),
        },
        "engine": engine_metadata(game),
        "dataset": dataset,
        "workload": {
            "kind": "unsettled full matches" if args.workload == "match"
                   else "completed career seasons",
            "result_record": "full match state" if args.workload == "match"
                            else "season result rows and summary (stored event highlights)",
            "seed": args.seed,
            "count": count,
            "seed_policy": "base seed plus workload index",
        },
        "environment": environment_metadata(),
        "timing_seconds": {
            "career_setup": round(setup_seconds, 6),
            "simulation_total": round(simulation_seconds, 6),
            "wall_total": round(wall_seconds, 6),
            "matches_per_simulation_second": round(
                totals["matches"] / simulation_seconds, 4) if simulation_seconds else None,
        },
        "counts": totals,
        "side_effects": {
            "career_save_writes": 0,
            "discarded_award_calls": discarded_awards,
        },
    }


def _write_result(path: Path, result: dict[str, Any]) -> None:
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(payload)


def main(argv: Sequence[str] | None = None) -> int:
    game = load_legacy_game()
    club_ids = [club["id"] for club in game.content.CLUBS]
    args = build_parser(club_ids).parse_args(argv)
    try:
        result = run_benchmark(args, game)
        if args.output is None:
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            _write_result(args.output, result)
            print(json.dumps({"output": str(args.output), "counts": result["counts"]},
                             ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"touchline benchmark: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
