# Test helpers

There is no interactive terminal in an agent session, so these render a game
into plain text you can read.

    vt.py        replays terminal output (cursor moves, erases, colour) onto a grid
    ptytest.py   runs a command in a PTY of a given size, sends keystrokes, returns output

Render a game at 80x24, pressing enter then three 'd's:

    cd games/<slug>
    TERMSTATION=1 TERMSTATION_NAME="My Game" TERMSTATION_SAVE_DIR=/tmp/t \
      PYTHONPATH=../../sdk python3 ../../tools/ptytest.py 80 24 $'\nddd'

Note: these replay what the program *sent*, accumulating frames, so a moving
sprite can leave a trail in the output that is not present on a real terminal.
Judge layout and borders from it, not motion blur.

## Known limits of the replay

`vt.py` is a partial terminal, not a real one. It handles cursor movement,
erase, ECH/DCH/ICH/IL/DL, REP and colour, which is enough to judge layout —
but ncurses emits heavily optimised output and the replay can occasionally
show a stray character where the program actually wrote a space.

When something looks wrong in one cell, check the source of truth before
chasing it: compose the frame and read the canvas directly, or blit into a
recording window and inspect what was written. Both are exact:

    canvas = console.compose(76, 20)
    print("".join(canvas.ch[11*76:12*76]))     # what will be drawn
