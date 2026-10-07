"""Regression checks for visual findings surfaced by the terminal player bot."""

from __future__ import annotations

import unittest

from games.touchline.checks.player_bot import inspect_ui_frame


class PlayerBotUiInspectionTests(unittest.TestCase):
    def test_right_side_orphan_fragment_is_reported_with_screen_and_row(self):
        row = "║" + " " * 43 + "Ca" + " " * 31 + "║"

        findings = inspect_ui_frame("match-live", row, terminal="80x24")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["screen"], "match-live")
        self.assertEqual(findings[0]["terminal"], "80x24")
        self.assertEqual(findings[0]["line"], 1)
        self.assertEqual(findings[0]["kind"], "orphan_short_text")
        self.assertEqual(findings[0]["text"], "Ca")

    def test_normal_panel_copy_and_left_aligned_short_text_are_not_reported(self):
        text = "\n".join((
            "╔" + "═" * 10 + "╗",
            "║" + "Home      " + "║",
            "║" + "GK        " + "║",
            "║" + "          " + "║",
            "╚" + "═" * 10 + "╝",
        ))

        self.assertEqual(inspect_ui_frame("squad", text, terminal="110x30"), [])

    def test_findings_keep_each_screen_line(self):
        empty = "║" + " " * 20 + "║"
        orphan = "║" + " " * 12 + "A" + " " * 7 + "║"

        findings = inspect_ui_frame(
            "match-events", "\n".join((empty, orphan)), terminal="80x24")

        self.assertEqual([(item["screen"], item["terminal"], item["line"], item["text"])
                          for item in findings], [("match-events", "80x24", 2, "A")])


if __name__ == "__main__":
    unittest.main()
