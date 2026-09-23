"""Headless rule and season checks for Ekse Slaan Ball.

Run from the repository root with ``python3 -m unittest games.touchline.test_game``.
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sdk"))

from games.touchline import content, main as game  # noqa: E402


class AlwaysInjuredRoll:
    def random(self):
        return 0.0

    def choice(self, options):
        return options[0]

    def randint(self, low, high):
        return low


class FixtureRules(unittest.TestCase):
    def test_round_robin_is_complete_and_balanced(self):
        club_ids = {club["id"] for club in content.CLUBS}
        seen = []
        for round_fixtures in content.FIXTURES:
            self.assertEqual(len(round_fixtures), len(club_ids) // 2)
            participants = [club for fixture in round_fixtures for club in fixture]
            self.assertEqual(set(participants), club_ids)
            self.assertEqual(len(participants), len(set(participants)))
            seen.extend(round_fixtures)

        self.assertEqual(len(content.FIXTURES), 10)
        self.assertEqual(len(seen), 30)
        for first, second in __import__("itertools").combinations(sorted(club_ids), 2):
            meetings = [fixture for fixture in seen if set(fixture) == {first, second}]
            self.assertEqual(sorted(meetings), [(first, second), (second, first)])


class MatchRules(unittest.TestCase):
    def test_shot_quality_and_conversion_are_separate(self):
        clear = game.expected_goals(4, "center", pressure=0)
        crowded = game.expected_goals(4, "center", pressure=3)
        self.assertGreater(clear, crowded)
        self.assertGreater(game.expected_goals(4, "center", 0, "cutback"), clear)
        self.assertGreater(game.conversion_probability(clear, 85, 55),
                           game.conversion_probability(clear, 55, 55))
        self.assertGreater(game.conversion_probability(clear, 70, 45),
                           game.conversion_probability(clear, 70, 85))

    def test_current_readiness_changes_execution_without_changing_xg(self):
        career = game.new_career("BRP", seed=271)
        finisher = career["players"]["BRP-11"]
        xg = game.expected_goals(3, "center", pressure=1)
        baseline = game.on_target_probability(xg, finisher, pressure=1)
        sharp = copy.deepcopy(finisher)
        sharp.update(sharpness=100, morale=100, form=9.5)
        self.assertGreater(game.on_target_probability(xg, sharp, pressure=1), baseline)
        self.assertEqual(game.expected_goals(3, "center", pressure=1), xg)

        keeper = career["players"]["BRP-01"]
        confident_keeper = copy.deepcopy(keeper)
        confident_keeper.update(sharpness=100, morale=100, form=9.5)
        self.assertGreater(game.effective_goalkeeping(confident_keeper),
                           game.effective_goalkeeping(keeper))
        self.assertLess(game.conversion_probability(
            xg, finisher["finishing"], game.effective_goalkeeping(confident_keeper)),
            game.conversion_probability(
                xg, finisher["finishing"], game.effective_goalkeeping(keeper)))

    def test_same_seed_replays_without_mutating_career_until_settlement(self):
        career = game.new_career("BRP", seed=4021)
        before = copy.deepcopy(career)
        first = game.simulate_match(career, "BRP", "BWA", match_seed=8123, round_index=0)
        second = game.simulate_match(career, "BRP", "BWA", match_seed=8123, round_index=0)

        self.assertEqual(first, second)
        self.assertEqual(career, before)
        game.validate_match(first)
        self.assertTrue(game.apply_match_result(career, first))
        settled = copy.deepcopy(career["table"])
        self.assertFalse(game.apply_match_result(career, first))
        self.assertEqual(career["table"], settled)

    def test_press_and_high_line_have_observable_tradeoffs(self):
        press_low = press_high = 0
        through_mid = through_high = 0
        for seed in range(24):
            low = game.new_career("BRP", seed=seed + 100)
            high = copy.deepcopy(low)
            low["clubs"]["BRP"]["tactics"]["press"] = "low"
            high["clubs"]["BRP"]["tactics"]["press"] = "high"
            press_low += game.simulate_match(low, "BRP", "BWA", seed + 3000, 0)[
                "stats"]["BRP"]["high_regains"]
            press_high += game.simulate_match(high, "BRP", "BWA", seed + 3000, 0)[
                "stats"]["BRP"]["high_regains"]

            mid = game.new_career("BRP", seed=seed + 900)
            raised = copy.deepcopy(mid)
            mid["clubs"]["BRP"]["tactics"]["line"] = "mid"
            raised["clubs"]["BRP"]["tactics"]["line"] = "high"
            for career in (mid, raised):
                career["clubs"]["BWA"]["tactics"]["build"] = "direct"
            through_mid += game.simulate_match(mid, "BRP", "BWA", seed + 6000, 0)[
                "stats"]["BWA"]["through_balls"]
            through_high += game.simulate_match(raised, "BRP", "BWA", seed + 6000, 0)[
                "stats"]["BWA"]["through_balls"]

        self.assertGreater(press_high, press_low)
        self.assertGreater(through_high, through_mid)

    def test_out_of_possession_shape_changes_screen_and_space(self):
        completed_442 = completed_352 = 0
        direct_442 = direct_352 = 0
        for seed in range(48):
            compact = game.new_career("BRP", seed=seed + 400)
            overload = copy.deepcopy(compact)
            compact["clubs"]["BRP"]["tactics"]["out_shape"] = "4-4-2"
            overload["clubs"]["BRP"]["tactics"]["out_shape"] = "3-5-2"
            for career in (compact, overload):
                career["clubs"]["BWA"]["tactics"]["build"] = "direct"
            match_seed = seed + 18_000
            mid = game.simulate_match(compact, "BRP", "BWA", match_seed, 0)
            wide = game.simulate_match(overload, "BRP", "BWA", match_seed, 0)
            completed_442 += mid["stats"]["BWA"]["passes_completed"]
            completed_352 += wide["stats"]["BWA"]["passes_completed"]
            direct_442 += mid["stats"]["BWA"]["through_balls"]
            direct_352 += wide["stats"]["BWA"]["through_balls"]

        self.assertGreater(completed_442, completed_352)
        self.assertGreater(direct_352, direct_442)


class CareerRules(unittest.TestCase):
    def test_escape_returns_from_management_page_to_home(self):
        career = game.new_career("BRP", seed=12)
        app = {"page": "tactics"}
        with patch.object(game.ts, "save"):
            self.assertTrue(game._route_key(27, career, {}, app))
        self.assertEqual(app["page"], "home")

    def test_training_and_scouting_resolve_with_bounded_costs(self):
        career = game.new_career("BRP", seed=17)
        player_id = "FA-06"
        player = career["players"][player_id]
        old_finishing = player["finishing"]
        old_fitness = player["fitness"]
        result = game.training_effect(career, player_id, "Finishing", "normal")
        self.assertGreater(player["finishing"], old_finishing)
        self.assertEqual(player["fitness"], old_fitness - 4)
        self.assertEqual(result["fitness"], -4.0)
        career["clubs"]["BRP"]["training"]["focus"] = "Tactical"
        self.assertTrue(game.prepare_week(career))
        self.assertEqual(game.prepare_week(career), [])
        self.assertEqual(len(career["training_history"]), 1)

        target_id = "FA-01"
        first = game.scout_target(career, target_id)
        second = game.scout_target(career, target_id)
        self.assertEqual(first["confidence"], "LOW")
        self.assertEqual(second["confidence"], "MED")
        self.assertLess(second["fee_range"][1] - second["fee_range"][0],
                        first["fee_range"][1] - first["fee_range"][0])
        target = career["players"][target_id]
        before_count = len(career["clubs"]["BRP"]["roster"])
        deal = game.resolve_offer(career, target_id, target["value"],
                                  target["wage_demand"])
        self.assertTrue(deal["accepted"], deal)
        self.assertEqual(len(career["clubs"]["BRP"]["roster"]), before_count + 1)
        self.assertIn(target_id, career["clubs"]["BRP"]["roster"])
        self.assertNotIn(target_id, career["market"])
        self.assertLessEqual(career["clubs"]["BRP"]["finance"]["weekly_wages"],
                             career["clubs"]["BRP"]["finance"]["wage_budget"])

    def test_match_injury_sets_a_real_recovery_window(self):
        career = game.new_career("BRP", seed=91)
        match = game.new_match(career, "BRP", "BWA", round_index=0, match_seed=331)
        player_id = match["lineups"]["BRP"][0]
        match["player_stats"][player_id] = {"minutes": 90}
        notices = game._injury_check(career, match, AlwaysInjuredRoll())

        player = career["players"][player_id]
        self.assertEqual(len(notices), 1)
        self.assertIn(player["injury"], {row["name"] for row in content.INJURIES})
        self.assertFalse(game.is_available(career, player))
        career["career_week"] = player["injury_until_round"]
        self.assertTrue(game.is_available(career, player))

    def test_complete_season_settles_every_fixture_then_rolls_over(self):
        career = game.new_career("BRP", seed=2026)
        season = game.simulate_full_season(career)

        self.assertTrue(career["season_complete"])
        self.assertEqual(career["round"], content.SEASON_ROUNDS)
        self.assertEqual(len(career["results"]), 30)
        self.assertEqual(len(set(career["played_ids"])), 30)
        self.assertEqual(season["user_place"],
                         game._table_order(career).index("BRP") + 1)
        self.assertEqual(sum(row["played"] for row in career["table"].values()), 60)
        self.assertEqual(sum(row["gf"] for row in career["table"].values()),
                         sum(row["ga"] for row in career["table"].values()))
        for row in career["table"].values():
            self.assertEqual(row["played"], 10)
            self.assertEqual(row["played"], row["won"] + row["drawn"] + row["lost"])
            self.assertEqual(row["points"], row["won"] * 3 + row["drawn"])

        academy = game.begin_next_season(career)
        self.assertEqual(career["season"], 2)
        self.assertEqual(career["round"], 0)
        self.assertFalse(career["season_complete"])
        self.assertEqual(len(academy), len(content.CLUBS))
        self.assertTrue(all(pid in career["players"] for pid in academy))
        self.assertTrue(all(row["played"] == 0 for row in career["table"].values()))


if __name__ == "__main__":
    unittest.main()
