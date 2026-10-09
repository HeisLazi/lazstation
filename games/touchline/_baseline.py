"""Shared, explicit headless boundaries for Touchline's P00 tools.

Importing this module does not import the game, read a save, or run a match.
The current UI helper is an untracked shared dependency in some checkouts, so
headless tools supply an inert import shim while importing the legacy rules.
"""
from __future__ import annotations

import importlib
import os
import platform
import sys
import tomllib
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SDK_DIR = REPOSITORY_ROOT / "sdk"
GAME_DIR = Path(__file__).resolve().parent
GAME_MANIFEST = GAME_DIR / "game.toml"
ENGINE_ID = "legacy-main"


class _UnusedUi(ModuleType):
    """Make accidental terminal rendering fail clearly in headless tools."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        raise RuntimeError(f"headless Touchline tool accessed termstation_ui.{name}")


def load_legacy_game() -> Any:
    """Import the existing game with its UI boundary made inert."""
    for path in (str(REPOSITORY_ROOT), str(SDK_DIR)):
        if path not in sys.path:
            sys.path.insert(0, path)

    previous_ui = sys.modules.get("termstation_ui")
    sys.modules["termstation_ui"] = _UnusedUi("termstation_ui")
    try:
        return importlib.import_module("games.touchline.main")
    finally:
        if previous_ui is None:
            sys.modules.pop("termstation_ui", None)
        else:
            sys.modules["termstation_ui"] = previous_ui


def manifest_metadata() -> dict[str, Any]:
    with GAME_MANIFEST.open("rb") as stream:
        manifest = tomllib.load(stream)
    return dict(manifest.get("game", {}))


def engine_metadata(game: Any) -> dict[str, Any]:
    """Report the legacy save version without implying a declared engine tag."""
    return {
        "id": ENGINE_ID,
        "version": None,
        "version_declared": False,
        "version_note": "The legacy game has no separate simulation-engine version.",
        "save_schema_version": int(game.SAVE_DEFAULTS["version"]),
    }


def environment_metadata() -> dict[str, Any]:
    processor = platform.processor()
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": processor or None,
        "cpu_count": os.cpu_count(),
    }


@contextmanager
def guard_sdk_effects(game: Any, *, discard_awards: bool = False
                      ) -> Iterator[list[str]]:
    """Forbid career saves; optionally capture and discard legacy award calls."""
    original_save = game.ts.save
    original_unlock = game.ts.unlock
    discarded_awards: list[str] = []

    def forbidden_save(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("P00 headless tools must not write career saves")

    def award_boundary(key: str, *_args: Any, **_kwargs: Any) -> None:
        if not discard_awards:
            raise RuntimeError(f"unexpected award effect in headless run: {key}")
        discarded_awards.append(str(key))

    game.ts.save = forbidden_save
    game.ts.unlock = award_boundary
    try:
        yield discarded_awards
    finally:
        game.ts.save = original_save
        game.ts.unlock = original_unlock
