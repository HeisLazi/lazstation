"""Filesystem layout for TermStation.

Everything mutable lives under XDG dirs so a game folder can be deleted,
re-cloned or git-managed without ever touching save data.
"""
from __future__ import annotations

import os
from pathlib import Path

APP = "termstation"


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default).expanduser()


#: Where the launcher itself lives (repo root).
ROOT = Path(__file__).resolve().parent.parent

#: Bundled games shipped with the console.
BUNDLED_GAMES = ROOT / "games"

#: The importable helper module offered to child processes.
SDK_DIR = ROOT / "sdk"

DATA_HOME = _xdg("XDG_DATA_HOME", ".local/share") / APP
CONFIG_HOME = _xdg("XDG_CONFIG_HOME", ".config") / APP
STATE_HOME = _xdg("XDG_STATE_HOME", ".local/state") / APP

#: Extra game folders the user drops in, scanned alongside BUNDLED_GAMES.
USER_GAMES = DATA_HOME / "games"

SAVES = DATA_HOME / "saves"
LOGS = STATE_HOME / "logs"
LIBRARY_DB = STATE_HOME / "library.json"
CONFIG_FILE = CONFIG_HOME / "config.json"


def game_search_paths() -> list[Path]:
    """Directories scanned for games, in priority order."""
    paths = [BUNDLED_GAMES, USER_GAMES]
    extra = os.environ.get("TERMSTATION_GAME_PATH", "")
    paths += [Path(p).expanduser() for p in extra.split(os.pathsep) if p.strip()]
    return paths


def save_dir(profile: str, slug: str) -> Path:
    return SAVES / profile / slug


def log_file(slug: str) -> Path:
    return LOGS / f"{slug}.log"


def ensure_dirs() -> None:
    for d in (DATA_HOME, CONFIG_HOME, STATE_HOME, USER_GAMES, SAVES, LOGS):
        d.mkdir(parents=True, exist_ok=True)
