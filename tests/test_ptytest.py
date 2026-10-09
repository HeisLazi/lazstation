import sys
import unittest

from tools.ptytest import KEY_BYTES, check_assertions, run_scenario


class PtyScenarioTests(unittest.TestCase):
    def test_named_function_keys_use_terminal_sequences(self):
        self.assertEqual(KEY_BYTES["F1"], b"\x1bOP")
        self.assertEqual(KEY_BYTES["F5"], b"\x1b[15~")
        self.assertEqual(KEY_BYTES["F12"], b"\x1b[24~")

    def test_named_keys_resize_snapshot_and_child_status(self):
        program = (
            "import os,sys; print('ready', flush=True); sys.stdin.readline(); "
            "size=os.get_terminal_size(); "
            "print(f'resized:{size.columns}x{size.lines}', flush=True)"
        )
        events = [
            {"type": "snapshot", "name": "ready"},
            {"type": "resize", "cols": 100, "rows": 30, "wait": 0.05},
            {"type": "keys", "keys": ["x", "ENTER"], "wait": 0.05},
        ]
        result = run_scenario([sys.executable, "-c", program], 80, 24,
                              events, settle=0.05, timeout=2.0,
                              wait_before=0.1, expect_exit=True)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(result.timed_out)
        self.assertEqual((result.cols, result.rows), (100, 30))
        self.assertIn("resized:100x30", result.output)
        self.assertIn("ready", result.snapshots["ready"].text)
        self.assertEqual(check_assertions({
            "expect_exit": True,
            "assertions": {
                "exit_code": 0,
                "output_contains": ["resized:100x30"],
                "frames": {"ready": {"contains": ["ready"]}},
            },
        }, result), [])

    def test_dumb_term_is_upgraded_for_curses_child(self):
        result = run_scenario(
            [sys.executable, "-c", "import os; print(os.environ['TERM'], flush=True)"],
            80, 24, [], settle=0.02, timeout=2.0, expect_exit=True,
            env={"TERM": "dumb"},
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("xterm-256color", result.output)

    def test_exit_assertion_reports_wrong_status(self):
        result = run_scenario([sys.executable, "-c", "raise SystemExit(7)"],
                              80, 24, [], timeout=2.0, expect_exit=True)
        errors = check_assertions({
            "expect_exit": True,
            "assertions": {"exit_code": 0},
        }, result)
        self.assertEqual(result.exit_code, 7)
        self.assertTrue(any("expected exit code 0" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
