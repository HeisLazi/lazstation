import unittest

from tools.vt import render


class VirtualTerminalTests(unittest.TestCase):
    def test_erase_after_bottom_right_never_indexes_outside_the_grid(self):
        self.assertEqual(render("1234\x1b[K", cols=4, rows=1), "1234")


if __name__ == "__main__":
    unittest.main()
