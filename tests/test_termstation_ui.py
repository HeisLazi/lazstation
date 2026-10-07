import curses
import unittest

from sdk import termstation_ui as ui


class MemoryWindow:
    def __init__(self, rows, cols):
        self.rows, self.cols = rows, cols
        self.cells = [[" "] * cols for _ in range(rows)]
        self.attributes = [[0] * cols for _ in range(rows)]

    def getmaxyx(self):
        return self.rows, self.cols

    def addnstr(self, y, x, text, count, attr=0):
        if y < 0 or y >= self.rows or x < 0 or x >= self.cols:
            raise curses.error("outside window")
        for offset, char in enumerate(text[:count]):
            if x + offset < self.cols:
                self.cells[y][x + offset] = char
                self.attributes[y][x + offset] = attr

    def line(self, y):
        return "".join(self.cells[y])


class UiTests(unittest.TestCase):
    def test_rect_splits_respect_gaps_and_parent_bounds(self):
        parent = ui.Rect(3, 4, 21, 9)
        left, right = ui.split_horizontal(parent, ratio=0.6, gap=2)
        self.assertEqual((left.x, left.y, left.width, left.height), (3, 4, 11, 9))
        self.assertEqual((right.x, right.right), (16, 24))
        self.assertEqual(left.right + 2, right.x)

    def test_viewport_keeps_selection_visible_after_page_moves(self):
        view = ui.Viewport()
        view.move("end", count=20, height=5)
        self.assertEqual(view.selected, 19)
        self.assertEqual(view.offset, 15)
        view.move("page_up", count=20, height=5)
        self.assertEqual(view.selected, 14)
        self.assertEqual(view.offset, 14)
        view.move("home", count=20, height=5)
        self.assertEqual((view.selected, view.offset), (0, 0))

    def test_list_and_table_clamp_preselected_index_before_enter(self):
        items = ui.ListView(["first", "last"], selected=20)
        self.assertEqual(items.handle(10, height=2), 1)
        self.assertEqual(items.selected, 1)

        table = ui.TableView(["Name"], [["first"], ["last"]], selected=20)
        self.assertEqual(table.handle(10, height=3), 1)
        self.assertEqual(table.selected, 1)

    def test_list_selection_and_table_render_stay_within_view(self):
        win = MemoryWindow(8, 24)
        view = ui.ListView([f"Player {i}" for i in range(12)])
        for _ in range(8):
            view.handle(curses.KEY_DOWN, height=3)
        self.assertEqual(view.selected, 8)
        view.draw(win, ui.Rect(0, 0, 12, 3))
        self.assertIn("Player 8", "\n".join(win.line(y) for y in range(3)))

        table = ui.TableView(
            ["Name", "POS", "FIT"],
            [["A long player name", "FWD", 92], ["Mara Voss", "MID", 81]],
        )
        table.draw(win, ui.Rect(2, 3, 18, 4))
        rendered = "\n".join(win.line(y) for y in range(3, 7))
        self.assertIn("Name", rendered)
        self.assertIn("FWD", rendered)
        self.assertEqual(len(win.cells), 8)

    def test_tabs_and_clipping(self):
        win = MemoryWindow(2, 18)
        tabs = ui.Tabs(["Home", "Squad", "Tactics"])
        self.assertTrue(tabs.handle(ord("3")))
        self.assertEqual(tabs.current, "Tactics")
        tabs.draw(win, 0, 0, 18)
        self.assertIn("Tactics", win.line(0))
        self.assertEqual(ui.clip("Touchline", 5), "Touc…")
        self.assertEqual(ui.clip("abc", 0), "")

    def test_panel_corners_and_table_columns_respect_rect(self):
        win = MemoryWindow(6, 30)
        ui.draw_panel(win, ui.Rect(18, 2, 12, 4), "Roster")
        self.assertEqual(win.cells[2][18], "┌")
        self.assertEqual(win.cells[2][29], "┐")
        self.assertEqual(win.cells[5][18], "└")
        self.assertEqual(win.cells[5][29], "┘")

        bounded = MemoryWindow(5, 30)
        table = ui.TableView(["A", "B", "C", "D"],
                             [["long"] * 4])
        table.draw(bounded, ui.Rect(4, 0, 9, 5), gap=1)
        self.assertTrue(all(bounded.cells[y][13:] == [" "] * 17
                            for y in range(5)))


if __name__ == "__main__":
    unittest.main()
