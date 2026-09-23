"""Command line entry point and the boot/launch/return cycle."""
from __future__ import annotations

import argparse
import curses
import json
import sys
import time

from . import boot, brand, library, paths, runner, scaffold
from .launcher import Console

VERSION = "1.0.0"
_C = {"cyan": "\x1b[36m", "grey": "\x1b[90m", "red": "\x1b[31m",
      "green": "\x1b[32m", "yellow": "\x1b[33m", "reset": "\x1b[0m",
      "bold": "\x1b[1m"}


def _c(text: str, name: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{_C.get(name, '')}{text}{_C['reset']}"


def post_game(game, result: runner.Result) -> None:
    """Shown on the bare terminal after a game exits, before curses resumes."""
    print()
    if result.ok or result.interrupted:
        played = library.format_playtime(result.seconds)
        boot.power_off()
        print(_c(f"  ▸ {game.name} — session ended after {played}", "green"))
        time.sleep(0.5)
        return

    print(_c(f"  ✗ {game.name} crashed (exit {result.exit_code})", "red"))
    print(_c(f"    log: {result.log}", "grey"))
    print(_c("    ─── last output " + "─" * 40, "grey"))
    for line in runner.crash_report(result).splitlines():
        print(_c("    " + line, "grey"))
    print()
    try:
        input(_c("  press enter to return to the console ", "yellow"))
    except (EOFError, KeyboardInterrupt):
        pass


def run_console(profile: str) -> int:
    """Boot the console. Curses is fully torn down around every launch."""
    paths.ensure_dirs()
    console = Console(profile)
    while True:
        try:
            action = curses.wrapper(console.loop)
        except KeyboardInterrupt:
            action = None
        finally:
            runner.restore_terminal()

        if action is None or action.kind == "quit":
            print(_c(f"\n  {brand.NAME} — powering off\n", "cyan"))
            return 0

        if action.kind == "launch" and action.game:
            boot.power_on(action.game.name, fast=console.fast_boot)
            result = runner.launch(action.game, action.profile)
            post_game(action.game, result)
            console.refresh_library()


# ------------------------------------------------------------------ commands

def cmd_list(args) -> int:
    games, problems = library.discover()
    stats = library.load_stats()
    if args.json:
        print(json.dumps([{**g.__dict__, "root": str(g.root)} for g in games],
                         indent=2, default=str))
        return 0
    if not games:
        print("  no games found. create one with:  lazstation new my-game")
        return 0
    print()
    print(_c(f"  {len(games)} game(s)", "bold"))
    for g in games:
        st = stats.get(g.slug, {})
        played = library.format_playtime(st.get("seconds", 0)) if st.get("seconds") else "-"
        origin = "" if g.bundled else " (user)"
        print(f"  {_c(g.slug.ljust(20), 'cyan')} {g.name.ljust(24)[:24]} "
              f"{played.rjust(7)}{origin}")
        if g.tagline:
            print(f"  {' ' * 20} {_c(g.tagline[:52], 'grey')}")
    for p in problems:
        print(_c(f"  ! {p}", "red"))
    print()
    return 0


def cmd_play(args) -> int:
    games, _ = library.discover()
    matches = [g for g in games if g.slug == args.slug] or \
              [g for g in games if args.slug.lower() in g.name.lower()]
    if not matches:
        print(_c(f"  no game matching '{args.slug}'", "red"))
        return 1
    game = matches[0]
    if sys.stdout.isatty() and not args.no_boot:
        boot.power_on(game.name)
    result = runner.launch(game, args.profile)
    if not (result.ok or result.interrupted):
        print(_c(f"\n  {game.name} exited {result.exit_code} — {result.log}", "red"))
        print(runner.crash_report(result))
    return result.exit_code if not result.interrupted else 0


def cmd_new(args) -> int:
    target = paths.USER_GAMES if args.user else paths.BUNDLED_GAMES
    try:
        directory = scaffold.create(args.name, target=target, author=args.author)
    except FileExistsError as exc:
        print(_c(f"  {exc}", "red"))
        return 1
    print()
    print(_c(f"  created {directory}", "green"))
    print(f"    {directory / 'game.toml'}   {_c('metadata shown on the console', 'grey')}")
    print(f"    {directory / 'main.py'}     {_c('your game', 'grey')}")
    print()
    print(f"  play it now:   {_c('lazstation play ' + directory.name, 'cyan')}")
    print()
    return 0


def cmd_info(args) -> int:
    games, _ = library.discover()
    for g in games:
        if g.slug == args.slug:
            st = library.load_stats().get(g.slug, {})
            print()
            print(f"  {_c(g.name, 'bold')}  v{g.version}")
            print(f"  {_c(g.slug, 'cyan')}  {g.root}")
            print(f"  entry     {' '.join(g.entry)}")
            print(f"  saves     {paths.save_dir(args.profile, g.slug)}")
            print(f"  log       {paths.log_file(g.slug)}")
            print(f"  launches  {st.get('launches', 0)}")
            print(f"  playtime  {library.format_playtime(st.get('seconds', 0))}")
            if g.description.strip():
                print()
                for line in g.description.strip().splitlines():
                    print(f"  {_c(line, 'grey')}")
            print()
            return 0
    print(_c(f"  unknown game '{args.slug}'", "red"))
    return 1


def cmd_doctor(args) -> int:
    paths.ensure_dirs()
    games, problems = library.discover()
    print()
    print(f"  python     {sys.version.split()[0]}")
    print(f"  games dir  {paths.BUNDLED_GAMES}")
    print(f"  user games {paths.USER_GAMES}")
    print(f"  saves      {paths.SAVES}")
    print(f"  logs       {paths.LOGS}")
    print(f"  sdk        {paths.SDK_DIR}")
    print(f"  found      {len(games)} game(s)")
    ok = True
    for g in games:
        try:
            argv = runner.resolve_argv(g)
            print(_c(f"  ✓ {g.slug}", "green") + _c(f"  {' '.join(argv[:2])}", "grey"))
        except FileNotFoundError as exc:
            ok = False
            print(_c(f"  ✗ {g.slug}: {exc}", "red"))
    for p in problems:
        ok = False
        print(_c(f"  ! {p}", "red"))
    print()
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lazstation",
        description=f"{brand.NAME} — a console for terminal games.")
    p.add_argument("--version", action="version",
                   version=f"{brand.NAME} v{VERSION}")
    p.add_argument("--profile", default="default", help="save profile to use")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("boot", help="open the console (default)")

    pl = sub.add_parser("list", help="list installed games")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_list)

    pp = sub.add_parser("play", help="launch a game directly")
    pp.add_argument("slug")
    pp.add_argument("--no-boot", action="store_true", help="skip the power-on sequence")
    pp.set_defaults(func=cmd_play)

    pn = sub.add_parser("new", help="scaffold a new game")
    pn.add_argument("name")
    pn.add_argument("--author", default="")
    pn.add_argument("--user", action="store_true",
                    help="create under ~/.local/share/termstation/games instead")
    pn.set_defaults(func=cmd_new)

    pi = sub.add_parser("info", help="show details for one game")
    pi.add_argument("slug")
    pi.set_defaults(func=cmd_info)

    sub.add_parser("doctor", help="check the install and every manifest"
                   ).set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "func", None):
        return args.func(args)
    if not sys.stdout.isatty():
        print(f"{brand.NAME} needs a terminal. try:  lazstation list")
        return 1
    return run_console(args.profile)


if __name__ == "__main__":
    sys.exit(main())
