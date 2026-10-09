"""Beastling ("Poke and Mon") regression suites.

Each suite is a standalone script in games/beastling/tests/ (run one directly:
`python3 games/beastling/tests/arena_test.py`). This module runs them all as
subprocesses, each with its own temporary save folder, so a plain
`python -m unittest` covers the game too.
"""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUITES = os.path.join(ROOT, "games", "beastling", "tests")


class BeastlingSuites(unittest.TestCase):
    """One test per suite script; the failure message carries its output."""


def _suite_test(script: str):
    def test(self):
        with tempfile.TemporaryDirectory(prefix="beastling-") as save:
            env = dict(os.environ, TERMSTATION_SAVE_DIR=save)
            r = subprocess.run([sys.executable, os.path.join(SUITES, script)], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-3000:])
    return test


for _script in sorted(os.listdir(SUITES)):
    if _script.endswith("_test.py"):
        setattr(BeastlingSuites, "test_" + _script[: -len("_test.py")], _suite_test(_script))


if __name__ == "__main__":
    unittest.main()
