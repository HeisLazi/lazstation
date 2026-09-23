# LAZSTATION 2

A console for terminal games. Boot it, browse your library, pick a game —
it loads inside a CRT cabinet on your terminal.

```
lazstation
```

## Install

```bash
git clone <this repo> ~/projects/termstation
cd ~/projects/termstation
./install.sh        # links `lazstation` and `laz` into ~/.local/bin
```

Python 3.11+ and a terminal. No dependencies.

**WSL:** WSL has its own home directory, so if you want `lazstation` there
too, clone the repo inside WSL and run `./install.sh` again from that shell.
The install is just a symlink into `~/.local/bin`, so doing it in both places
is harmless.

## Using it

| command | what it does |
| --- | --- |
| `lazstation` | open the console |
| `lazstation play <slug>` | launch a game straight away |
| `lazstation new <name>` | scaffold a new game |
| `lazstation new <name> --curses` | scaffold a full-screen game |
| `lazstation list` | list installed games |
| `lazstation info <slug>` | where a game's files, saves and logs live |
| `lazstation doctor` | check the install and every manifest |

In the console: `↑↓`/`jk` move, `enter` plays, `/` filters, `p` switches save
profile, `b` toggles the boot animation, `r` rescans, `?` help, `q` powers off.

## Making a game

```bash
lazstation new pokemon
$EDITOR games/pokemon/main.py
lazstation play pokemon
```

That is the whole loop. A game is **a folder with a `game.toml`** — drop one in
`games/` (or `~/.local/share/termstation/games/`) and press `r` in the console.

```toml
[game]
name = "Pokemon"
slug = "pokemon"
description = "Shown on the console."
tags = ["rpg"]
entry = ["{python}", "main.py"]   # or any argv: a shell script, a binary
min_cols = 70                     # warn if the picture is smaller than this
min_rows = 20
```

### The contract

Games are launched as **separate processes** with the terminal handed over
completely. A game that crashes, hangs or leaves the terminal in a strange
state cannot harm the console. Everything is passed as environment variables:

| variable | meaning |
| --- | --- |
| `TERMSTATION` | `1` when launched from the console |
| `TERMSTATION_SAVE_DIR` | this game's save folder, already created |
| `TERMSTATION_SHARED_DIR` | shared across games for the current profile |
| `TERMSTATION_PROFILE` | active save profile |
| `TERMSTATION_DATA_DIR` | the game's own folder, for assets |
| `TERMSTATION_NAME` / `_SLUG` | what the console calls this game |

**Every one of these is optional.** A forty-line script that only calls
`input()` and `print()` works on day one. Exit `0` for a clean finish;
anything else is reported as a crash and the stderr log is kept.

### The SDK

`import termstation_sdk as ts` — optional conveniences, never required.

```python
import termstation_sdk as ts

ts.tv("My Game")                      # draw the CRT cabinet
save = ts.load({"gold": 0})           # read this game's save
save["gold"] += 10
ts.save(save)                         # atomic write

ts.tv_print(ts.title("MY GAME"))      # print inside the picture
ts.tv_print(ts.box(["a panel"]))
name = ts.prompt("your name")         # input, echoed inside the frame
n = ts.ask_int("how many", 1, 10)
if ts.confirm("sure?"): ...
pick = ts.menu("Choose", ["Fight", "Run"])
```

For full-screen games:

```python
win, screen = ts.tv_curses(stdscr, "My Game")   # window inset in the bezel
win.addstr(1, 2, "hello")                       # draw into `win`
```

`ts.size()` returns the **picture** size, so `box()`, `title()` and `rule()`
fit the cabinet automatically. Call `tv_curses` again on `KEY_RESIZE`.

### Why the bezel works this way

The frame is *cooperative*: games draw it themselves through the SDK rather
than the launcher drawing it around them. Erase-display (`\x1b[2J`) ignores
terminal scroll margins, so any frame the parent painted would be wiped the
moment a curses game cleared the screen. Instead the launcher and the SDK
share one geometry module (`sdk/termstation_bezel.py`), so the cabinet the
boot screen draws and the cabinet the game draws land on the same cells and
the picture changes without the frame blinking.

The cabinet is capped at 100x34 and centred, rather than stretched across the
whole terminal — a screen stretched over an ultrawide window leaves the
picture stranded in a corner. Game output sits on a centred "stage" no wider
than 78 columns for the same reason, and `ts.tv_clear(page=N)` centres a page
of N lines vertically.

A game that ignores the bezel simply runs full screen.

## Where things live

```
games/<slug>/            a game (code + game.toml)
sdk/                     termstation_sdk, on PYTHONPATH for every game
~/.local/share/termstation/saves/<profile>/<slug>/    save data
~/.local/state/termstation/logs/<slug>.log            last run's stderr
~/.local/state/termstation/library.json               playtime and stats
```

Save data lives outside the game folder on purpose: you can delete, move or
re-clone a game without losing progress.

## Included

- **Blackjack** — six decks, split/double/insurance, chips shared across games.
- **Gladiator** — full-screen arena combat, stamina and crowd favour.
