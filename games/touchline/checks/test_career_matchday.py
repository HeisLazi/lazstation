"""P17 career-to-spatial-match integration contracts."""

from __future__ import annotations

import copy
import io
import os
import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

from games.touchline import main as game
from games.touchline.esb.career_matchday import (
    CENTER_KICKER_SLOTS,
    MATCHDAY_RULES,
    PROFILE_MAPPING_VERSION,
    SLOT_ROLES,
    build_team_sheet,
    career_tactic,
    default_formation_positions,
    formation_slots,
    legacy_profile,
    legal_formation_positions,
    tactical_slot_bindings,
)
from games.touchline.esb.career_adapter import CareerMatchSession
from games.touchline.esb.ids import PlayerId
from games.touchline.esb.match import MatchPhase, Pitch
from games.touchline.esb.match.engine import _emit
from games.touchline.esb.model import Position2D
from games.touchline.esb.people import PrimaryRole
from games.touchline.esb.tactics import TacticalPhase


class CareerMatchdayTests(unittest.TestCase):
    def _start(self, seed: int = 711):
        career = game.new_career("BRP", seed)
        save_data = {"version": 2, "career": career}
        app = {"match_engine": "spatial", "_save_data": save_data}
        game._start_matchday(career, app, save_data)
        self.assertEqual(app["page"], "match_setup")
        game._handle_match_setup_key(10, career, save_data, app)
        self.assertEqual(app["page"], "spatial_match", app.get("message"))
        return career, save_data, app

    def test_saved_spatial_result_has_a_home_report_route_and_readable_summary(self):
        career = game.new_career("BRP", 2281)
        home, away = game.current_fixture(career)
        scorer_id = career["clubs"][career["club_id"]]["roster"][0]
        record = {
            "id": "match:p17-report",
            "engine_id": game.SPATIAL_ENGINE_ID,
            "season": 1,
            "round": 1,
            "division": "sable",
            "home": home,
            "away": away,
            "home_goals": 2,
            "away_goals": 1,
            "ruleset_id": "touchline.standard",
            "ruleset_version": 1,
            "goal_lineages": [{
                "sequence": 7, "scorer_id": scorer_id, "assist_id": None,
                "own_goal_id": None,
            }],
            "lineage_events": [{
                "sequence": 6, "kind": "pass", "actor_id": scorer_id,
                "payload": {"actor_id": scorer_id},
            }],
            "stats": {"minutes": {scorer_id: 90.0}, "player": {}},
        }
        career["results"].append(record)
        self.assertIs(game._latest_managed_spatial_result(career), record)
        self.assertIn("R match report", game._spatial_home_hint({
            "career": career, "_save_data": {},
        }))

        drawn: list[str] = []
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, _y, value, *_args:
                  drawn.append(str(value)))):
            game._draw_spatial_report(
                None, game.ui.Rect(0, 2, 79, 18), career, {},
            )
        rendered = "\n".join(drawn)
        self.assertIn(f"{game.club_by_id(home)['name']}  2–1  "
                      f"{game.club_by_id(away)['name']}", rendered)
        self.assertIn("GOAL CHRONOLOGY", rendered)
        self.assertIn(career["players"][scorer_id]["name"], rendered)
        self.assertIn("PLAYING TIME · 1 APPEARANCES", rendered)

    def test_pending_spatial_substitution_stays_visible_on_the_live_match(self):
        career, save_data, app = self._start(2293)
        session = game.resume_spatial_career_match(save_data["_career_adapter_state"])
        team_id = game._spatial_user_team(session, career)
        roster = session.match.teams[team_id]
        outgoing_id = next(
            player_id for player_id in roster.starting_ids
            if player_id in session.match.play.players
            and session.match.play.possession_id != player_id
            and session.match.play.players[player_id].profile.primary_role.value != "goalkeeper"
        )
        incoming = next(profile for profile in roster.eligible_bench()
                        if profile.primary_role.value != "goalkeeper")
        career["spatial_matchday_runtime_v1"] = {
            "queued_substitution": {
                "team_id": team_id,
                "outgoing_id": str(outgoing_id),
                "incoming_id": str(incoming.player_id),
            },
        }

        drawn: list[str] = []
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, _y, value, *_args:
                  drawn.append(str(value))),
              mock.patch.object(game, "_draw_pitch_map", return_value={})):
            game._draw_spatial_match(None, game.ui.Rect(0, 2, 79, 18), career, app)
        queue_line = next((line for line in drawn if "CHANGE QUEUED" in line), "")
        self.assertIn(incoming.display_name, queue_line)
        self.assertIn(game._player_name(career, outgoing_id), queue_line)
        self.assertIn("next stoppage", queue_line)

    def test_match_setup_pitch_uses_field_aspect_and_explains_placement(self):
        career = game.new_career("BRP", 1003)
        save_data = {"version": 2, "career": career}
        app = {"match_engine": "spatial", "_save_data": save_data}
        game._start_matchday(career, app, save_data)

        for body in (game.ui.Rect(0, 2, 75, 16), game.ui.Rect(0, 2, 95, 22)):
            with self.subTest(size=(body.width, body.height)):
                drawn: list[str] = []
                with (mock.patch.object(game, "_pair", return_value=0),
                      mock.patch.object(
                          game.ui, "draw_text",
                          side_effect=lambda _win, _x, _y, value, *_args:
                          drawn.append(str(value))),
                      mock.patch.object(game, "_draw_pitch_map",
                                        wraps=game._draw_pitch_map) as pitch_map):
                    game._draw_match_setup(None, body, career, app)
                pitch_area = pitch_map.call_args.args[1]
                cell_aspect = ((pitch_area.width - 2) / (pitch_area.height - 2))
                self.assertAlmostEqual(cell_aspect, 3.0, delta=0.15)
                self.assertTrue(any("PLAN" in line for line in drawn))
                self.assertTrue(any("local x/y" in line for line in drawn))
                self.assertTrue(any("w Y-2m" in line and "s Y+2m" in line
                                    and "a X-2m" in line and "d X+2m" in line
                                    for line in drawn))
                self.assertTrue(any("SELECTED @" in line for line in drawn))
                if body.height > 16:
                    self.assertTrue(all(profile["name"] in "\n".join(drawn)
                                        for profile in (
                                            career["players"][player_id]
                                            for player_id in app["match_setup"]["lineup_ids"])))

        screen = SimpleNamespace(erase=lambda: None, getmaxyx=lambda: (24, 76))
        footer_rows: list[tuple[int, str]] = []
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, y, value, *_args:
                  footer_rows.append((y, str(value))))):
            game._draw_frame(screen, career, app)
        footer = next(text for y, text in footer_rows if y == 23)
        self.assertIn("1–9,0,A select", footer)
        self.assertIn("wasd place", footer)
        self.assertIn("F shape", footer)

        game._handle_match_setup_key(ord("A"), career, save_data, app)
        self.assertEqual(app["match_setup"]["selected_slot"], 10)
        self.assertIn("Selected", app["message"])
        game._handle_match_setup_key(ord("f"), career, save_data, app)
        self.assertEqual(app["match_setup"]["selected_slot"], 0)
        selected_slot = formation_slots(app["match_setup"]["shape"])[0]
        before_move = app["match_setup"]["positions"][selected_slot]
        game._handle_match_setup_key(ord("a"), career, save_data, app)
        after_move = app["match_setup"]["positions"][selected_slot]
        self.assertEqual(app["match_setup"]["selected_slot"], 0)
        self.assertAlmostEqual(after_move.x_m, before_move.x_m - 2.0)

    def test_selected_player_zoom_projects_local_spacing_and_live_detail(self):
        career, save_data, app = self._start(1007)
        game._advance_spatial_match(career, save_data, app, 60)
        session = game._spatial_session(save_data)
        match = session.match
        player_id = next(
            player_id for player_id, state in match.play.players.items()
            if state.team_id == game._spatial_user_team(game._spatial_session(save_data), career)
        )
        other_id = next(candidate for candidate in match.play.players
                        if candidate != player_id)
        # A close pair collides in the rendered full-field viewport but
        # resolves when the selected-player camera zooms.
        state = match.play.players[player_id]
        other = match.play.players[other_id]
        focus_position = Position2D(51.5, 34.0)
        match.play.players[player_id] = replace(
            state, motion=replace(state.motion, position=focus_position))
        match.play.players[other_id] = replace(
            other, motion=replace(other.motion, position=Position2D(52.5, 34.0)))
        save_data["_career_adapter_state"] = replace(
            save_data["_career_adapter_state"], spatial_match_json=session.to_json())

        app["match_view"] = "pitch"
        app["spatial_selected_player_id"] = str(player_id)
        app["spatial_pitch_zoom"] = False
        drawn: list[str] = []
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, _y, value, *_args: drawn.append(str(value)))):
              game._draw_spatial_match(None, game.ui.Rect(0, 2, 75, 16), career, app)
        viewport = app["spatial_pitch_viewport"]
        self.assertEqual(
            game._pitch_map_cell(focus_position, match.play.pitch, *viewport),
            game._pitch_map_cell(Position2D(52.5, 34.0), match.play.pitch, *viewport),
        )
        game._handle_spatial_match_key(ord("z"), career, save_data, app)
        drawn.clear()
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, _y, value, *_args: drawn.append(str(value)))):
              game._draw_spatial_match(None, game.ui.Rect(0, 2, 75, 16), career, app)
        bounds = app["spatial_pitch_bounds"]
        self.assertNotEqual(
            game._pitch_map_cell(focus_position, match.play.pitch, *viewport, bounds),
            game._pitch_map_cell(Position2D(52.5, 34.0), match.play.pitch,
                                 *viewport, bounds),
        )
        self.assertIsNone(game._pitch_map_cell(
            Position2D(5.0, 5.0), match.play.pitch, *viewport, bounds))
        self.assertTrue(any("FOCUS " in line and "X≈" in line and "Y≈" in line
                            for line in drawn))
        self.assertTrue(any("PITCH · CLOSE" in line for line in drawn))
        self.assertTrue(any("LATEST EVENTS" in line for line in drawn))
        self.assertTrue(any("[ ] next" in line for line in drawn))
        self.assertTrue(any("Keys 1–9,0,A,C–Z / a–k select" in line
                            for line in drawn))
        self.assertTrue(any("B ball/player" in line for line in drawn))
        event_heading = next(index for index, line in enumerate(drawn)
                             if "LATEST EVENTS" in line)
        self.assertTrue(any(line.strip() for line in drawn[event_heading + 1:]),
                        "the pitch sidebar should show a latest event or its empty state")
        self.assertTrue(any("BALL OFF" in line for line in drawn))
        self.assertTrue(any("X≈" in line and "Y≈" in line for line in drawn))
        self.assertTrue(any("╭┄" in line for line in drawn))
        self.assertTrue(any("┆" in line for line in drawn))
        self.assertTrue(any("┬" in line for line in drawn))
        self.assertTrue(any("├" in line for line in drawn))
        joined = "\n".join(drawn)
        self.assertIn("x51.5/y34.0m", joined)
        self.assertIn("LAST", joined)
        self.assertLessEqual(max(map(len, drawn)), 80)

        app["spatial_watching"] = True
        drawn.clear()
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, _y, value, *_args: drawn.append(str(value)))):
            game._draw_spatial_match(None, game.ui.Rect(0, 0, 80, 24), career, app)
        self.assertTrue(any("ticks/update" in line for line in drawn))
        game._handle_spatial_match_key(ord("z"), career, save_data, app)
        self.assertFalse(app["spatial_pitch_zoom"])
        self.assertIn("Full pitch restored", app["message"])

    def test_live_player_cycle_ignores_stale_pitch_zoom_bounds(self):
        career, save_data, app = self._start(1009)
        session = game._spatial_session(save_data)
        player_ids = list(session.match.play.players)
        app.update({
            "match_view": "live",
            "spatial_pitch_zoom": True,
            "spatial_pitch_bounds": (20.0, 56.0, 24.0, 40.0),
            "spatial_selected_player_id": str(player_ids[0]),
        })
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(game.ui, "draw_text")):
            game._draw_spatial_match(
                None, game.ui.Rect(0, 0, 80, 24), career, app)
        self.assertIsNone(app["spatial_pitch_bounds"])

        app["spatial_pitch_bounds"] = (20.0, 56.0, 24.0, 40.0)
        with mock.patch.object(
                game, "_spatial_player_cycle_ids",
                wraps=game._spatial_player_cycle_ids) as cycle:
            game._handle_spatial_match_key(ord("]"), career, save_data, app)
        self.assertIsNone(cycle.call_args.args[3])

    def test_live_feed_distinguishes_restart_awarded_from_restart_taken(self):
        career = game.new_career("BRP", 1021)
        actor_id = next(iter(career["players"]))
        awarded = SimpleNamespace(
            kind="restart_awarded", match_tick=0,
            payload={"actor_id": actor_id, "kind": "kickoff"},
        )
        taken = SimpleNamespace(
            kind="restart_taken", match_tick=0,
            payload={"actor_id": actor_id, "kind": "kickoff"},
        )
        awarded_line = game._spatial_sidebar_event_line(awarded, career, 250, 40)
        taken_line = game._spatial_sidebar_event_line(taken, career, 250, 40)
        self.assertIn(" AWARD · ", awarded_line)
        self.assertIn(" TAKE · ", taken_line)
        self.assertNotEqual(awarded_line, taken_line)

    def test_bezel_restore_redraws_the_complete_bottom_edge(self):
        class TTYStringIO(io.StringIO):
            def isatty(self):
                return True

        terminal = TTYStringIO()
        screen = SimpleNamespace(framed=True, ox=0, oy=0, cab_w=10, cab_h=5)
        with mock.patch.object(game.sys, "stdout", terminal):
            game._restore_bezel_bottom_right(None, screen)
        self.assertIn("\x1b[5;1H╚════════╝", terminal.getvalue())

    def test_zoom_key_remains_visible_in_finished_and_keeper_gates(self):
        win = SimpleNamespace(erase=lambda: None, getmaxyx=lambda: (24, 76))
        cases = (
            (MatchPhase.FINISHED, False),
            (MatchPhase.ABANDONED, False),
            (MatchPhase.IN_PLAY, True),
        )
        for phase, keeper_required in cases:
            with self.subTest(phase=phase, keeper_required=keeper_required):
                app = {
                    "page": "spatial_match", "spatial_match_phase": phase,
                    "match_view": "pitch", "spatial_pitch_zoom": True,
                    "spatial_keeper_user_required": keeper_required,
                }
                drawn: list[tuple[int, str]] = []
                with (mock.patch.object(game, "_pair", return_value=0),
                      mock.patch.object(
                          game.ui, "draw_text",
                          side_effect=lambda _win, _x, y, text, *_args:
                          drawn.append((y, str(text))))):
                    game._draw_frame(win, None, app)
                footer = next(text for y, text in drawn if y == 23)
                self.assertIn("Z full", footer)
                self.assertIn("Esc", footer)
                self.assertLessEqual(len(footer), 75)

    def test_live_footer_teaches_pitch_zoom_route_without_clipping(self):
        win = SimpleNamespace(erase=lambda: None, getmaxyx=lambda: (24, 76))
        app = {
            "page": "spatial_match", "spatial_match_phase": MatchPhase.IN_PLAY,
            "match_view": "live", "spatial_watching": True,
        }
        drawn: list[tuple[int, str]] = []
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, y, text, *_args:
                  drawn.append((y, str(text))))):
            game._draw_frame(win, None, app)
        footer = next(text for y, text in drawn if y == 23)
        self.assertIn("Tab views", footer)
        self.assertIn("Z pitch", footer)
        self.assertLessEqual(len(footer), 75)

    def test_z_from_live_opens_the_zoomed_pitch(self):
        career, save_data, app = self._start(1011)
        app["match_view"] = "live"
        game._handle_spatial_match_key(ord("z"), career, save_data, app)
        self.assertEqual(app["match_view"], "pitch")
        self.assertTrue(app["spatial_pitch_zoom"])
        self.assertIn("live ball", app["message"])
        game._handle_spatial_match_key(ord("z"), career, save_data, app)
        self.assertFalse(app["spatial_pitch_zoom"])
        self.assertIn("Full pitch restored", app["message"])

        app["match_view"] = "live"
        player_id = next(iter(game._spatial_session(save_data).match.play.players))
        app["spatial_selected_player_id"] = str(player_id)
        game._handle_spatial_match_key(ord("z"), career, save_data, app)
        self.assertIn("selected player", app["message"])

        app["match_view"] = "live"
        game._handle_spatial_match_key(ord("B"), career, save_data, app)
        self.assertEqual(app["match_view"], "pitch")
        self.assertTrue(app["spatial_pitch_focus_ball"])
        self.assertIn("live ball", app["message"])
        game._handle_spatial_match_key(ord("B"), career, save_data, app)
        self.assertFalse(app["spatial_pitch_focus_ball"])
        self.assertIn("B returns to the live ball", app["message"])

    def test_legacy_capability_mapping_is_versioned_and_tendencies_stay_neutral(self):
        fast = legacy_profile({
            "id": "player:p17-fast", "name": "Fast", "position": "FWD",
            "pace": 90, "passing": 60, "finishing": 70,
        }, "club:p17")
        slow = legacy_profile({
            "id": "player:p17-slow", "name": "Slow", "position": "FWD",
            "pace": 30, "passing": 60, "finishing": 70,
        }, "club:p17")
        self.assertEqual(fast.capabilities.provenance, PROFILE_MAPPING_VERSION)
        speed = {item.name: item.value for item in fast.capabilities.measurements}
        slow_speed = {item.name: item.value for item in slow.capabilities.measurements}
        self.assertGreater(speed["maximum_speed"], slow_speed["maximum_speed"])
        self.assertTrue(all(item.value == 0.5 for item in fast.tendencies.values))
        self.assertTrue(all(item.provenance.source == "touchline:" + PROFILE_MAPPING_VERSION
                            for item in fast.tendencies.values))

    def test_center_circle_projection_is_used_by_the_actual_team_sheet(self):
        career = game.new_career("BRP", 812)
        home = game.current_fixture(career)[0]
        away = game.current_fixture(career)[1]
        home_shape = career["clubs"][home]["tactics"]["in_shape"]
        away_shape = career["clubs"][away]["tactics"]["in_shape"]
        home_lineup = game.lineup_for(career, home, home_shape)
        away_lineup = game.lineup_for(career, away, away_shape)
        local = default_formation_positions(away_shape)
        kickoff_slot = CENTER_KICKER_SLOTS[away_shape]
        local[kickoff_slot] = Position2D(52.5, 34.0)
        projected = legal_formation_positions("away", local)
        self.assertLess(projected[kickoff_slot].x_m, 52.5)
        sheet = build_team_sheet(career, away, "away", away_lineup, shape=away_shape)
        actual = {str(player.profile.player_id): player.motion.position
                  for player in sheet.sheet.starters}
        bound_striker = dict(sheet.slot_bindings)[kickoff_slot]
        expected_local = dict(sheet.local_positions)[str(bound_striker)]
        self.assertEqual(actual[str(bound_striker)].x_m, Pitch().length_m - expected_local.x_m)
        center = Position2D(Pitch().length_m / 2.0, Pitch().width_m / 2.0)
        self.assertGreaterEqual(
            ((actual[str(bound_striker)].x_m - center.x_m) ** 2
             + (actual[str(bound_striker)].y_m - center.y_m) ** 2) ** 0.5,
            MATCHDAY_RULES.restart_clearance_m,
        )
        self.assertEqual(len(home_lineup), 11)

    def test_selected_style_replaces_the_base_phase_instead_of_being_shadowed(self):
        wide = career_tactic("wide")
        possession = career_tactic("possession")
        wide_phase = next(item for item in wide.phases
                          if item.phase is TacticalPhase.ESTABLISHED_ATTACK)
        possession_phase = next(item for item in possession.phases
                                if item.phase is TacticalPhase.ESTABLISHED_ATTACK)
        wide_lw = next(item for item in wide_phase.instructions if item.slot_id == "LW")
        possession_lw = next(item for item in possession_phase.instructions
                             if item.slot_id == "LW")
        self.assertNotEqual(wide_lw.anchor, possession_lw.anchor)
        self.assertEqual(wide_lw.actions[0].value, "hold_width")

    def test_named_formations_have_distinct_roles_positions_and_tactical_bindings(self):
        expected = {
            "4-4-2": Counter({
                PrimaryRole.GOALKEEPER: 1,
                PrimaryRole.CENTER_BACK: 2,
                PrimaryRole.FULLBACK: 2,
                PrimaryRole.CENTRAL_MIDFIELDER: 2,
                PrimaryRole.WIDE_FORWARD: 2,
                PrimaryRole.STRIKER: 2,
            }),
            "4-3-3": Counter({
                PrimaryRole.GOALKEEPER: 1,
                PrimaryRole.CENTER_BACK: 2,
                PrimaryRole.FULLBACK: 2,
                PrimaryRole.DEFENSIVE_MIDFIELDER: 1,
                PrimaryRole.CENTRAL_MIDFIELDER: 2,
                PrimaryRole.WIDE_FORWARD: 2,
                PrimaryRole.STRIKER: 1,
            }),
            "3-5-2": Counter({
                PrimaryRole.GOALKEEPER: 1,
                PrimaryRole.CENTER_BACK: 3,
                PrimaryRole.FULLBACK: 2,
                PrimaryRole.DEFENSIVE_MIDFIELDER: 1,
                PrimaryRole.CENTRAL_MIDFIELDER: 2,
                PrimaryRole.STRIKER: 2,
            }),
        }
        career = game.new_career("BRP", 1731)
        club_id = career["club_id"]
        for shape, role_counts in expected.items():
            with self.subTest(shape=shape):
                slots = formation_slots(shape)
                self.assertEqual(len(slots), 11)
                self.assertEqual(Counter(SLOT_ROLES[slot] for slot in slots), role_counts)
                lineup = game.lineup_for(career, club_id, shape)
                sheet = build_team_sheet(career, club_id, "home", lineup, shape=shape)
                self.assertEqual(
                    Counter(player.profile.primary_role for player in sheet.sheet.starters),
                    role_counts,
                )
                tactical = tactical_slot_bindings(shape, dict(sheet.slot_bindings))
                self.assertEqual(len(tactical), 11)
                self.assertEqual(len(set(tactical.values())), 11)
                positions = default_formation_positions(shape)
                self.assertEqual(set(positions), set(slots))
                projected = legal_formation_positions("home", positions)
                self.assertEqual(
                    projected[CENTER_KICKER_SLOTS[shape]], Position2D(52.5, 34.0)
                )

    def test_managed_possession_plan_is_not_rewritten_when_playing_away(self):
        club_id = next(
            club["id"] for club in game.content.CLUBS
            if game.current_fixture(game.new_career(club["id"], 1811))[1] == club["id"]
        )
        career = game.new_career(club_id, 1811)
        save_data = {"version": 2, "career": career}
        app = {"match_engine": "spatial", "_save_data": save_data}
        game._start_matchday(career, app, save_data)
        self.assertEqual(app["match_setup"]["team_id"], "away")
        app["match_setup"]["style_id"] = "possession"
        game._handle_match_setup_key(10, career, save_data, app)
        session = game._spatial_session(save_data)
        self.assertEqual(game._spatial_user_team(session, career), "away")
        self.assertEqual(
            app["spatial_tactical_runtimes"]["away"].tactic.tactic_id,
            career_tactic("possession").tactic_id,
        )

    def test_free_placement_changes_kickoff_input_and_spatial_tick_moves_players(self):
        career = game.new_career("BRP", 913)
        save_data = {"version": 2, "career": career}
        app = {"match_engine": "spatial", "_save_data": save_data}
        game._start_matchday(career, app, save_data)
        setup = app["match_setup"]
        setup["selected_slot"] = 0
        slot = formation_slots(setup["shape"])[0]
        before_local = setup["positions"][slot]
        game._handle_match_setup_key(ord("d"), career, save_data, app)
        after_local = setup["positions"][slot]
        self.assertEqual(after_local.x_m, before_local.x_m + 2.0)
        game._handle_match_setup_key(10, career, save_data, app)
        session = game._spatial_session(save_data)
        self.assertEqual(session.match.rules, MATCHDAY_RULES)
        user_team = game._spatial_user_team(session, career)
        club_id = career["club_id"]
        player_id = career["clubs"][club_id]["spatial_formation_v1"]["slot_bindings"][slot]
        player_id = PlayerId(player_id)
        local = session.match.play.players[player_id].motion.position
        if user_team == "away":
            expected_x = Pitch().length_m - after_local.x_m
        else:
            expected_x = after_local.x_m
        self.assertEqual(local.x_m, expected_x)
        initial_positions = {
            key: state.motion.position for key, state in session.match.play.players.items()
        }
        advanced = game._advance_spatial_match(career, save_data, app, 40)
        self.assertGreater(advanced, 0)
        session = game._spatial_session(save_data)
        self.assertTrue(any(
            state.motion.position != initial_positions[player_id]
            for player_id, state in session.match.play.players.items()
            if player_id in initial_positions
        ))
        ticks = [event.match_tick for event in session.match.events]
        self.assertEqual(ticks, sorted(ticks))

    def test_split_step_advancement_is_deterministic(self):
        first = self._start(1207)
        second = self._start(1207)
        career_a, save_a, app_a = first
        career_b, save_b, app_b = second
        game._advance_spatial_match(career_a, save_a, app_a, 80)
        game._advance_spatial_match(career_b, save_b, app_b, 31)
        game._advance_spatial_match(career_b, save_b, app_b, 49)
        self.assertEqual(
            game._spatial_session(save_a).to_json(),
            game._spatial_session(save_b).to_json(),
        )
        self.assertEqual(
            career_a["spatial_matchday_runtime_v1"]["distance_m"],
            career_b["spatial_matchday_runtime_v1"]["distance_m"],
        )

    def test_matchday_views_filter_moves_offer_full_pitch_and_select_player(self):
        career, save_data, app = self._start(1381)
        game._advance_spatial_match(career, save_data, app, 40)
        session = game._spatial_session(save_data)
        events = list(session.match.events)
        self.assertNotIn("B", game._spatial_player_symbols(session.match).values())
        moves = [event for event in events if event.kind == "move"]
        key_events = game._key_match_events(events)
        self.assertTrue(moves)
        self.assertLess(len(key_events), len(events))
        self.assertTrue(all(event.kind != "move" for event in key_events))
        self.assertRegex(
            game._spatial_event_line(moves[0], career, session.match.rules.tick_duration_ms),
            r"^\d{2}:\d{2}\.\d MOVE",
        )
        own_goal_id = next(iter(career["players"]))
        own_goal = SimpleNamespace(
            kind="goal", match_tick=moves[0].match_tick,
            payload={"actor_id": None, "own_goal_player_id": own_goal_id},
        )
        self.assertIn(
            f"OWN GOAL · {game._player_name(career, own_goal_id)}",
            game._spatial_event_line(
                own_goal, career, session.match.rules.tick_duration_ms),
        )

        drawn: list[str] = []
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, _y, value, *_args: drawn.append(str(value)))):
            game._draw_spatial_chronology(
                None, game.ui.Rect(0, 0, 100, 24), events, career,
                session.match.rules.tick_duration_ms, {},
            )
        self.assertTrue(any("CHRONOLOGY · KEY" in line for line in drawn))
        self.assertTrue(any("detail rows hidden" in line for line in drawn))
        self.assertFalse(any(" MOVE · " in line for line in drawn))

        contact = SimpleNamespace(
            kind="ball_contact", match_tick=7,
            payload={"actor_id": "touchline.player.contact"},
        )
        control = SimpleNamespace(
            kind="possession_controlled", match_tick=7,
            payload={"actor_id": "touchline.player.contact"},
        )
        unmatched_contact = SimpleNamespace(
            kind="ball_contact", match_tick=8,
            payload={"actor_id": "touchline.player.other"},
        )
        self.assertEqual(
            [item.source for item in game._key_match_events(
                [contact, control, unmatched_contact])],
            [control, unmatched_contact],
        )

        app["match_view"] = "events"
        game._handle_spatial_match_key(ord("m"), career, save_data, app)
        self.assertTrue(app["show_movement_events"])
        drawn.clear()
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, _y, value, *_args: drawn.append(str(value)))):
            game._draw_spatial_chronology(
                None, game.ui.Rect(0, 0, 100, 24), events, career,
                session.match.rules.tick_duration_ms, app,
            )
        self.assertTrue(any("CHRONOLOGY · ALL" in line for line in drawn))
        self.assertTrue(any(" MOVE · " in line for line in drawn))

        player_id = next(
            player_id for player_id in session.match.play.players
            if player_id != session.match.play.possession_id
        )
        player_key = game._spatial_player_symbols(session.match)[str(player_id)]
        app["match_view"] = "pitch"
        game._handle_spatial_match_key(ord(player_key), career, save_data, app)
        self.assertEqual(app["spatial_selected_player_id"], str(player_id))
        player_ids = list(session.match.play.players)
        other_id = next(item for item in player_ids
                        if item != player_id
                        and item != session.match.play.possession_id)
        first_state = session.match.play.players[player_id]
        other_state = session.match.play.players[other_id]
        session.match.play.players[other_id] = replace(
            other_state,
            motion=replace(other_state.motion, position=first_state.motion.position),
        )
        save_data["_career_adapter_state"] = replace(
            save_data["_career_adapter_state"], spatial_match_json=session.to_json())
        drawn.clear()
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, _y, value, *_args: drawn.append(str(value)))):
            game._draw_spatial_match(
                None, game.ui.Rect(0, 0, 100, 30), career, app,
            )
        self.assertTrue(any("VIEWS" in line and "[PITCH]" in line for line in drawn))
        self.assertTrue(any("HOME →" in line and "AWAY" in line for line in drawn))
        self.assertTrue(any("!" in line for line in drawn))
        self.assertTrue(any("SEL " in line for line in drawn))
        self.assertTrue(any("[" in line and "]" in line and "│" in line for line in drawn))
        self.assertGreater(
            len(game._spatial_player_cycle_ids(
                session.match, str(player_id), app["spatial_pitch_viewport"])), 1,
        )

        clustered_ids = game._spatial_player_cycle_ids(
            session.match, str(player_id), app["spatial_pitch_viewport"])
        clustered_index = clustered_ids.index(PlayerId(str(player_id)))
        clustered_next = clustered_ids[(clustered_index + 1) % len(clustered_ids)]
        game._handle_spatial_match_key(ord("]"), career, save_data, app)
        self.assertEqual(app["spatial_selected_player_id"], str(clustered_next))

        app.pop("spatial_pitch_viewport", None)
        app.pop("spatial_selected_player_id", None)
        game._handle_spatial_match_key(ord("]"), career, save_data, app)
        self.assertEqual(app["spatial_selected_player_id"], str(player_ids[0]))
        game._handle_spatial_match_key(ord("]"), career, save_data, app)
        self.assertEqual(app["spatial_selected_player_id"], str(player_ids[1]))

        player_stats = game._spatial_player_statistics(session.match)
        attempts = sum(values.get("pass_attempts", 0) for values in player_stats.values())
        completed = sum(values.get("passes_completed", 0) for values in player_stats.values())
        self.assertEqual(attempts, sum(event.kind == "pass" for event in events))
        self.assertLessEqual(completed, attempts)
        drawn.clear()
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, _y, value, *_args: drawn.append(str(value)))):
            game._draw_spatial_stats(
                None, game.ui.Rect(0, 0, 78, 18), session.match, career,
                {"home": "Home", "away": "Away"}, {},
            )
        self.assertTrue(any("PA/PC pass attempts/completed" in line for line in drawn))
        self.assertLessEqual(max(map(len, drawn)), 78)

        map_rows: list[str] = []
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, _y, value, *_args: map_rows.append(str(value)))):
            cluster = game._draw_pitch_map(
                None, game.ui.Rect(0, 0, 60, 15), Pitch(),
                [("home", Position2D(10, 10), "player:p17-a"),
                 ("home", Position2D(10, 10), "player:p17-b")],
            )
        self.assertEqual(cluster, {"player:p17-a": 2, "player:p17-b": 2})
        self.assertTrue(any("+" in line for line in map_rows))
        self.assertTrue(any("[" in line and "]" in line for line in map_rows))

    def test_key_chronology_groups_repeated_actions_but_all_view_keeps_each_event(self):
        career = game.new_career("BRP", 1383)
        actor_id = next(iter(career["players"]))

        def event(kind: str, tick: int):
            return SimpleNamespace(
                kind=kind, match_tick=tick, payload={"actor_id": actor_id})

        events = [
            event("carry", 10), event("carry", 11), event("carry", 12),
            event("press", 13), event("press", 14), event("press", 15),
            event("pass", 16), event("carry", 17),
        ]
        grouped = game._key_match_events(events)
        self.assertEqual(
            [(item.kind, item.repeat_count, item.match_tick, item.through_tick)
             for item in grouped],
            [("carry", 3, 10, 12), ("press", 3, 13, 15),
             ("pass", 1, 16, None), ("carry", 1, 17, 17)],
        )
        grouped_carry = game._spatial_event_line(grouped[0], career, 1000)
        self.assertTrue(grouped_carry.startswith("00:10.0–00:12.0 CARRY ×3"))

        drawn: list[str] = []
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, _y, value, *_args:
                  drawn.append(str(value)))):
            game._draw_spatial_chronology(
                None, game.ui.Rect(0, 0, 100, 10), events, career, 1000, {},
            )
        self.assertTrue(any("CARRY ×3" in line for line in drawn))
        self.assertTrue(any("PRESS ×3" in line for line in drawn))
        action_rows = [line for line in drawn
                       if any(label in line for label in ("CARRY", "PRESS", "PASS"))]
        self.assertEqual([line.split(" ", 1)[1].split(" ×", 1)[0].split(" ·", 1)[0]
                          for line in action_rows],
                         ["CARRY", "PRESS", "PASS", "CARRY"])

        drawn.clear()
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, _y, value, *_args:
                  drawn.append(str(value)))):
            game._draw_spatial_chronology(
                None, game.ui.Rect(0, 0, 100, 10), events, career, 1000,
                {"show_movement_events": True},
            )
        self.assertTrue(any("CHRONOLOGY · ALL" in line for line in drawn))
        self.assertEqual(sum(" CARRY · " in line for line in drawn), 4)
        self.assertEqual(sum(" PRESS · " in line for line in drawn), 3)
        self.assertEqual(len(events), 8)

    def test_setup_preview_names_assigned_slot_and_away_shape(self):
        career = game.new_career("BRP", 1831)
        save_data = {"version": 2, "career": career}
        app = {"match_engine": "spatial", "_save_data": save_data}
        game._start_matchday(career, app, save_data)
        drawn: list[str] = []
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, _y, value, *_args: drawn.append(str(value)))):
            game._draw_match_setup(None, game.ui.Rect(0, 0, 78, 22), career, app)
        self.assertTrue(any("SLOT GK" in line and "natural" in line for line in drawn))
        self.assertTrue(any("3-5-2" in line or "4-3-3" in line for line in drawn))

    def test_home_hint_describes_saved_spatial_match_as_live(self):
        career, save_data, app = self._start(1841)
        app["page"] = "home"
        hint = game._spatial_home_hint(app)
        self.assertIn("Live match paused", hint)
        self.assertNotIn("Pre-kickoff", hint)

    def test_keeper_replacement_footer_names_tab_focus_targets(self):
        class FakeWindow:
            def erase(self):
                pass

            def getmaxyx(self):
                return 24, 80

        career = game.new_career("BRP", 1843)
        app = {"page": "spatial_subs", "spatial_keeper_user_required": True}
        drawn: list[str] = []
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, _y, value, *_args: drawn.append(str(value)))):
            game._draw_frame(FakeWindow(), career, app)
        footer = next(line for line in drawn if "GK required" in line)
        self.assertIn("Tab OFF/ON", footer)
        self.assertIn("Enter apply", footer)

    def test_formation_preview_keeps_coordinates_role_and_unique_player_markers(self):
        class FakeWindow:
            def getmaxyx(self):
                return 20, 75

        career = game.new_career("BRP", 1849)
        save_data = {"version": 2, "career": career}
        app = {"match_engine": "spatial", "_save_data": save_data}
        game._start_matchday(career, app, save_data)
        game._handle_match_setup_key(ord("f"), career, save_data, app)
        self.assertEqual(app["match_setup"]["shape"], "3-5-2")
        drawn: list[tuple[int, int, str]] = []
        body = game.ui.Rect(0, 2, 75, 16)
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, x, y, value, *_args:
                  drawn.append((x, y, str(value))))):
            game._draw_match_setup(FakeWindow(), body, career, app)

        pitch_rows = [line for x, y, line in drawn
                      if x == body.x and body.y + 3 <= y < body.y + 12]
        self.assertEqual(sum(line.count("2") for line in pitch_rows), 1)
        selected = next(line for _x, _y, line in drawn
                        if line.startswith("SELECTED "))
        self.assertIn("Enno Vale · goalkeeper", selected)
        slot_line = next(line for _x, _y, line in drawn if line.startswith("SLOT "))
        self.assertIn("local x/y 4.0/34.0m", slot_line)
        self.assertLessEqual(len(selected), body.width)
        self.assertIn("SLOT GK · natural GK", slot_line)

    def test_spatial_substitution_lists_show_all_players_and_scroll_selection(self):
        career, save_data, app = self._start(1853)
        session = game._spatial_session(save_data)
        team_id = game._spatial_user_team(session, career)
        roster = session.match.teams[team_id]
        active_ids = [player_id for player_id in roster.starting_ids
                      if player_id in session.match.play.players]
        expected_names = [game._player_name(career, player_id) for player_id in active_ids]
        drawn: list[tuple[int, int, str]] = []

        def render(body, selected):
            drawn.clear()
            app["spatial_sub_out_index"] = selected
            with (mock.patch.object(game, "_pair", return_value=0),
                  mock.patch.object(
                      game.ui, "draw_text",
                      side_effect=lambda _win, x, y, value, *_args:
                      drawn.append((x, y, str(value))))):
                game._draw_spatial_substitutions(None, body, career, app)

        render(game.ui.Rect(0, 2, 75, 16), 10)
        labels = [value for _x, _y, value in drawn]
        self.assertTrue(all(any(name in value for value in labels)
                            for name in expected_names))
        self.assertTrue(any(value.startswith(">" + expected_names[-1])
                            for value in labels))
        self.assertFalse(any("central_midfielder" in value for value in labels))

        render(game.ui.Rect(0, 2, 55, 10), 10)
        labels = [value for _x, _y, value in drawn]
        self.assertTrue(any("6–11/11" in value for value in labels))
        self.assertTrue(any(value.startswith(">" + expected_names[-1])
                            for value in labels))

    def test_live_sidebar_event_keeps_actor_visible_at_compact_width(self):
        career, _save_data, _app = self._start(1859)
        actor_id = next(iter(career["players"]))
        career["players"][actor_id]["name"] = "Kesa Amel"
        event = SimpleNamespace(
            kind="possession_controlled", match_tick=1,
            payload={"actor_id": actor_id},
        )
        line = game._spatial_sidebar_event_line(event, career, 20, 39)
        self.assertIn("CONTROL", line)
        self.assertIn("Kesa Amel", line)
        self.assertLessEqual(len(line), 39)

    def test_resuming_spatial_match_replaces_new_career_message(self):
        career, save_data, app = self._start(1861)
        app["message"] = "Choose a club and build a football life around its people."
        game._start_matchday(career, app, save_data)
        self.assertEqual(app["page"], "spatial_match")
        self.assertIn("Resumed spatial match", app["message"])
        self.assertNotIn("Choose a club", app["message"])

    def test_spatial_checkpoint_survives_game_save_reload(self):
        career, save_data, app = self._start(1313)
        before = save_data["_career_adapter_state"].spatial_match_json
        with tempfile.TemporaryDirectory(prefix="esb-p17-save-reload-") as directory:
            with mock.patch.dict(os.environ, {"TERMSTATION_SAVE_DIR": directory}):
                game._persist(save_data, career)
                loaded = game.migrate_save(game.ts.load(game.SAVE_DEFAULTS))
        adapter = loaded["_career_adapter_state"]
        self.assertEqual(adapter.current_match_engine_id, "touchline.spatial.v1")
        self.assertEqual(adapter.spatial_match_json, before)
        self.assertEqual(game._spatial_session(loaded).match.play.clock.tick, 0)

    def test_queued_substitution_waits_for_a_legal_engine_stoppage(self):
        career, save_data, app = self._start(1411)
        session = game._spatial_session(save_data)
        game._advance_spatial_match(career, save_data, app, 1)
        session = game._spatial_session(save_data)
        self.assertEqual(session.match.phase, MatchPhase.IN_PLAY)
        team_id = game._spatial_user_team(session, career)
        roster = session.match.teams[team_id]
        active = [player_id for player_id in roster.starting_ids
                  if player_id in session.match.play.players
                  and session.match.play.players[player_id].profile.primary_role.value != "goalkeeper"
                  and player_id != session.match.play.possession_id]
        bench = [item for item in roster.eligible_bench()
                 if item.primary_role.value != "goalkeeper"]
        self.assertTrue(active and bench)
        outgoing, incoming = str(active[0]), str(bench[0].player_id)
        game._queue_spatial_substitution(career, save_data, app, outgoing, incoming)
        runtime_state = career["spatial_matchday_runtime_v1"]
        self.assertEqual(runtime_state["queued_substitution"]["outgoing_id"], outgoing)
        self.assertNotIn(PlayerId(incoming), session.match.play.players)
        game._advance_spatial_match(career, save_data, app, 1)
        session = game._spatial_session(save_data)
        self.assertNotIn(PlayerId(incoming), session.match.play.players)
        self.assertIsNotNone(runtime_state.get("queued_substitution"))

    def test_keeper_replacement_gate_stops_quick_sim_and_filters_to_eligible_keeper(self):
        career, save_data, app = self._start(1517)
        session = game._spatial_session(save_data)
        team_id = game._spatial_user_team(session, career)
        roster = session.match.teams[team_id]
        exhausted_windows = [f"used-window-{index}"
                             for index in range(MATCHDAY_RULES.substitution_windows_allowed)]
        roster.substitution_windows_used = list(exhausted_windows)
        roster.substitutions_made = len(exhausted_windows)
        self.assertLess(roster.substitutions_made, MATCHDAY_RULES.substitutions_allowed)
        keeper_id = next(
            player_id for player_id, state in session.match.play.players.items()
            if state.team_id == team_id and state.profile.primary_role is PrimaryRole.GOALKEEPER
        )
        reserve_id = str(roster.substitutes[0].player_id)
        roster.substitutes[0] = legacy_profile(
            career["players"][reserve_id], career["club_id"], PrimaryRole.GOALKEEPER
        )
        del session.match.play.players[keeper_id]
        roster.sent_off_ids.append(keeper_id)
        active_outfield = [player_id for player_id in roster.starting_ids
                           if player_id in session.match.play.players]
        carrier_id = active_outfield[0]
        session.match.play.possession_id = carrier_id
        session.match.play.possession_team_id = team_id
        session.match.keeper_replacement_team_id = team_id
        save_data["_career_adapter_state"] = replace(
            save_data["_career_adapter_state"], spatial_match_json=session.to_json()
        )

        drawn: list[str] = []
        with (mock.patch.object(game, "_pair", return_value=0),
              mock.patch.object(
                  game.ui, "draw_text",
                  side_effect=lambda _win, _x, _y, value, *_args: drawn.append(str(value)))):
            game._draw_spatial_players(
                None, game.ui.Rect(0, 0, 100, 30), session.match, career,
                {"home": "Home", "away": "Away"}, {},
            )
        self.assertTrue(any(
            game._player_name(career, keeper_id) in line
            and "· GK · SENT OFF" in line
            for line in drawn
        ))

        advanced = game._advance_spatial_match(career, save_data, app, 500_000)
        self.assertEqual(advanced, 0)
        self.assertEqual(app["page"], "spatial_subs")
        self.assertTrue(app["spatial_keeper_user_required"])
        self.assertEqual(app["spatial_sub_focus"], "in")
        game._handle_spatial_subs_key(10, career, save_data, app)
        self.assertEqual(app["page"], "spatial_subs")
        self.assertIn("ball carrier cannot leave", app["message"])
        game._handle_spatial_subs_key(9, career, save_data, app)
        self.assertEqual(app["spatial_sub_focus"], "out")
        game._handle_spatial_subs_key(ord("j"), career, save_data, app)
        self.assertEqual(app["spatial_sub_out_index"], 1)
        game._handle_spatial_subs_key(9, career, save_data, app)
        self.assertEqual(app["spatial_sub_focus"], "in")
        game._handle_spatial_subs_key(10, career, save_data, app)
        self.assertIn("Change completed", app.get("message", ""))

        raw_session = CareerMatchSession.from_json(
            save_data["_career_adapter_state"].spatial_match_json
        )
        self.assertEqual(
            raw_session.match.teams[team_id].substitution_windows_used,
            exhausted_windows,
        )
        self.assertEqual(
            raw_session.match.teams[team_id].substitutions_made,
            len(exhausted_windows) + 1,
        )
        substitution_event = next(
            event for event in reversed(raw_session.match.events)
            if event.kind == "substitution"
        )
        self.assertEqual(substitution_event.payload["window_id"], exhausted_windows[-1])
        lineup = set(career["clubs"][career["club_id"]]["lineup"])
        active = {str(player_id) for player_id, state in raw_session.match.play.players.items()
                  if state.team_id == team_id}
        sent_off = {str(player_id) for player_id in raw_session.match.teams[team_id].sent_off_ids}
        self.assertEqual(lineup, active | sent_off)

        restored = game._spatial_session(save_data)
        self.assertIsNone(restored.match.keeper_replacement_team_id)
        self.assertIn(roster.substitutes[0].player_id, restored.match.play.players)
        self.assertEqual(app["page"], "spatial_match")

    def test_opponent_keeper_ai_uses_a_used_window_when_all_windows_are_spent(self):
        career, save_data, _app = self._start(1529)
        session = game._spatial_session(save_data)
        user_team = game._spatial_user_team(session, career)
        team_id = "away" if user_team == "home" else "home"
        roster = session.match.teams[team_id]
        exhausted_windows = [f"used-window-{index}"
                             for index in range(MATCHDAY_RULES.substitution_windows_allowed)]
        roster.substitution_windows_used = list(exhausted_windows)
        roster.substitutions_made = len(exhausted_windows)
        reserve_id = str(roster.substitutes[0].player_id)
        club_id = str(session.binding.home_club_id if team_id == "home"
                       else session.binding.away_club_id)
        roster.substitutes[0] = legacy_profile(
            career["players"][reserve_id], club_id, PrimaryRole.GOALKEEPER)
        keeper_id = next(
            player_id for player_id, state in session.match.play.players.items()
            if state.team_id == team_id
            and state.profile.primary_role is PrimaryRole.GOALKEEPER
        )
        cover = next(profile for profile in roster.eligible_bench()
                     if profile.primary_role is PrimaryRole.GOALKEEPER)
        del session.match.play.players[keeper_id]
        roster.sent_off_ids.append(keeper_id)
        session.match.phase = MatchPhase.RESTART_READY
        session.match.keeper_replacement_team_id = team_id

        self.assertTrue(game._queue_opponent_keeper_replacement(career, session))
        _message, applied = game._apply_queued_spatial_substitution(career, session)
        self.assertTrue(applied)
        self.assertIn(cover.player_id, session.match.play.players)
        self.assertIsNone(session.match.keeper_replacement_team_id)
        self.assertEqual(roster.substitution_windows_used, exhausted_windows)
        self.assertEqual(roster.substitutions_made, len(exhausted_windows) + 1)
        event = next(event for event in reversed(session.match.events)
                     if event.kind == "substitution")
        self.assertEqual(event.payload["window_id"], exhausted_windows[-1])


if __name__ == "__main__":
    unittest.main()
