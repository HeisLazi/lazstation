"""Run a game in a real PTY of a given size, send keys, render the screen."""
import fcntl, os, pty, select, struct, sys, termios, time

def run(argv, cols, rows, keys, settle=0.45, env=None):
    pid, fd = pty.fork()
    if pid == 0:
        e = dict(os.environ); e.update(env or {})
        e["TERM"] = "xterm-256color"; e["LINES"] = str(rows); e["COLUMNS"] = str(cols)
        os.execvpe(argv[0], argv, e)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    out = b""
    def drain(t=0.5):
        nonlocal out
        end = time.time() + t
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.08)
            if r:
                try: chunk = os.read(fd, 65536)
                except OSError: return False
                if not chunk: return False
                out += chunk
        return True
    drain(settle)
    for k in keys:
        try: os.write(fd, k.encode())
        except OSError: break
        if not drain(settle): break
    try: os.close(fd)
    except OSError: pass
    try: os.waitpid(pid, os.WNOHANG)
    except ChildProcessError: pass
    return out.decode("utf-8", "replace")

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    from vt import render
    cols, rows = int(sys.argv[1]), int(sys.argv[2])
    keys = sys.argv[3] if len(sys.argv) > 3 else ""
    data = run(["python3", "main.py"], cols, rows, list(keys))
    print(render(data, cols, rows))
