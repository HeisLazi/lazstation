"""Launching a game as an isolated child process.

The launcher never imports game code. Each game is its own process with the
terminal handed over completely, which means a game may crash, leave curses in
raw mode, or install its own signal handlers without harming the console.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import library, paths
from .library import Game

# Sent to the terminal after a child exits: leave alt-screen, show cursor,
# reset attributes, disable mouse reporting and bracketed paste.
_RESET_SEQ = "\x1b[?1049l\x1b[?25h\x1b[0m\x1b[?1000l\x1b[?2004l"


@dataclass
class Result:
    exit_code: int
    seconds: float
    log: Path

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def interrupted(self) -> bool:
        # Ctrl-C / SIGINT out of a child is a normal way to quit a game.
        return self.exit_code in (130, -2)


def build_env(game: Game, profile: str) -> dict[str, str]:
    """The TermStation contract, passed as environment variables.

    A game that ignores every one of these still runs -- the contract is
    opt-in, which is what lets a forty-line blackjack work on day one.
    """
    env = os.environ.copy()
    saves = paths.save_dir(profile, game.slug)
    saves.mkdir(parents=True, exist_ok=True)

    env["TERMSTATION"] = "1"
    env["TERMSTATION_VERSION"] = "1.0"
    env["TERMSTATION_SLUG"] = game.slug
    env["TERMSTATION_NAME"] = game.name
    env["TERMSTATION_PROFILE"] = profile
    env["TERMSTATION_SAVE_DIR"] = str(saves)
    env["TERMSTATION_DATA_DIR"] = str(game.root)
    env["TERMSTATION_SHARED_DIR"] = str(paths.SAVES / profile / "_shared")

    # Make `import termstation_sdk` work in the child without installing it.
    sdk = str(paths.SDK_DIR)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{sdk}{os.pathsep}{existing}" if existing else sdk
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def resolve_argv(game: Game) -> list[str]:
    """Expand placeholders and make relative program paths absolute."""
    argv = [a.replace("{python}", sys.executable).replace("{root}", str(game.root))
            for a in game.entry]
    program = argv[0]
    candidate = game.root / program
    if candidate.exists():
        argv[0] = str(candidate)
    elif not os.path.isabs(program) and shutil.which(program) is None:
        raise FileNotFoundError(f"cannot find '{program}' for {game.name}")
    # A script path given relative to the game root resolves against it.
    found_script = False
    for i, arg in enumerate(argv[1:], start=1):
        rel = game.root / arg
        if arg.endswith(".py"):
            if rel.exists():
                argv[i] = str(rel)
                found_script = True
            elif Path(arg).is_absolute() and Path(arg).exists():
                found_script = True
            else:
                raise FileNotFoundError(
                    f"{game.name}: entry script '{arg}' does not exist")
    if not found_script and argv[0].endswith(("python", "python3")):
        raise FileNotFoundError(f"{game.name}: entry names no script to run")
    return argv


def restore_terminal() -> None:
    """Put the TTY back into a sane state no matter how the child died."""
    try:
        sys.stdout.write(_RESET_SEQ)
        sys.stdout.flush()
    except Exception:
        pass
    if sys.stdin.isatty():
        try:
            subprocess.run(["stty", "sane"], stdin=sys.stdin, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


def launch(game: Game, profile: str = "default") -> Result:
    """Run a game with the terminal fully handed over. Never raises."""
    paths.ensure_dirs()
    log = paths.log_file(game.slug)
    env = build_env(game, profile)
    started = time.monotonic()
    code = 0

    try:
        argv = resolve_argv(game)
    except FileNotFoundError as exc:
        log.write_text(f"TermStation could not start {game.name}:\n{exc}\n", encoding="utf-8")
        return Result(127, 0.0, log)

    try:
        with open(log, "w", encoding="utf-8") as errlog:
            errlog.write(f"=== {game.name} ({game.slug}) :: {' '.join(argv)}\n")
            errlog.flush()
            # stdin/stdout inherited: the child owns the terminal outright.
            proc = subprocess.run(argv, cwd=str(game.root), env=env, stderr=errlog)
            code = proc.returncode
    except KeyboardInterrupt:
        code = 130
    except OSError as exc:
        with open(log, "a", encoding="utf-8") as errlog:
            errlog.write(f"\nTermStation failed to launch: {exc}\n")
        code = 127
    finally:
        restore_terminal()

    seconds = time.monotonic() - started
    library.record_session(game.slug, seconds, code)
    return Result(code, seconds, log)


def crash_report(result: Result, limit: int = 18) -> str:
    """The tail of a failed game's stderr, for showing the player."""
    try:
        lines = result.log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(no log available)"
    return "\n".join(lines[-limit:]) if lines else "(no output captured)"
