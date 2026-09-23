"""Game discovery, manifest parsing and play statistics."""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import paths


def _inner(cols: int, rows: int) -> tuple[int, int]:
    """Usable size inside the bezel; falls back to raw size if unframed."""
    import sys as _sys
    _sys.path.insert(0, str(paths.SDK_DIR))
    try:
        from termstation_bezel import geometry
        g = geometry(cols, rows)
        return g.width, g.height
    except Exception:
        return cols, rows

MANIFEST_NAME = "game.toml"


class ManifestError(Exception):
    """A game.toml that exists but cannot be used."""


@dataclass
class Game:
    slug: str
    name: str
    entry: list[str]
    root: Path
    description: str = ""
    version: str = "0.1.0"
    author: str = ""
    tags: list[str] = field(default_factory=list)
    min_cols: int = 80
    min_rows: int = 24
    bundled: bool = True

    @property
    def tagline(self) -> str:
        return self.description.strip().splitlines()[0] if self.description.strip() else ""

    def fits(self, cols: int, rows: int) -> bool:
        """Does the game fit the picture area, once the bezel is subtracted?"""
        inner_cols, inner_rows = _inner(cols, rows)
        return inner_cols >= self.min_cols and inner_rows >= self.min_rows


def _as_argv(value, root: Path) -> list[str]:
    """Accept `entry = "main.py"`, a full argv list, or a shell-ish string."""
    if isinstance(value, list):
        argv = [str(v) for v in value]
    elif isinstance(value, str):
        argv = value.split() if " " in value else [value]
    else:
        raise ManifestError(f"entry must be a string or list, got {type(value).__name__}")
    if not argv:
        raise ManifestError("entry is empty")
    # Bare .py file -> run with the same interpreter the launcher uses.
    if len(argv) == 1 and argv[0].endswith(".py"):
        argv = ["{python}", argv[0]]
    return argv


def load_manifest(directory: Path, bundled: bool = True) -> Game:
    manifest = directory / MANIFEST_NAME
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ManifestError(f"{manifest}: {exc}") from exc

    game = data.get("game", data)
    for required in ("name", "entry"):
        if required not in game:
            raise ManifestError(f"{manifest}: missing required key '{required}'")

    return Game(
        slug=str(game.get("slug") or directory.name).strip(),
        name=str(game["name"]).strip(),
        entry=_as_argv(game["entry"], directory),
        root=directory,
        description=str(game.get("description", "")),
        version=str(game.get("version", "0.1.0")),
        author=str(game.get("author", "")),
        tags=[str(t) for t in game.get("tags", [])],
        min_cols=int(game.get("min_cols", 80)),
        min_rows=int(game.get("min_rows", 24)),
        bundled=bundled,
    )


def discover() -> tuple[list[Game], list[str]]:
    """Scan every search path. Returns (games, problems).

    A broken manifest never stops the console from booting; it is reported.
    """
    games: dict[str, Game] = {}
    problems: list[str] = []
    for base in paths.game_search_paths():
        if not base.is_dir():
            continue
        bundled = base == paths.BUNDLED_GAMES
        for entry in sorted(base.iterdir()):
            if not entry.is_dir() or entry.name.startswith((".", "_")):
                continue
            if not (entry / MANIFEST_NAME).exists():
                continue
            try:
                game = load_manifest(entry, bundled=bundled)
            except ManifestError as exc:
                problems.append(str(exc))
                continue
            games[game.slug] = game  # later paths win, so user games can shadow
    return sorted(games.values(), key=lambda g: g.name.lower()), problems


# --------------------------------------------------------------------------
# play statistics
# --------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_stats() -> dict:
    try:
        return json.loads(paths.LIBRARY_DB.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_stats(stats: dict) -> None:
    paths.LIBRARY_DB.parent.mkdir(parents=True, exist_ok=True)
    tmp = paths.LIBRARY_DB.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    tmp.replace(paths.LIBRARY_DB)


def record_session(slug: str, seconds: float, exit_code: int) -> dict:
    stats = load_stats()
    entry = stats.setdefault(slug, {"launches": 0, "seconds": 0.0, "last_played": None})
    entry["launches"] += 1
    entry["seconds"] = round(entry.get("seconds", 0.0) + max(0.0, seconds), 1)
    entry["last_played"] = _now()
    entry["last_exit"] = exit_code
    save_stats(stats)
    return entry


def format_playtime(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def format_last_played(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return "unknown"
    delta = datetime.now(timezone.utc) - then
    days, secs = delta.days, delta.seconds
    if days > 1:
        return f"{days}d ago"
    if days == 1:
        return "yesterday"
    if secs >= 3600:
        return f"{secs // 3600}h ago"
    if secs >= 60:
        return f"{secs // 60}m ago"
    return "just now"
