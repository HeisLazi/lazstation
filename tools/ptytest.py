"""Drive a game in a PTY, replay its frames, and assert scripted paths.

Legacy use remains supported:

    python3 ../../tools/ptytest.py 80 24 $'\nq'

For repeatable paths, pass a JSON scenario with named keys, waits, resizes,
snapshots, and assertions. See ``docs/GAME-BRIEF.md`` for the schema.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import pty
import re
import select
import shlex
import signal
import struct
import sys
import termios
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

KEY_BYTES = {
    "ENTER": b"\n", "RETURN": b"\n", "ESC": b"\x1b", "ESCAPE": b"\x1b",
    "TAB": b"\t", "BACKSPACE": b"\x7f", "DELETE": b"\x1b[3~",
    "UP": b"\x1b[A", "DOWN": b"\x1b[B", "RIGHT": b"\x1b[C",
    "LEFT": b"\x1b[D", "HOME": b"\x1b[H", "END": b"\x1b[F",
    "PAGE_UP": b"\x1b[5~", "PGUP": b"\x1b[5~",
    "PAGE_DOWN": b"\x1b[6~", "PGDN": b"\x1b[6~",
    "CTRL_C": b"\x03", "CTRL_D": b"\x04",
}
KEY_BYTES.update({
    "F1": b"\x1bOP", "F2": b"\x1bOQ", "F3": b"\x1bOR", "F4": b"\x1bOS",
    "F5": b"\x1b[15~", "F6": b"\x1b[17~", "F7": b"\x1b[18~",
    "F8": b"\x1b[19~", "F9": b"\x1b[20~", "F10": b"\x1b[21~",
    "F11": b"\x1b[23~", "F12": b"\x1b[24~",
})


@dataclass
class Snapshot:
    name: str
    cols: int
    rows: int
    text: str


@dataclass
class RunResult:
    output: str
    exit_code: int | None
    cols: int
    rows: int
    timed_out: bool = False
    stopped_by_runner: bool = False
    snapshots: dict[str, Snapshot] = field(default_factory=dict)


def _set_size(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ,
                struct.pack("HHHH", max(1, rows), max(1, cols), 0, 0))


def _token_bytes(token: object) -> bytes:
    value = str(token)
    named = KEY_BYTES.get(value.upper())
    if named is not None:
        return named
    if len(value) == 1:
        return value.encode("utf-8")
    if value.startswith("CTRL+") and len(value) == 6:
        code = ord(value[-1].upper()) - ord("@")
        if 1 <= code <= 26:
            return bytes([code])
    raise ValueError(f"unknown key token: {value!r}")


def _send(fd: int, payload: bytes) -> bool:
    try:
        os.write(fd, payload)
        return True
    except OSError:
        return False


def _render(data: str, cols: int, rows: int) -> str:
    # The script is usually launched by path from a game's directory, while
    # tests may import it as tools.ptytest from the repository root.
    tool_dir = str(Path(__file__).resolve().parent)
    if tool_dir not in sys.path:
        sys.path.insert(0, tool_dir)
    from vt import render
    return render(data, cols, rows)


def run_scenario(argv: list[str], cols: int, rows: int,
                 events: Iterable[dict[str, Any]] = (), *,
                 settle: float = 0.12, timeout: float = 8.0,
                 wait_before: float = 0.2, expect_exit: bool = True,
                 env: dict[str, str] | None = None) -> RunResult:
    """Run a child process under a PTY and return output, status, and frames.

    Event types are ``key``, ``keys``, ``text``, ``wait``, ``resize``, and
    ``snapshot``. If ``expect_exit`` is false, the runner captures the final
    frame and then terminates a still-running game cleanly.
    """
    if not argv:
        raise ValueError("argv must contain a program")
    cols, rows = max(1, int(cols)), max(1, int(rows))
    pid, fd = pty.fork()
    if pid == 0:
        child_env = dict(os.environ)
        child_env.update(env or {})
        term = child_env.get("TERM", "").strip().lower()
        if not term or term in {"dumb", "unknown"}:
            child_env["TERM"] = "xterm-256color"
        child_env["LINES"] = str(rows)
        child_env["COLUMNS"] = str(cols)
        try:
            os.execvpe(argv[0], argv, child_env)
        except BaseException:
            import traceback
            traceback.print_exc()
            os._exit(127)

    _set_size(fd, cols, rows)
    output = bytearray()
    snapshots: dict[str, Snapshot] = {}
    final_cols, final_rows = cols, rows
    exit_code: int | None = None
    fd_open = True

    def poll_child() -> bool:
        nonlocal exit_code
        if exit_code is not None:
            return True
        try:
            got, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            exit_code = 0
            return True
        if got:
            exit_code = os.waitstatus_to_exitcode(status)
            return True
        return False

    def drain(seconds: float) -> None:
        nonlocal fd_open
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            done = poll_child()
            if not fd_open:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # Read any bytes already waiting even when the requested wait
                # was zero, without blocking on a quiet child.
                select_timeout = 0.0
            else:
                select_timeout = min(0.05, remaining)
            try:
                readable, _, _ = select.select([fd], [], [], select_timeout)
            except (OSError, ValueError):
                fd_open = False
                return
            if readable:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    fd_open = False
                    return
                if not chunk:
                    fd_open = False
                    return
                output.extend(chunk)
                continue
            if done or remaining <= 0:
                return

    def send(payload: bytes, delay: float | None = None) -> None:
        if exit_code is None and fd_open:
            _send(fd, payload)
        drain(settle if delay is None else max(0.0, float(delay)))

    def capture(name: str) -> None:
        snapshots[name] = Snapshot(name, final_cols, final_rows,
                                   _render(output.decode("utf-8", "replace"),
                                           final_cols, final_rows))

    timed_out = False
    stopped_by_runner = False
    try:
        drain(wait_before)
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                raise ValueError(f"event {index} must be an object")
            kind = event.get("type")
            delay = event.get("wait", event.get("settle"))
            if kind == "key":
                send(_token_bytes(event.get("key", "")), delay)
            elif kind == "keys":
                keys = event.get("keys", [])
                if isinstance(keys, str):
                    keys = list(keys)
                for token in keys:
                    send(_token_bytes(token), delay)
            elif kind == "text":
                send(str(event.get("text", "")).encode("utf-8"), delay)
            elif kind == "wait":
                drain(float(event.get("seconds", settle)))
            elif kind == "resize":
                final_cols = max(1, int(event["cols"]))
                final_rows = max(1, int(event["rows"]))
                _set_size(fd, final_cols, final_rows)
                drain(float(delay if delay is not None else settle))
            elif kind == "snapshot":
                capture(str(event.get("name", f"frame-{index + 1}")))
            else:
                raise ValueError(f"event {index}: unsupported type {kind!r}")

        if expect_exit:
            deadline = time.monotonic() + max(0.0, timeout)
            while exit_code is None and time.monotonic() < deadline:
                drain(min(0.05, deadline - time.monotonic()))
            if exit_code is None:
                timed_out = True
        else:
            drain(settle)

        if exit_code is None:
            stopped_by_runner = not timed_out
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 0.5
            while exit_code is None and time.monotonic() < deadline:
                drain(min(0.05, deadline - time.monotonic()))
            if exit_code is None:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                while exit_code is None:
                    drain(0.05)
        # Make the last frame available even if the script did not request one.
        capture("final")
    finally:
        if exit_code is None:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                _, status = os.waitpid(pid, 0)
                exit_code = os.waitstatus_to_exitcode(status)
            except ChildProcessError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass

    return RunResult(output.decode("utf-8", "replace"), exit_code,
                     final_cols, final_rows, timed_out, stopped_by_runner,
                     snapshots)


def run(argv: list[str], cols: int, rows: int, keys: Iterable[str],
        settle: float = 0.45, env: dict[str, str] | None = None) -> str:
    """Backward-compatible raw-key helper; returns the captured PTY output."""
    events = ({"type": "key", "key": key} for key in keys)
    return run_scenario(argv, cols, rows, events, settle=settle,
                        expect_exit=False, env=env).output


_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|[()][0-2A-Z])")


def plain_output(value: str) -> str:
    """Remove terminal controls while preserving text written across frames."""
    value = _ANSI.sub("", value).replace("\r", "")
    return "".join(ch for ch in value if ch.isprintable() or ch in "\n\t")


def check_assertions(script: dict[str, Any], result: RunResult) -> list[str]:
    """Return scenario assertion failures as readable messages."""
    checks = script.get("assertions", {})
    if not isinstance(checks, dict):
        return ["assertions must be an object"]
    errors: list[str] = []
    if result.timed_out:
        errors.append("child did not exit before the timeout")
    if script.get("expect_exit", True) and result.exit_code is None:
        errors.append("child was expected to exit but has no exit status")
    expected = checks.get("exit_code")
    if expected is not None and result.exit_code != int(expected):
        errors.append(f"expected exit code {expected}, got {result.exit_code}")
    if script.get("expect_exit", True) and expected is None and result.exit_code not in (0, None):
        errors.append(f"expected clean exit code 0, got {result.exit_code}")

    output = plain_output(result.output)
    for needle in checks.get("output_contains", []):
        if str(needle) not in output:
            errors.append(f"output is missing {needle!r}")
    for needle in checks.get("output_not_contains", []):
        if str(needle) in output:
            errors.append(f"output unexpectedly contains {needle!r}")

    frame_checks = checks.get("frames", {})
    if not isinstance(frame_checks, dict):
        errors.append("assertions.frames must be an object")
        return errors
    for name, frame_check in frame_checks.items():
        snapshot = result.snapshots.get(name)
        if snapshot is None:
            errors.append(f"missing snapshot {name!r}")
            continue
        if not isinstance(frame_check, dict):
            errors.append(f"frame assertion {name!r} must be an object")
            continue
        for needle in frame_check.get("contains", []):
            if str(needle) not in snapshot.text:
                errors.append(f"snapshot {name!r} is missing {needle!r}")
        for needle in frame_check.get("not_contains", []):
            if str(needle) in snapshot.text:
                errors.append(f"snapshot {name!r} unexpectedly contains {needle!r}")
    return errors


def _load_script(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read scenario {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("events", []), list):
        raise ValueError("scenario must be a JSON object with an events array")
    return data


def _environment(entries: list[str]) -> dict[str, str]:
    env = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"--env expects KEY=VALUE, got {entry!r}")
        key, value = entry.split("=", 1)
        env[key] = value
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cols", type=int)
    parser.add_argument("rows", type=int)
    parser.add_argument("keys", nargs="?", default="",
                        help="legacy raw key stream (use --script for named keys)")
    parser.add_argument("--script", type=Path, help="JSON PTY scenario")
    parser.add_argument("--settle", type=float, default=0.12,
                        help="seconds to drain after each key (default: 0.12)")
    parser.add_argument("--timeout", type=float, default=8.0,
                        help="seconds to wait for an expected process exit")
    parser.add_argument("--artifacts", type=Path,
                        help="write rendered checkpoint frames here")
    parser.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--command", default="python3 main.py",
                        help="child command parsed without a shell")
    args = parser.parse_args(argv)

    try:
        child = shlex.split(args.command)
        env = _environment(args.env)
        if args.script:
            script = _load_script(args.script)
            result = run_scenario(child, args.cols, args.rows,
                                  script.get("events", []), settle=args.settle,
                                  timeout=float(script.get("timeout", args.timeout)),
                                  wait_before=float(script.get("wait_before", 0.2)),
                                  expect_exit=bool(script.get("expect_exit", True)),
                                  env=env)
            failures = check_assertions(script, result)
        else:
            events = ({"type": "key", "key": key} for key in args.keys)
            result = run_scenario(child, args.cols, args.rows, events,
                                  settle=args.settle, timeout=args.timeout,
                                  expect_exit=False, env=env)
            failures = []
    except (ValueError, OSError) as exc:
        print(f"ptytest: {exc}", file=sys.stderr)
        return 2

    print(_render(result.output, result.cols, result.rows))
    if args.artifacts:
        args.artifacts.mkdir(parents=True, exist_ok=True)
        for name, snapshot in result.snapshots.items():
            safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
            (args.artifacts / f"{safe_name}.txt").write_text(
                snapshot.text + "\n", encoding="utf-8")
    status = f"exit={result.exit_code}" if result.exit_code is not None else "no exit status"
    if result.stopped_by_runner:
        status += " (stopped after capture)"
    print(f"ptytest: {status} at {result.cols}x{result.rows}", file=sys.stderr)
    for failure in failures:
        print(f"ptytest: FAIL: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
