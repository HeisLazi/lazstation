"""Generate isolated, synthetic save-v2 fixtures for the legacy Touchline game.

Run from the repository root with an explicit new destination, for example:
``python3 -m games.touchline.fixtures --output-dir /tmp/esb-fixtures-1``.
The parent directory must exist and the destination must not already exist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from games.touchline._baseline import (
    engine_metadata,
    guard_sdk_effects,
    load_legacy_game,
    manifest_metadata,
)


FIXTURE_KINDS = ("fresh", "live", "midseason", "finished")
GENERATOR_VERSION = 1


def _midseason_round(game: Any) -> int:
    return max(1, int(game.content.SEASON_ROUNDS) // 2)


def _career_for_kind(game: Any, kind: str, club_id: str, seed: int) -> dict[str, Any]:
    career = game.new_career(club_id, seed=seed)
    if kind == "fresh":
        return career

    if kind == "live":
        fixture = game.current_fixture(career)
        if fixture is None:
            raise RuntimeError("cannot create a live fixture from a completed season")
        home, away = fixture
        match = game.new_match(career, home, away, career["round"], seed + 50_000)
        game.simulate_period(career, match)
        career["live_match"] = match
        return career

    if kind == "midseason":
        target_round = _midseason_round(game)
        if target_round >= game.content.SEASON_ROUNDS:
            raise RuntimeError("the authored season is too short for a midseason fixture")
        while career["round"] < target_round:
            game.prepare_week(career)
            fixture = game.current_fixture(career)
            if fixture is None:
                raise RuntimeError("midseason fixture ended before its target round")
            home, away = fixture
            match = game.simulate_match(
                career, home, away,
                match_seed=game._match_seed(career, career["round"], home, away),
                round_index=career["round"],
            )
            game.complete_user_match(career, match)
        return career

    if kind == "finished":
        game.simulate_full_season(career)
        return career

    raise ValueError(f"unknown fixture kind: {kind}")


def _validate_lifecycle(game: Any, kind: str, save: dict[str, Any]) -> dict[str, Any]:
    if save.get("version") != int(game.SAVE_DEFAULTS["version"]):
        raise ValueError(f"{kind}: save wrapper does not use schema v2")
    career = save.get("career")
    if not isinstance(career, dict) or career.get("version") != 2:
        raise ValueError(f"{kind}: career does not use schema v2")

    round_index = int(career["round"])
    live_match = career.get("live_match")
    completed = bool(career.get("season_complete"))
    if kind == "fresh":
        valid = (round_index == 0 and not completed and live_match is None
                 and not career.get("results") and not career.get("season_history"))
    elif kind == "live":
        valid = (not completed and isinstance(live_match, dict)
                 and not live_match.get("finished")
                 and 0 < int(live_match.get("period", 0)) < game.content.MATCH_PERIODS
                 and int(live_match.get("round", -1)) == round_index)
    elif kind == "midseason":
        valid = (0 < round_index < game.content.SEASON_ROUNDS
                 and round_index == _midseason_round(game)
                 and not completed and live_match is None
                 and bool(career.get("results")))
    elif kind == "finished":
        valid = (round_index == game.content.SEASON_ROUNDS and completed
                 and live_match is None and bool(career.get("season_history"))
                 and career["season_history"][-1].get("season") == career.get("season"))
    else:
        raise ValueError(f"unknown fixture kind: {kind}")

    if not valid:
        raise ValueError(f"{kind}: generated career does not match its lifecycle label")
    return {
        "season": int(career["season"]),
        "round": round_index,
        "season_rounds": int(game.content.SEASON_ROUNDS),
        "season_complete": completed,
        "live_match": live_match is not None,
        "results": len(career.get("results", [])),
        "played_ids": len(career.get("played_ids", [])),
    }


def _json_save(game: Any, career: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    """Return the exact JSON representation the SDK would reload."""
    wrapper = {"version": int(game.SAVE_DEFAULTS["version"]), "career": career}
    first_payload = json.dumps(wrapper, ensure_ascii=False, sort_keys=True,
                               allow_nan=False).encode("utf-8")
    reloaded = json.loads(first_payload)
    # `content.DIVISION_FIXTURES` contains Python tuples; JSON reloads those as
    # arrays. The on-disk representation is canonical from this point onward.
    persisted_payload = json.dumps(reloaded, ensure_ascii=False, sort_keys=True,
                                   indent=2, allow_nan=False).encode("utf-8") + b"\n"
    checked = json.loads(persisted_payload)
    if checked != reloaded:
        raise ValueError("fixture save changed across JSON serialize/reload")
    return checked, persisted_payload


def generate_fixtures(game: Any, club_id: str, seed: int
                      ) -> tuple[dict[str, tuple[dict[str, Any], bytes, dict[str, Any]]], list[str]]:
    fixtures: dict[str, tuple[dict[str, Any], bytes, dict[str, Any]]] = {}
    with guard_sdk_effects(game, discard_awards=True) as discarded_awards:
        for kind in FIXTURE_KINDS:
            career = _career_for_kind(game, kind, club_id, seed)
            save, payload = _json_save(game, career)
            lifecycle = _validate_lifecycle(game, kind, save)
            fixtures[kind] = (save, payload, lifecycle)
    return fixtures, discarded_awards


def _manifest(game: Any, club_id: str, seed: int,
              fixtures: dict[str, tuple[dict[str, Any], bytes, dict[str, Any]]],
              discarded_awards: list[str]) -> dict[str, Any]:
    game_info = manifest_metadata()
    records = {}
    for kind, (_save, payload, lifecycle) in fixtures.items():
        records[kind] = {
            "file": f"{kind}.json",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "lifecycle": lifecycle,
        }
    return {
        "format_version": 1,
        "generator": "games.touchline.fixtures",
        "generator_version": GENERATOR_VERSION,
        "game": {
            "name": game_info.get("name"),
            "slug": game_info.get("slug"),
            "manifest_version": game_info.get("version"),
        },
        "engine": engine_metadata(game),
        "seed": seed,
        "club_id": club_id,
        "fixtures": records,
        "sdk_effects": {
            "career_save_writes": 0,
            "discarded_award_calls": discarded_awards,
        },
    }


def build_parser(club_ids: Sequence[str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="new directory for JSON saves and provenance manifest")
    parser.add_argument("--seed", type=int, default=1,
                        help="synthetic career seed (default: 1)")
    parser.add_argument("--club", choices=club_ids, default=club_ids[0],
                        help="club for the synthetic career (default: first authored club)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    game = load_legacy_game()
    club_ids = [club["id"] for club in game.content.CLUBS]
    args = build_parser(club_ids).parse_args(argv)
    try:
        fixtures, discarded_awards = generate_fixtures(game, args.club, args.seed)
        args.output_dir.mkdir(parents=False, exist_ok=False)
        for kind, (save, payload, _lifecycle) in fixtures.items():
            fixture_path = args.output_dir / f"{kind}.json"
            fixture_path.write_bytes(payload)
            reloaded = json.loads(fixture_path.read_bytes())
            if reloaded != save:
                raise ValueError(f"{kind}: written save changed after reload")
            _validate_lifecycle(game, kind, reloaded)
        manifest = _manifest(game, args.club, args.seed, fixtures, discarded_awards)
        manifest_payload = json.dumps(manifest, ensure_ascii=False, indent=2,
                                      sort_keys=True) + "\n"
        (args.output_dir / "manifest.json").write_text(manifest_payload, encoding="utf-8")
        print(json.dumps({"output_dir": str(args.output_dir),
                          "fixtures": len(fixtures),
                          "manifest": "manifest.json"}, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"touchline fixtures: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
