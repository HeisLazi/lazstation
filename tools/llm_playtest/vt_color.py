"""Colour-aware companion to tools/vt.py: replays cursor/erase codes AND colour
(16/256/24-bit foreground and background, bold, reverse), then draws the screen
as a PNG -- so a vision model (or a person reviewing a change) sees what a
player actually sees: colour, contrast, alignment.

    cells = render_cells(raw_terminal_output, cols, rows)
    to_png(cells, "screen.png")
"""
import os
import re

from PIL import Image, ImageDraw, ImageFont

FONTS = [  # first that exists wins; regular, bold
    ("/usr/share/fonts/TTF/JetBrainsMonoNerdFontMono-Regular.ttf",
     "/usr/share/fonts/TTF/JetBrainsMonoNerdFontMono-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSansMono.ttf", "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"),
]
BG, DEFAULT_FG = (14, 17, 23), (205, 214, 224)
BASE16 = [(0, 0, 0), (205, 49, 49), (13, 188, 121), (229, 229, 16), (36, 114, 200), (188, 63, 188),
          (17, 168, 205), (229, 229, 229), (102, 102, 102), (241, 76, 76), (35, 209, 139), (245, 245, 67),
          (59, 142, 234), (214, 112, 214), (41, 184, 219), (255, 255, 255)]


def xterm256(n: int) -> tuple:
    if n < 16:
        return BASE16[n]
    if n < 232:
        n -= 16
        lv = [0, 95, 135, 175, 215, 255]
        return (lv[n // 36], lv[(n // 6) % 6], lv[n % 6])
    v = 8 + (n - 232) * 10
    return (v, v, v)


def _sgr(nums, state):
    """Apply one SGR (ESC[...m) parameter list to state = [fg, bg, bold, reverse]."""
    ns, k = nums or [0], 0
    while k < len(ns):
        v = ns[k]
        if v == 0:
            state[:] = [None, None, False, False]
        elif v == 1:
            state[2] = True
        elif v == 22:
            state[2] = False
        elif v == 7:
            state[3] = True
        elif v == 27:
            state[3] = False
        elif v == 39:
            state[0] = None
        elif v == 49:
            state[1] = None
        elif v in (38, 48) and k + 1 < len(ns):
            slot = 0 if v == 38 else 1
            if ns[k + 1] == 5 and k + 2 < len(ns):
                state[slot] = xterm256(ns[k + 2])
                k += 2
            elif ns[k + 1] == 2 and k + 4 < len(ns):
                state[slot] = (ns[k + 2], ns[k + 3], ns[k + 4])
                k += 4
        elif 30 <= v <= 37:
            state[0] = BASE16[v - 30]
        elif 90 <= v <= 97:
            state[0] = BASE16[v - 90 + 8]
        elif 40 <= v <= 47:
            state[1] = BASE16[v - 40]
        elif 100 <= v <= 107:
            state[1] = BASE16[v - 100 + 8]
        k += 1


def render_cells(data: str, cols: int, rows: int):
    """Returns (chars, fg, bg, bold) grids; colours are RGB tuples or None."""
    def blank():
        return ([[" "] * cols for _ in range(rows)], [[None] * cols for _ in range(rows)],
                [[None] * cols for _ in range(rows)], [[False] * cols for _ in range(rows)])
    ch, fg, bg, bd = blank()
    cy = cx = 0
    state = [None, None, False, False]
    i = 0
    while i < len(data):
        c = data[i]
        if c == "\x1b" and i + 1 < len(data) and data[i + 1] in "()#":
            i += 3
            continue
        if c == "\x1b" and i + 1 < len(data) and data[i + 1] in "=>":
            i += 2
            continue
        if c == "\x1b" and i + 1 < len(data) and data[i + 1] == "]":      # OSC: title etc.
            end = data.find("\x07", i)
            i = (end + 1) if end != -1 else len(data)
            continue
        if c == "\x1b" and i + 1 < len(data) and data[i + 1] == "[":
            m = re.match(r"\x1b\[([0-9;?]*)([A-Za-z])", data[i:])
            if not m:
                i += 1
                continue
            params, cmd = m.group(1), m.group(2)
            nums = [int(p) for p in params.split(";") if p.isdigit()]
            if cmd == "m":
                _sgr(nums, state)
            elif cmd in "Hf":
                cy = (nums[0] - 1) if nums else 0
                cx = (nums[1] - 1) if len(nums) > 1 else 0
            elif cmd == "J":
                if not nums or nums[0] in (2, 3):
                    ch, fg, bg, bd = blank()
            elif cmd == "A":
                cy = max(0, cy - (nums[0] if nums else 1))
            elif cmd == "B":
                cy = min(rows - 1, cy + (nums[0] if nums else 1))
            elif cmd == "C":
                cx = min(cols - 1, cx + (nums[0] if nums else 1))
            elif cmd == "D":
                cx = max(0, cx - (nums[0] if nums else 1))
            elif cmd == "G":
                cx = max(0, (nums[0] - 1) if nums else 0)
            elif cmd == "d":                       # vertical position absolute (curses uses it)
                cy = max(0, (nums[0] - 1) if nums else 0)
            elif cmd == "X" and 0 <= cy < rows:    # erase N characters, cursor stays
                for x in range(cx, min(cols, cx + (nums[0] if nums else 1))):
                    ch[cy][x], fg[cy][x], bg[cy][x], bd[cy][x] = " ", None, state[1], False
            elif cmd == "K" and 0 <= cy < rows:
                for x in range(cx, cols):          # erase paints the current background
                    ch[cy][x], fg[cy][x], bg[cy][x], bd[cy][x] = " ", None, state[1], False
            i += m.end()
            continue
        if c == "\n":
            cy, cx = cy + 1, 0
            i += 1
            continue
        if c == "\r":
            cx = 0
            i += 1
            continue
        if c == "\x08":                            # backspace: curses moves left with it
            cx = max(0, cx - 1)
            i += 1
            continue
        if c == "\t":
            cx = min(cols - 1, (cx // 8 + 1) * 8)
            i += 1
            continue
        if 0 <= cy < rows and 0 <= cx < cols and c.isprintable():
            f, b = state[0], state[1]
            if state[3]:
                f, b = (b or BG), (f or DEFAULT_FG)
            ch[cy][cx], fg[cy][cx], bg[cy][cx], bd[cy][cx] = c, f, b, state[2]
        cx += 1
        if cx >= cols:
            cx, cy = 0, cy + 1
        i += 1
    return ch, fg, bg, bd


def _fonts(size: int):
    for reg, bold in FONTS:
        if os.path.exists(reg):
            return ImageFont.truetype(reg, size), ImageFont.truetype(bold if os.path.exists(bold) else reg, size)
    f = ImageFont.load_default()
    return f, f


def to_png(cells, path: str, size: int = 18) -> str:
    ch, fg, bg, bd = cells
    rows, cols = len(ch), len(ch[0])
    f, fb = _fonts(size)
    cw = int(f.getlength("M")) or 10
    chh = int(size * 1.35)
    img = Image.new("RGB", (cols * cw + 20, rows * chh + 20), BG)
    d = ImageDraw.Draw(img)
    for y in range(rows):
        for x in range(cols):
            if bg[y][x] is not None:
                d.rectangle([10 + x * cw, 10 + y * chh, 10 + (x + 1) * cw - 1, 10 + (y + 1) * chh - 1],
                            fill=bg[y][x])
            c = ch[y][x]
            if c != " ":
                d.text((10 + x * cw, 10 + y * chh), c, font=fb if bd[y][x] else f,
                       fill=fg[y][x] or DEFAULT_FG)
    img.save(path)
    return path
