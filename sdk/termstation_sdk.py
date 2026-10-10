"""termstation_sdk -- optional conveniences for TermStation games.

Importing this is never required. A game that knows nothing about TermStation
runs fine; this module just saves you writing the same save-file and
box-drawing code in every game you make.

    import termstation_sdk as ts

    save = ts.load({"gold": 0})
    save["gold"] += 10
    ts.save(save)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

__all__ = [
    "running_in_termstation", "profile", "slug", "save_dir", "data_dir",
    "load", "save", "delete_save", "slots", "shared_dir",
    "clear", "size", "color", "rule", "box", "title", "center",
    "prompt", "ask_int", "ask_choice", "confirm", "pause", "menu",
    "RESET", "BOLD", "DIM",
]

# ---------------------------------------------------------------- environment

def running_in_termstation() -> bool:
    return os.environ.get("TERMSTATION") == "1"


def profile() -> str:
    return os.environ.get("TERMSTATION_PROFILE", "default")


def slug() -> str:
    return os.environ.get("TERMSTATION_SLUG") or Path(sys.argv[0]).stem


def save_dir() -> Path:
    """Where this game's save data belongs. Created on demand.

    Outside TermStation it falls back to a local .saves/ folder so a game is
    still runnable straight from its own directory.
    """
    raw = os.environ.get("TERMSTATION_SAVE_DIR")
    path = Path(raw) if raw else Path.cwd() / ".saves"
    path.mkdir(parents=True, exist_ok=True)
    return path


def shared_dir() -> Path:
    """Cross-game data for the current profile (a shared wallet, say)."""
    raw = os.environ.get("TERMSTATION_SHARED_DIR")
    path = Path(raw) if raw else save_dir().parent / "_shared"
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    """The game's own folder -- assets shipped alongside the code."""
    raw = os.environ.get("TERMSTATION_DATA_DIR")
    return Path(raw) if raw else Path(sys.argv[0]).resolve().parent


# ---------------------------------------------------------------- persistence

def load(default: dict | None = None, name: str = "save") -> dict:
    """Read a save slot, filling in anything `default` has that it lacks.

    Merging rather than replacing means adding a field to your game does not
    break saves written before that field existed -- which matters, because
    you will keep editing a game people are already playing.
    """
    path = save_dir() / f"{name}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default) if default else {}
    if not isinstance(data, dict):
        return dict(default) if default else {}
    for key, value in (default or {}).items():
        data.setdefault(key, value)
    return data


def save(data: dict, name: str = "save") -> Path:
    """Write a save slot atomically, so a crash mid-write cannot corrupt it."""
    path = save_dir() / f"{name}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)
    return path


def delete_save(name: str = "save") -> bool:
    try:
        (save_dir() / f"{name}.json").unlink()
        return True
    except OSError:
        return False


def slots() -> list[str]:
    return sorted(p.stem for p in save_dir().glob("*.json"))


# ---------------------------------------------------------------- presentation

RESET, BOLD, DIM = "\x1b[0m", "\x1b[1m", "\x1b[2m"

#: The console's palette, as xterm-256 indices. Games keep calling
#: ts.color(text, "bright_green") exactly as before -- the names now resolve
#: into one warm, consistent scheme instead of raw terminal primaries, so
#: every game matches the dashboard without changing a line of game code.
_THEME = {
    "black": 233, "white": 223, "paper": 223,
    "grey": 244, "gray": 244, "ink": 244,
    "red": 167, "bright_red": 203,
    "green": 108, "bright_green": 150,
    "yellow": 179, "bright_yellow": 221, "amber": 214,
    "blue": 68, "bright_blue": 111,
    "magenta": 176, "bright_magenta": 212,
    "cyan": 109, "bright_cyan": 152,
}
#: Fallback for terminals without 256 colours.
_BASIC = {
    "black": 30, "red": 31, "green": 32, "yellow": 33, "blue": 34,
    "magenta": 35, "cyan": 36, "white": 37, "grey": 90, "gray": 90,
    "ink": 90, "paper": 37, "amber": 33,
    "bright_red": 91, "bright_green": 92, "bright_yellow": 93,
    "bright_blue": 94, "bright_magenta": 95, "bright_cyan": 96,
}


#: Console themes; the launcher hands its pick to games as TERMSTATION_THEME.
#: "neo" (the default) paints the picture's own background, so text never sits
#: on a transparent or busy terminal, in crisp high-contrast ink with one blue
#: accent. The classic phosphors draw on the terminal's own background exactly
#: as before -- same bytes. Every neo colour is an exact xterm-256 entry: the
#: curses launcher can only draw those, and identical indices on both sides
#: mean no colour jump when a game takes over the screen.
CLASSIC_THEMES = ("amber", "green", "mono", "ice", "classic")
_NEO = {
    "black": 234, "white": 255, "paper": 254,
    "grey": 246, "gray": 246, "ink": 246,
    "red": 167, "bright_red": 203,
    "green": 78, "bright_green": 120,
    "yellow": 179, "bright_yellow": 221, "amber": 75,     # UI accent: LazStation blue
    "blue": 68, "bright_blue": 111,
    "magenta": 176, "bright_magenta": 213,
    "cyan": 80, "bright_cyan": 123,
}
#: Neo surfaces: the picture, the title band, cabinet lines, the accent (LED,
#: brand) and the title text.
NEO_SURFACE = {"bg": 234, "band": 236, "frame": 60, "accent": 75, "title": 255}


def theme() -> str:
    """The active theme name: "neo" unless a classic phosphor was chosen."""
    name = os.environ.get("TERMSTATION_THEME", "neo").strip().lower()
    return name if name in CLASSIC_THEMES else "neo"


def _rich() -> bool:
    """Does this terminal do 256 colours?"""
    term = os.environ.get("TERM", "")
    return "256" in term or bool(os.environ.get("COLORTERM"))


def _tty() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def surface() -> str:
    """The escape that starts a stretch of picture: neo's background and resting
    ink. Empty for the classic themes. Games that write raw escapes (blanking a
    row, say) should lead with this, or their row punches a hole in the picture."""
    if theme() != "neo" or not _tty():
        return ""
    if _rich():
        return f"\x1b[48;5;{NEO_SURFACE['bg']};38;5;{_NEO['paper']}m"
    return "\x1b[40;37m"


def _span_end() -> str:
    """End of a neo colour span: bold off and back to the resting ink, while
    the background stays. A full reset here would blank the background
    mid-line and leave holes after every coloured word."""
    return f"\x1b[22;38;5;{_NEO['paper']}m" if _rich() else "\x1b[22;37m"


def color(text: str, name: str = "white", bold: bool = False) -> str:
    if not _tty():
        return text
    if theme() == "neo":
        code = f"38;5;{_NEO.get(name, _NEO['paper'])}" if _rich() else str(_BASIC.get(name, 37))
        return f"\x1b[{'1;' if bold else ''}{code}m{text}{_span_end()}"
    if _rich():
        code = _THEME.get(name, _THEME["paper"])
        return f"\x1b[{'1;' if bold else ''}38;5;{code}m{text}{RESET}"
    code = _BASIC.get(name, 37)
    return f"\x1b[{'1;' if bold else ''}{code}m{text}{RESET}"


def _restore_terminal() -> None:
    """Neo spans end in the resting ink, not a full reset -- so on the way out
    put the terminal back, or the shell prompt inherits the console's colours."""
    if theme() == "neo" and _tty():
        sys.stdout.write(RESET)
        sys.stdout.flush()


import atexit as _atexit  # noqa: E402
_atexit.register(_restore_terminal)


def size() -> tuple[int, int]:
    """Usable size. Inside the TV cabinet this is the picture, not the
    terminal, so box(), title() and rule() fit the frame automatically."""
    if _tv_state.get("active"):
        screen = _tv_state["screen"]
        return _tv_state["stage"] or screen.width, screen.height
    cols, rows = shutil.get_terminal_size((80, 24))
    return cols, rows


def clear() -> None:
    if _tty():
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.flush()


def center(text: str, width: int | None = None) -> str:
    width = width or size()[0]
    return text.center(width)


def rule(char: str = "─", width: int | None = None, fg: str = "ink") -> str:
    return color(char * (width or size()[0]), fg)


def box(lines: list[str], width: int | None = None, fg: str = "amber") -> str:
    """A bordered panel. Lines longer than the box are truncated, not wrapped."""
    width = width or min(size()[0], 78)
    inner = width - 2
    out = [color("╭" + "─" * inner + "╮", fg)]
    for line in lines:
        keep = inner + (len(line) - _visible_len(line))
        out.append(color("│", fg) + line[:keep].ljust(inner) + color("│", fg))
    out.append(color("╰" + "─" * inner + "╯", fg))
    return "\n".join(out)


def title(text: str, fg: str = "amber") -> str:
    """A heading band, matching the console's own chrome."""
    width = min(size()[0], 78)
    bar = "━" * width
    return "\n".join([color(bar, fg),
                       color(text.center(width), "bright_yellow", bold=True),
                       color(bar, fg)])


# ---------------------------------------------------------------- input

def _out(*parts: object, sep: str = " ") -> None:
    """print() for the input helpers -- lands inside the picture when the TV
    is on, and behaves like an ordinary print() when it is not."""
    if _tv_state.get("active"):
        tv_print(*parts, sep=sep)
    else:
        print(*parts, sep=sep)


def _seat_cursor() -> None:
    """Put the terminal cursor on the TV's current line before reading input,
    so the player's typing and its echo appear inside the frame."""
    state = _tv_state
    if not state.get("active") or not _tty():
        return
    screen = state["screen"]
    if state["row"] >= screen.height - 2:
        tv_clear()
    col = screen.x + state["indent"] + 1
    # surface(): under neo the player's typing (and its backspaces) echo onto
    # the picture's background, not the terminal's.
    sys.stdout.write(f"\x1b[{screen.y + state['row'] + 1};{col}H{surface()}")
    sys.stdout.flush()
    state["row"] += 1


def prompt(message: str, default: str = "") -> str:
    """Ask for a line of input.

    If stdin closes there is no player left to ask, so we exit cleanly rather
    than spin forever re-prompting -- that turns a piped/backgrounded run into
    an infinite loop instead of a quiet exit.
    """
    suffix = f" [{default}]" if default else ""
    _seat_cursor()
    try:
        answer = input(f"{color('▸', 'amber')} {color(message + suffix, 'paper')}"
                       f"{color(':', 'ink')} ").strip()
    except EOFError:
        print()
        raise SystemExit(0) from None
    return answer or default


def ask_int(message: str, lo: int | None = None, hi: int | None = None,
            default: int | None = None) -> int:
    while True:
        raw = prompt(message, "" if default is None else str(default))
        try:
            value = int(raw)
        except ValueError:
            _out(color("  numbers only", "red"))
            continue
        if lo is not None and value < lo:
            _out(color(f"  minimum is {lo}", "red"))
            continue
        if hi is not None and value > hi:
            _out(color(f"  maximum is {hi}", "red"))
            continue
        return value


def ask_choice(message: str, options: list[str]) -> str:
    """Accept a number, or any unambiguous prefix of an option."""
    lowered = [o.lower() for o in options]
    shown = "/".join(options)
    while True:
        raw = prompt(f"{message} ({shown})").lower()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        matches = [o for o, low in zip(options, lowered) if low.startswith(raw) and raw]
        if len(matches) == 1:
            return matches[0]
        _out(color("  pick one of: " + shown, "red"))


def confirm(message: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = prompt(f"{message} [{hint}]").lower()
    return default if not raw else raw.startswith("y")


def pause(message: str = "press enter to continue") -> None:
    _seat_cursor()
    try:
        input(color(f"  {message}", "grey"))
    except EOFError:
        pass


def menu(heading: str, options: list[str], back: str | None = "Back") -> int:
    """Numbered menu. Returns the chosen index, or -1 for the back option."""
    entries = list(options) + ([back] if back else [])
    _out()
    _out(color(f"┤ {heading} ├", "amber", bold=True))
    for i, opt in enumerate(entries, 1):
        marker = color(f"[{i}]", "bright_yellow")
        text = color(opt, "ink" if back and i == len(entries) else "paper")
        _out(f"   {marker} {text}")
    choice = ask_int("choose", 1, len(entries))
    return -1 if back and choice == len(entries) else choice - 1


# ---------------------------------------------------------------- the TV

from termstation_bezel import geometry as _geometry, frame_lines, side_runs, title_bar  # noqa: E402

_tv_state = {"active": False, "row": 0, "title": "", "screen": None,
             "stage": 0, "indent": 0}

#: Text is hard to read in very long lines, so the playfield is capped and
#: centred inside the picture rather than stretched across it.
STAGE_MAX = 78


def tv(title: str = "") -> "object":
    """Draw the CRT cabinet and put the cursor inside the picture.

    Returns the screen geometry; `screen.width` / `screen.height` are the
    usable area. On a terminal too small to frame, this clears the screen and
    returns full-size geometry, so a game never has to special-case it.
    """
    title = title or os.environ.get("TERMSTATION_NAME", "")
    screen = _geometry()
    stage = min(screen.width, STAGE_MAX)
    _tv_state.update(active=True, row=0, title=title, screen=screen,
                     stage=stage, indent=(screen.width - stage) // 2)
    _repaint_frame(screen, title)
    return screen


#: Window title, so a compositor rule can single the console out -- e.g. make
#: it fully opaque in Hyprland: windowrule = opacity 1.0 override, title:^(LazStation)
WINDOW_TITLE = "LazStation"


def _repaint_frame(screen, title: str) -> None:
    if not _tty():
        return
    out = [f"\x1b]2;{WINDOW_TITLE}" + (f" · {title}" if title else "") + "\x07", "\x1b[2J\x1b[H"]
    if screen.framed:
        if theme() == "neo":
            out.extend(neo_cabinet(screen, title))
        else:
            for y, x, text in frame_lines(screen, title):
                out.append(f"\x1b[{y + 1};{x + 1}H{text}")
            for y, x, text in side_runs(screen):
                out.append(f"\x1b[{y + 1};{x + 1}H{text}")
        out.append(f"\x1b[{screen.y + 1};{screen.x + 1}H")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def cabinet_edges(screen) -> str:
    """The cabinet's side edges and bottom as one escape string, in the active
    theme -- for curses games whose window refresh scrubs them and redraw them
    by hand. Classic output is the old double-line glyphs, unchanged."""
    if not getattr(screen, "framed", False):
        return ""
    style = "neo" if theme() == "neo" else "classic"
    pre = ""
    if style == "neo" and _tty():          # NO_COLOR keeps the glyphs, drops the colour
        pre = (f"\x1b[0;48;5;{NEO_SURFACE['bg']};38;5;{NEO_SURFACE['frame']}m" if _rich()
               else "\x1b[0;40;34m")
    out = [pre]
    for y, x, text in side_runs(screen, style=style):
        out.append(f"\x1b[{y + 1};{x + 1}H{text}")
    y, x, text = frame_lines(screen, style=style)[-1]
    out.append(f"\x1b[{y + 1};{x + 1}H{text}")
    if pre:
        out.append(RESET)
    return "".join(out)


def neo_cabinet(screen, title: str = "", right: str = "LAZSTATION 2") -> list[str]:
    """The neo cabinet as escape strings: the whole cabinet painted (so the
    picture never shows the terminal through it), thin rounded lines, a shaded
    title band with a blue power LED, the title in white and the brand in blue."""
    s, rich = NEO_SURFACE, _rich()
    if rich:
        line = f"\x1b[0;48;5;{s['bg']};38;5;{s['frame']}m"
        band = f"\x1b[48;5;{s['band']}m"
        led = f"\x1b[1;38;5;{s['accent']}m"
        name = f"\x1b[1;38;5;{s['title']}m"
        brand = f"\x1b[22;38;5;{s['accent']}m"
        pad = f"\x1b[48;5;{s['bg']}m"
    else:
        line, band, led, name, brand, pad = "\x1b[0;40;34m", "\x1b[40m", "\x1b[1;94m", "\x1b[1;97m", "\x1b[22;94m", "\x1b[40m"
    top, bar_row, sep, bottom = frame_lines(screen, title, right, style="neo")
    v = bar_row[2][0]
    bar = title_bar(screen, title, right)
    head, tail = bar[: len(bar) - len(right) - 1], bar[len(bar) - len(right) - 1:]
    ox, cab_w = screen.ox, screen.cab_w
    out = []
    for y, x, text in (top, sep, bottom):
        out.append(f"\x1b[{y + 1};{x + 1}H{line}{text}")
    y = bar_row[0]
    out.append(f"\x1b[{y + 1};{ox + 1}H{line}{v}{band}{led}{head[:2]}{name}{head[2:]}{brand}{tail}{line}{v}")
    for y in range(screen.oy + 3, screen.oy + screen.cab_h - 1):
        out.append(f"\x1b[{y + 1};{ox + 1}H{line}{v}{pad} ")
        out.append(f"\x1b[{y + 1};{ox + cab_w - 1}H{pad} {line}{v}")
    out.append(RESET)
    return out


def tv_clear(page: int = 0) -> None:
    """Wipe the picture but leave the cabinet standing.

    `page` is the height of the screen you are about to draw; give it and the
    page is centred vertically instead of hugging the top of the picture.
    """
    screen = _tv_state.get("screen")
    if not screen or not _tty():
        clear()
        return
    blank = " " * screen.width
    fill = surface()                       # neo paints the picture; classic leaves the terminal's
    out = []
    for i in range(screen.height):
        out.append(f"\x1b[{screen.y + i + 1};{screen.x + 1}H{fill}{blank}")
    if fill:
        out.append(RESET)
    out.append(f"\x1b[{screen.y + 1};{screen.x + 1}H")
    sys.stdout.write("".join(out))
    sys.stdout.flush()
    _tv_state["row"] = max(0, (screen.height - page) // 2) if page else 0


def _visible_len(text: str) -> int:
    """Length ignoring ANSI colour codes, so clipping counts real columns."""
    out, i = 0, 0
    while i < len(text):
        if text[i] == "\x1b":
            j = text.find("m", i)
            if j == -1:
                break
            i = j + 1
            continue
        out += 1
        i += 1
    return out


def _clip(text: str, width: int) -> str:
    """Cut to `width` visible columns, keeping colour codes intact.

    Counting escape bytes as if they were part of the budget (or not) both go
    wrong: the only reliable way is to walk the string and stop once enough
    printable columns have been emitted.
    """
    out, seen, i = [], 0, 0
    while i < len(text):
        if text[i] == "\x1b":
            j = text.find("m", i)
            if j == -1:
                break
            out.append(text[i:j + 1])
            i = j + 1
            continue
        if seen >= width:
            # Keep any trailing resets so colour does not leak onward.
            rest = text[i:]
            out.append("".join(
                rest[k:rest.find("m", k) + 1]
                for k in range(len(rest)) if rest[k] == "\x1b"))
            break
        out.append(text[i])
        seen += 1
        i += 1
    result = "".join(out)
    return result if result.endswith(RESET) or "\x1b" not in result else result + RESET


def tv_print(*parts: object, sep: str = " ") -> None:
    """print() that stays inside the picture tube.

    Wraps at the inner width and page-flips at the bottom instead of
    scrolling, which is what would otherwise drag the bezel off screen.
    """
    if not _tv_state["active"]:
        print(*parts, sep=sep)
        return
    screen = _tv_state["screen"]
    text = sep.join(str(p) for p in parts)
    for line in (text.split("\n") if text else [""]):
        if _tv_state["row"] >= screen.height - 1:
            tv_pause()
            tv_clear()
        if _visible_len(line) > _tv_state["stage"]:
            line = _clip(line, _tv_state["stage"])
        if _tty():
            col = screen.x + _tv_state["indent"] + 1
            sys.stdout.write(
                f"\x1b[{screen.y + _tv_state['row'] + 1};{col}H{surface()}{line}\x1b[0m")
        else:
            sys.stdout.write(line + "\n")
        _tv_state["row"] += 1
    sys.stdout.flush()


def tv_prompt(message: str, default: str = "") -> str:
    """prompt() positioned inside the picture, page-flipping when needed."""
    if not _tv_state["active"]:
        return prompt(message, default)
    return prompt(message, default)


def tv_pause(message: str = "press enter") -> None:
    pause(message)


def tv_curses(stdscr, title: str = ""):
    """Draw the cabinet on a curses screen; return a window for the picture.

    Call again after KEY_RESIZE to redraw at the new size.
    """
    import curses

    title = title or os.environ.get("TERMSTATION_NAME", "")
    rows, cols = stdscr.getmaxyx()
    screen = _geometry(cols, rows)
    stdscr.erase()

    def _put(y, x, text, attr=0):
        if 0 <= y < rows and x < cols:
            try:
                stdscr.addnstr(y, x, text, max(0, cols - x - (1 if y == rows - 1 else 0)),
                               attr)
            except curses.error:
                pass

    if screen.framed:
        attr = curses.A_BOLD
        style = "neo" if theme() == "neo" else "classic"
        title_attr = None
        if curses.has_colors():
            attr |= curses.color_pair(0)
            if style == "neo" and getattr(curses, "COLORS", 0) >= 256:
                # The top usable pairs: games allocate theirs from 1 upward.
                # Capped at 255 -- color_pair() packs the number into 8
                # attribute bits, so a higher pair wraps (it drew the cabinet
                # top black).
                try:
                    top = min(getattr(curses, "COLOR_PAIRS", 256) - 1, 255)
                    curses.init_pair(top, NEO_SURFACE["frame"], NEO_SURFACE["bg"])
                    curses.init_pair(top - 1, NEO_SURFACE["title"], NEO_SURFACE["band"])
                    attr = curses.color_pair(top)
                    title_attr = curses.color_pair(top - 1) | curses.A_BOLD
                except (curses.error, ValueError, OverflowError):
                    pass
        for y, x, text in frame_lines(screen, title, style=style):
            _put(y, x, text, attr)
        if title_attr is not None:             # neo: the shaded title band, in white
            _put(screen.oy + 1, screen.ox + 1, title_bar(screen, title), title_attr)
        for y, x, text in side_runs(screen, style=style):
            _put(y, x, text, attr)
    stdscr.noutrefresh()
    win = curses.newwin(screen.height, screen.width, screen.y, screen.x)
    win.keypad(True)
    return win, screen


__all__ += ["theme", "surface", "CLASSIC_THEMES", "cabinet_edges"]
__all__ += ["tv", "tv_print", "tv_clear", "tv_prompt", "tv_pause", "tv_curses",
            "tv_size"]


def tv_size() -> tuple[int, int]:
    """Inner picture size -- what a game should lay out against."""
    screen = _tv_state.get("screen") or _geometry()
    return screen.width, screen.height


# ---------------------------------------------------------------- real time

class Loop:
    """A fixed-timestep loop with held-key tracking, for action games.

    Terminals report key presses but never releases, so "is the player holding
    jump?" cannot be read directly. Every press refreshes a timestamp and a
    key counts as held for `hold` seconds afterwards -- long enough to bridge
    the gap between auto-repeats, short enough to feel like a release.
    """

    def __init__(self, win, fps: int = 30, hold: float = 0.14) -> None:
        import time as _time
        self.win = win
        self.dt = 1.0 / fps
        self.hold = hold
        self._time = _time
        self._pressed: dict[int, float] = {}
        self._fresh: set[int] = set()
        self._last = _time.monotonic()
        win.nodelay(True)
        win.keypad(True)

    def poll(self) -> set[int]:
        """Drain every key waiting this frame. Returns keys newly pressed."""
        now = self._time.monotonic()
        self._fresh = set()
        while True:
            key = self.win.getch()
            if key == -1:
                break
            self._fresh.add(key)
            self._pressed[key] = now
        return self._fresh

    def pressed(self, *keys: int) -> bool:
        """True only on the frame a key arrived -- for jumps, menus, firing."""
        return any(k in self._fresh for k in keys)

    def held(self, *keys: int) -> bool:
        """True while a key keeps repeating -- for walking, steering."""
        now = self._time.monotonic()
        return any(now - self._pressed.get(k, -99) < self.hold for k in keys)

    def release(self, *keys: int) -> None:
        """Forget a key, so one press cannot count twice."""
        for k in keys:
            self._pressed.pop(k, None)
            self._fresh.discard(k)

    def resume(self) -> None:
        """Restart the clock after a blocking screen (a menu, a pause).

        Without this the time spent blocked arrives as a single huge frame,
        and anything moving fast enough can pass straight through a wall.
        """
        self._last = self._time.monotonic()
        self._pressed.clear()
        self._fresh = set()

    def tick(self) -> float:
        """Sleep out the rest of the frame. Returns elapsed seconds."""
        now = self._time.monotonic()
        elapsed = now - self._last
        remaining = self.dt - elapsed
        if remaining > 0:
            self._time.sleep(remaining)
            elapsed = self.dt
        self._last = self._time.monotonic()
        return min(elapsed, self.dt * 2)


__all__ += ["Loop"]


# ---------------------------------------------------------------- slots

def slot() -> int:
    """Which save slot the console launched this game into (1 by default).

    Games rarely need this -- the launcher already points TERMSTATION_SAVE_DIR
    at the right folder -- but it is here for showing "Slot 2" in a menu.
    """
    try:
        return max(1, int(os.environ.get("TERMSTATION_SLOT", "1")))
    except ValueError:
        return 1


# ---------------------------------------------------------------- achievements

def _achievements_path() -> Path | None:
    raw = os.environ.get("TERMSTATION_ACHIEVEMENTS")
    return Path(raw) if raw else None


def achievements(slug: str | None = None) -> dict:
    """Everything unlocked so far, for this game unless told otherwise."""
    path = _achievements_path()
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if slug is None:
        slug = globals()["slug"]()
    return data.get(slug, {}) if slug else data


#: Awards unlocked but not yet shown, for games that draw their own screen.
_award_queue: list[dict] = []


def drain_awards() -> list[dict]:
    """Take the awards unlocked since this was last called.

    Line-based games need not bother -- unlock() announces those itself. A
    full-screen game owns every cell, so it drains this and draws the banner
    wherever it likes.
    """
    global _award_queue
    out, _award_queue = _award_queue, []
    return out


def _announce(title: str, description: str) -> None:
    line = f"  ★  {title}"
    if description:
        line += f" — {description}"
    width = min(size()[0], 78)
    bar = color("─" * width, "amber")
    for text in (bar, color(line, "bright_yellow", bold=True), bar):
        _out(text)


def unlock(key: str, title: str = "", description: str = "") -> bool:
    """Record an achievement. Returns True only the first time.

    A newly unlocked award announces itself: printed inline for a line-based
    game, or queued for a full-screen one to draw via drain_awards(). An
    award earned again stays silent.
    """
    path = _achievements_path()
    if path is None:
        return False
    mine = globals()["slug"]()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    game = data.setdefault(mine, {})
    if key in game:
        return False
    game[key] = {"title": title or key, "description": description,
                 "at": _now_iso()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return False

    record = {"key": key, "title": title or key, "description": description}
    if _tv_state.get("active"):
        _announce(record["title"], record["description"])
    else:
        _award_queue.append(record)
    return True


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


__all__ += ["slot", "unlock", "achievements", "drain_awards"]
