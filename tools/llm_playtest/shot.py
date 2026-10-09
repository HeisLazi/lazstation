"""Screenshot a program in a real PTY after typing a key sequence: a colour PNG
(vt_color) plus the plain text next to it (<out>.txt). For row-budget checks
("does this screen fit 66x24?") and before/after visual reviews.

usage: shot.py COLS ROWS KEYS OUT.png [--save DIR] [--cwd DIR] [--wait SECS] [-- CMD...]

  KEYS   comma-separated lines to type, each followed by Enter ("" = just Enter)
  CMD    defaults to Beastling: python3 main.py in games/beastling
"""
import argparse, fcntl, os, pty, select, struct, sys, termios, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import vt_color  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("cols", type=int)
ap.add_argument("rows", type=int)
ap.add_argument("keys")
ap.add_argument("out")
ap.add_argument("--save", default=None, help="TERMSTATION_SAVE_DIR for the program (default: a temp dir)")
ap.add_argument("--cwd", default=os.path.join(REPO, "games", "beastling"))
ap.add_argument("--wait", type=float, default=0.5, help="seconds to let output settle after each key")
argv = sys.argv[1:]
cmd = []
if "--" in argv:                       # everything after -- is the program to run
    cut = argv.index("--")
    argv, cmd = argv[:cut], argv[cut + 1:]
a = ap.parse_args(argv)
cmd = cmd or ["python3", "main.py"]
save = a.save
if save is None:
    import tempfile
    save = tempfile.mkdtemp(prefix="shot-save-")

pid, fd = pty.fork()
if pid == 0:
    env = dict(os.environ, PYTHONPATH=os.path.join(REPO, "sdk") + os.pathsep + REPO, TERM="xterm-256color",
               TERMSTATION_SAVE_DIR=save, COLUMNS=str(a.cols), LINES=str(a.rows))
    os.chdir(a.cwd)
    os.execvpe(cmd[0], cmd, env)
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", a.rows, a.cols, 0, 0))
raw = ""


def drain(t):
    global raw
    end = time.time() + t
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                c = os.read(fd, 65536)
            except OSError:
                return
            if not c:
                return
            raw += c.decode("utf-8", "replace")


drain(1.0)
for k in a.keys.split(",") if a.keys else []:
    os.write(fd, (k + "\n").encode())
    drain(a.wait)
cells = vt_color.render_cells(raw, a.cols, a.rows)
vt_color.to_png(cells, a.out)
with open(a.out.rsplit(".", 1)[0] + ".txt", "w") as f:
    f.write("\n".join("".join(row).rstrip() for row in cells[0]) + "\n")
try:
    os.kill(pid, 9)
except OSError:
    pass
print("wrote", a.out)
