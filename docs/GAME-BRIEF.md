# Brief: writing a game for LAZSTATION 2

Read this before writing any game for this console. It is the whole contract.

## Where things are

```
~/Projects/personal/heisprojects/termstation/
  games/<slug>/game.toml   the manifest the console reads
  games/<slug>/main.py     your game
  games/<slug>/*.py        your data files
  sdk/termstation_sdk.py   helpers (already on PYTHONPATH when launched)
  docs/GAME-BRIEF.md       this file
```

Start a game with `lazstation new <name>` (line-based) or
`lazstation new <name> --curses` (full-screen). It writes a working game you
then replace. Run it with `lazstation play <slug>`, or `lazstation` for the
console. `lazstation doctor` validates every manifest.

## Rules that are not negotiable

1. **Do not edit `sdk/`, `termstation/`, `bin/`, `install.sh`, or any game you
   were not asked to write.** Another agent is working in those files. If you
   need something the SDK lacks, write it inside your own game folder.

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

`ts.Loop` exists because terminals report key presses but never releases. A
key counts as held for a short window after each press. Anything real-time
must also **sub-step its collision** — one slow frame can otherwise move an
entity clean through a wall.

## How to verify (required before you say it works)

There is no interactive terminal here, so render the game in a pseudo-terminal
and read the screen. Helpers already exist:

```
tools/ptytest.py   run a game in a PTY of a given size, send keystrokes
tools/vt.py        replay the output onto a grid as plain text
```

```bash
cd games/<slug>
TERMSTATION=1 TERMSTATION_NAME="My Game" TERMSTATION_SAVE_DIR=/tmp/t \
  PYTHONPATH=../../sdk python3 ../../tools/ptytest.py 80 24 $'\nddd'
```

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
