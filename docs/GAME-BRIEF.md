# Brief: writing a game for LAZSTATION 2

Read this before writing any game for this console. It is the whole contract.

## Where things are

```
~/Projects/personal/heisprojects/termstation/
  games/<slug>/game.toml   the manifest the console reads
  games/<slug>/main.py     your game
  games/<slug>/*.py        your data files
  sdk/termstation_sdk.py   helpers (already on PYTHONPATH when launched)
  sdk/termstation_ui.py   optional curses layout and navigation widgets
  docs/GAME-BRIEF.md       this file
```

Start a game with `lazstation new <name>` (line-based) or
`lazstation new <name> --curses` (full-screen). It writes a working game you
then replace. Run it with `lazstation play <slug>`, or `lazstation` for the
console. `lazstation doctor` validates every manifest.

## Rules that are not negotiable

1. **When writing a game, keep changes inside its own folder.** Do not edit
   `sdk/`, `termstation/`, `bin/`, `tools/`, `install.sh`, or another game as
   part of game work. If a platform feature is missing, ask for that platform
   change separately or implement a local helper inside your game folder.

2. **Content goes in data files, rules go in `main.py`.** Species tables, map
   art, dialogue, item stats, squad data — put them in a separate module in
   your game folder with a comment saying how to edit them. The owner directs
   this project by editing data; a game that hardcodes its content is a game
   he cannot redirect. See `games/beastling/beasts.py` and
   `games/emberlight/world.py` for the pattern.

3. **Budget your rows before writing `draw()`.** At an 80x24 terminal the
   playable picture is **76 wide by 20 tall**. Count the rows your screen
   needs and make them fit; do not discover it afterwards. Curses games can
   grow to 96x30 on a large terminal, so lay out against the minimum and let
   the extra space go to the viewport. Never hardcode 76.

4. **Draw inside the bezel.** Line-based: call `ts.tv("Name")` once, then use
   `ts.tv_print()` instead of `print()` and `ts.tv_clear(page=N)` to wipe
   (N = how many rows your screen uses; it centres the page vertically).
   Full-screen: `win, screen = ts.tv_curses(stdscr, "Name")` and draw into
   `win`, using `screen.width` / `screen.height`. Call it again on
   `KEY_RESIZE`. After any full-screen banner, call `win.clear()` — `erase()`
   can leave the previous screen's text behind.

5. **Saves must survive you editing the game.** `ts.load(defaults)` merges the
   defaults into whatever was stored, so add fields freely — but never assume
   a key exists that you added later, and keep a `version` int in the save.

6. **Exit 0 on a clean finish, 130 on Ctrl-C.** Anything else is reported to
   the player as a crash. Wrap `main()` in try/except KeyboardInterrupt.

7. **Original content only.** Genre-faithful systems are the goal; names,
   characters and worlds must be your own, not lifted from the games these are
   inspired by.

## The SDK, briefly

```python
import termstation_sdk as ts

ts.tv("My Game")                     # draw the CRT cabinet
save = ts.load({"gold": 0})          # merged with what was stored
ts.save(save)                        # atomic write
ts.tv_print(ts.title("MY GAME"))     # print inside the picture
ts.tv_print(ts.box(["a panel"]))     # box/title/rule fit the stage
n   = ts.ask_int("how many", 1, 10)  # validated input
pick= ts.menu("Choose", ["Fight", "Run"])   # numbered menu, -1 = back
ok  = ts.confirm("sure?")
ts.tv_pause()
ts.size()                            # usable width/height
loop = ts.Loop(win, fps=30)          # real-time: poll/pressed/held/tick/resume
```

For curses games, `termstation_ui` provides optional layout and navigation
primitives without taking ownership of the game's state or visual theme:

```python
import termstation_ui as ui

body = ui.Rect(0, 0, screen.width, screen.height - 1)
left, right = ui.split_horizontal(body, ratio=0.62, gap=1)
ui.draw_panel(win, left, "Squad", attr=border_attr)
roster = ui.TableView(["Name", "POS", "FIT"], rows)
roster.draw(win, left.inset(), selected_attr=focus_attr)
index = roster.handle(win.getch(), left.height)
```

`Rect` uses window-local cells; the split helpers reserve an explicit gap.
`draw_text`, `draw_rule`, and `draw_panel` clip writes to the window. `wrap_text`
wraps prose. `ListView` and `TableView` keep a visible selection while scrolling;
`Tabs` keeps the selected tab visible on narrow screens. `ListView.handle()`
and `TableView.handle()` return a selected index on Enter, `-1` on Esc/`q`, or
`None` while navigation continues; `Tabs.handle()` returns whether it changed
the selected tab. Arrow keys and `h/j/k/l` are supported, with Home/End and
Page Up/Down for lists and tables. `key_action()` exposes the shared key
mapping. These widgets assume one terminal cell per character; games remain
responsible for calling `ts.tv_curses()` again after `KEY_RESIZE` and redrawing
their own screen.

`ts.Loop` exists because terminals report key presses but never releases. A
key counts as held for a short window after each press. Anything real-time
must also **sub-step its collision** — one slow frame can otherwise move an
entity clean through a wall.

## How to verify (required before you say it works)

There is no interactive terminal here, so render the game in a pseudo-terminal
and read the screen. Helpers already exist:

```
tools/ptytest.py   run a game in a PTY, replay frames, and assert a path
tools/vt.py        replay the output onto a grid as plain text
```

```bash
cd games/<slug>
TERMSTATION=1 TERMSTATION_NAME="My Game" TERMSTATION_SAVE_DIR=/tmp/t \
  PYTHONPATH=../../sdk python3 ../../tools/ptytest.py 80 24 $'\nddd'
```

For repeatable paths, put named input and frame assertions in a JSON scenario.
Events run in order. `key` sends one named key, `keys` sends a sequence,
`text` sends literal UTF-8 input, `wait` drains output, `resize` changes the
pseudo-terminal dimensions, and `snapshot` saves the rendered frame so far.
Supported key names include `ENTER`, `ESC`, arrows, `HOME`, `END`, `PAGE_UP`,
`PAGE_DOWN`, `F1`–`F12`, `CTRL_C`, and single characters. A compact example:

```json
{
  "wait_before": 0.2,
  "timeout": 10,
  "expect_exit": true,
  "events": [
    {"type": "snapshot", "name": "start"},
    {"type": "key", "key": "ENTER"},
    {"type": "key", "key": "DOWN"},
    {"type": "key", "key": "ENTER"},
    {"type": "snapshot", "name": "encounter"}
  ],
  "assertions": {
    "exit_code": 0,
    "frames": {"start": {"contains": ["New Game"]}},
    "output_contains": ["Victory"]
  }
}
```

Run it from the game directory with
`python3 ../../tools/ptytest.py 80 24 --script path/to/scenario.json`;
use `--command "python3 main.py"` to override the child command and
`--artifacts /tmp/frames` to write named snapshots as text files. Scenarios
fail on timeout, an unexpected exit status, or a failed output/frame check.
The original positional raw-key form remains available for quick inspection.

They replay what the program sent and accumulate frames, so a moving sprite
leaves a trail that is not on a real terminal. Judge layout and borders from
them, not motion.

Check, at minimum:
- the game renders correctly at **80x24** and at a wide size such as **110x30**
- the borders are intact and nothing writes outside the frame
- a real path through the game works (a battle fought, a match played)
- `lazstation doctor` passes

Verify the game's *rules* headlessly too — import the module and assert on the
maths (damage, progression, table positions). That catches what a screenshot
cannot.

## Commit when done

The repo is git. Commit your own game folder only:

```
git add games/<slug> && git commit
```
