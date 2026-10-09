"""Subprocess continuation endpoint for CORE-01; not a production game runner."""

from __future__ import annotations

import sys

from games.touchline.checks.replay_scenario import run_synthetic_updates
from games.touchline.esb.serialization import dumps, loads
from games.touchline.esb.state import SimulationState


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: replay_worker UPDATE_COUNT")
    state = loads(sys.stdin.read(), SimulationState)
    run_synthetic_updates(state, int(sys.argv[1]))
    sys.stdout.write(dumps(state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
