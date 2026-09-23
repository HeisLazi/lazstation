"""termstation_fx -- colour, canvas, lighting, particles and transitions.

Additive: nothing here changes the existing SDK. Import it when a game wants
more than text.

    import termstation_fx as fx

    canvas = fx.Canvas(screen.width, screen.height)
    canvas.text(2, 1, "hello", fx.rgb(255, 180, 80))
    canvas.blit(win, palette)

Design notes
  * A Canvas is an off-screen buffer of cells. Games draw into it and blit
    once, so a frame never half-renders and effects can post-process the
    whole picture (lighting, shake, dissolve) before it reaches the terminal.
  * Colours are xterm-256 indices. Terminals vary, so everything degrades:
    with 8 colours the palette folds 256 down to the nearest basic colour.
  * Light is a separate per-cell channel, applied at blit time. That keeps
    "what is here" and "how lit is it" independent, which is what makes a
    torch look like a torch instead of a recolour.
"""
from __future__ import annotations

import math
import random

# ---------------------------------------------------------------- colour

#: The six levels the xterm colour cube samples on each axis.
_CUBE = (0, 95, 135, 175, 215, 255)


def _nearest_cube(v: int) -> int:
    best, bi = 1e9, 0
    for i, level in enumerate(_CUBE):
        d = abs(level - v)
        if d < best:
            best, bi = d, i
    return bi


def rgb(r: int, g: int, b: int) -> int:
    """Nearest xterm-256 index for an RGB colour."""
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    # Greys are better served by the 24-step ramp than by the cube.
    if abs(r - g) < 11 and abs(g - b) < 11 and abs(r - b) < 11:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + min(23, (r - 8) // 10)
    return 16 + 36 * _nearest_cube(r) + 6 * _nearest_cube(g) + _nearest_cube(b)


def to_rgb(color: int) -> tuple[int, int, int]:
    """Inverse of rgb(), for colours in the cube or grey ramp."""
    if color >= 232:
        v = 8 + 10 * (color - 232)
        return v, v, v
    if color >= 16:
        c = color - 16
        return _CUBE[c // 36], _CUBE[(c // 6) % 6], _CUBE[c % 6]
    base = [(0, 0, 0), (170, 0, 0), (0, 170, 0), (170, 85, 0), (0, 0, 170),
            (170, 0, 170), (0, 170, 170), (170, 170, 170), (85, 85, 85),
            (255, 85, 85), (85, 255, 85), (255, 255, 85), (85, 85, 255),
            (255, 85, 255), (85, 255, 255), (255, 255, 255)]
    return base[color % 16]


_scale_cache: dict[tuple[int, int], int] = {}


def scale(color: int, amount: float) -> int:
    """Brighten (>1) or dim (<1) a colour. Cached: this runs per cell."""
    key = (color, int(amount * 32))
    hit = _scale_cache.get(key)
    if hit is not None:
        return hit
    r, g, b = to_rgb(color)
    out = rgb(int(r * amount), int(g * amount), int(b * amount))
    _scale_cache[key] = out
    return out


def mix(a: int, b: int, t: float) -> int:
    """Blend two colours; t=0 gives a, t=1 gives b."""
    ar, ag, ab = to_rgb(a)
    br, bg, bb = to_rgb(b)
    return rgb(int(ar + (br - ar) * t), int(ag + (bg - ag) * t),
               int(ab + (bb - ab) * t))


# A few named colours so games are not full of magic numbers.
WHITE, BLACK = 231, 16
EMBER = rgb(255, 140, 40)
FLAME = rgb(255, 210, 90)
BLOOD = rgb(190, 40, 40)
STONE = rgb(140, 140, 150)
MOSS = rgb(90, 150, 80)
WATER = rgb(60, 120, 210)
GOLD = rgb(240, 200, 80)
SHADOW = rgb(40, 40, 60)
PAPER = rgb(236, 226, 205)   # warm off-white, easy on a dark terminal
INK = rgb(120, 112, 100)     # muted text
AMBER = rgb(255, 176, 64)    # the retro accent


# ---------------------------------------------------------------- palette

class Palette:
    """Allocates curses colour pairs on demand.

    Terminals cap how many pairs exist. When the pool runs out this returns
    the closest pair already allocated rather than raising -- a particle-heavy
    frame must never be the thing that crashes a game.
    """

    def __init__(self, curses_mod) -> None:
        self.curses = curses_mod
        self.pairs: dict[tuple[int, int], int] = {}
        self.next = 1
        self.enabled = False
        self.colors = 8
        self.limit = 1

        if not curses_mod.has_colors():
            return
        curses_mod.start_color()
        try:
            curses_mod.use_default_colors()
        except curses_mod.error:
            pass
        self.enabled = True
        self.colors = getattr(curses_mod, "COLORS", 8)
        self.limit = max(1, min(getattr(curses_mod, "COLOR_PAIRS", 64) - 1, 4000))

    def _fold(self, color: int) -> int:
        """Map a 256-colour index onto what this terminal actually has."""
        if color < self.colors:
            return color
        if self.colors >= 256:
            return color % 256
        r, g, b = to_rgb(color)
        bright = (r + g + b) / 3 > 128
        base = ((1 if r > 100 else 0) | (2 if g > 100 else 0) | (4 if b > 100 else 0))
        basic = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7}[base]
        if basic == 0 and bright:
            basic = 7
        return basic + 8 if (bright and self.colors >= 16) else basic

    def pair(self, fg: int, bg: int = -1) -> int:
        """A curses attribute for this colour combination."""
        if not self.enabled:
            return 0
        fg = self._fold(fg)
        bg = bg if bg < 0 else self._fold(bg)
        key = (fg, bg)
        got = self.pairs.get(key)
        if got is None:
            if self.next > self.limit:
                # Out of pairs: reuse the nearest thing we already have.
                return self.curses.color_pair(next(iter(self.pairs.values()), 0))
            try:
                self.curses.init_pair(self.next, fg, bg)
            except self.curses.error:
                return 0
            got = self.next
            self.pairs[key] = got
            self.next += 1
        return self.curses.color_pair(got)


# ---------------------------------------------------------------- canvas

class Canvas:
    """An off-screen grid of cells: glyph, foreground, background, light."""

    __slots__ = ("w", "h", "ch", "fg", "bg", "lit", "ambient")

    def __init__(self, w: int, h: int, ambient: float = 1.0) -> None:
        self.w, self.h = w, h
        self.ambient = ambient
        self.clear()

    def clear(self, glyph: str = " ", fg: int = WHITE, bg: int = -1) -> None:
        n = self.w * self.h
        self.ch = [glyph] * n
        self.fg = [fg] * n
        self.bg = [bg] * n
        self.lit = [self.ambient] * n

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def put(self, x: int, y: int, glyph: str, fg: int = WHITE, bg: int = -1) -> None:
        if not self.inside(x, y):
            return
        i = y * self.w + x
        self.ch[i] = glyph
        self.fg[i] = fg
        self.bg[i] = bg

    def text(self, x: int, y: int, s: str, fg: int = WHITE, bg: int = -1) -> None:
        for n, glyph in enumerate(s):
            self.put(x + n, y, glyph, fg, bg)

    def fill(self, x: int, y: int, w: int, h: int, glyph: str = " ",
             fg: int = WHITE, bg: int = -1) -> None:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.put(xx, yy, glyph, fg, bg)

    def box(self, x: int, y: int, w: int, h: int, fg: int = STONE,
            bg: int = -1, fill: bool = False) -> None:
        if fill:
            self.fill(x + 1, y + 1, w - 2, h - 2, " ", fg, bg)
        for xx in range(x + 1, x + w - 1):
            self.put(xx, y, "─", fg, bg)
            self.put(xx, y + h - 1, "─", fg, bg)
        for yy in range(y + 1, y + h - 1):
            self.put(x, yy, "│", fg, bg)
            self.put(x + w - 1, yy, "│", fg, bg)
        self.put(x, y, "┌", fg, bg)
        self.put(x + w - 1, y, "┐", fg, bg)
        self.put(x, y + h - 1, "└", fg, bg)
        self.put(x + w - 1, y + h - 1, "┘", fg, bg)

    # --- light
    def darken(self, level: float = 0.0) -> None:
        """Set every cell's light, ready for lights to add to it."""
        self.lit = [level] * (self.w * self.h)

    def add_light(self, cx: int, cy: int, radius: float, power: float = 1.0,
                  squash: float = 0.5) -> None:
        """A light source falling off with distance.

        `squash` accounts for character cells being about twice as tall as
        they are wide -- without it a round light looks like a tall oval.
        """
        r = int(radius) + 1
        for y in range(max(0, cy - r), min(self.h, cy + r + 1)):
            for x in range(max(0, cx - r * 2), min(self.w, cx + r * 2 + 1)):
                dx = (x - cx) * squash
                dy = y - cy
                d = math.sqrt(dx * dx + dy * dy)
                if d > radius:
                    continue
                i = y * self.w + x
                self.lit[i] = min(1.6, self.lit[i] + power * (1.0 - d / radius))

    # --- output
    def blit(self, win, palette: Palette, ox: int = 0, oy: int = 0,
             shake: tuple[int, int] = (0, 0)) -> None:
        """Draw into a curses window at (ox, oy). Light is applied here.

        Fills exactly the rectangle the canvas occupies -- every cell of it,
        blanks included -- and never a cell outside. `shake` displaces the
        *content* within that rectangle rather than the rectangle itself, so
        a shaking game cannot scrub the bezel drawn around it.
        """
        h, w = win.getmaxyx()
        sx, sy = shake
        blank = palette.pair(WHITE, -1)
        for row in range(self.h):
            ty = oy + row
            if ty < 0 or ty >= h:
                continue
            for col in range(self.w):
                tx = ox + col
                if tx < 0 or tx >= w - 1:
                    continue
                x, y = col - sx, row - sy
                if 0 <= x < self.w and 0 <= y < self.h:
                    i = y * self.w + x
                    glyph = self.ch[i]
                    light = self.lit[i]
                    fg = (self.fg[i] if light >= 0.99
                          else scale(self.fg[i], max(0.05, light)))
                    attr = palette.pair(fg, self.bg[i])
                else:
                    glyph, attr = " ", blank
                try:
                    win.addstr(ty, tx, glyph, attr)
                except Exception:
                    pass

    def to_ansi(self, ox: int = 1, oy: int = 1) -> str:
        """Render to an escape-sequence string, for use outside curses."""
        out = []
        for y in range(self.h):
            out.append(f"\x1b[{oy + y};{ox}H")
            last = None
            for x in range(self.w):
                i = y * self.w + x
                light = self.lit[i]
                fg = self.fg[i] if light >= 0.99 else scale(self.fg[i], max(0.05, light))
                if fg != last:
                    out.append(f"\x1b[38;5;{fg}m")
                    last = fg
                out.append(self.ch[i])
            out.append("\x1b[0m")
        return "".join(out)


# ---------------------------------------------------------------- easing

def linear(t: float) -> float:
    return t


def ease_in(t: float) -> float:
    return t * t


def ease_out(t: float) -> float:
    return 1 - (1 - t) * (1 - t)


def ease_in_out(t: float) -> float:
    return 2 * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 2) / 2


def bounce(t: float) -> float:
    if t < 0.36:
        return 7.5625 * t * t
    if t < 0.73:
        t -= 0.545
        return 7.5625 * t * t + 0.75
    if t < 0.91:
        t -= 0.82
        return 7.5625 * t * t + 0.9375
    t -= 0.955
    return 7.5625 * t * t + 0.984


def elastic(t: float) -> float:
    if t in (0.0, 1.0):
        return t
    return -(2 ** (10 * t - 10)) * math.sin((t * 10 - 10.75) * (2 * math.pi / 3))


class Tween:
    """A value moving from a to b over a duration."""

    def __init__(self, a: float, b: float, seconds: float, curve=ease_out) -> None:
        self.a, self.b, self.seconds, self.curve = a, b, max(1e-6, seconds), curve
        self.t = 0.0

    @property
    def done(self) -> bool:
        return self.t >= self.seconds

    @property
    def value(self) -> float:
        p = min(1.0, self.t / self.seconds)
        return self.a + (self.b - self.a) * self.curve(p)

    def update(self, dt: float) -> float:
        self.t += dt
        return self.value


# ---------------------------------------------------------------- shake

class Shake:
    """Screen shake. Kick it on impact; read the offset when you blit."""

    def __init__(self) -> None:
        self.power = 0.0

    def kick(self, power: float = 2.0) -> None:
        self.power = max(self.power, power)

    def update(self, dt: float) -> tuple[int, int]:
        if self.power <= 0.05:
            self.power = 0.0
            return 0, 0
        self.power = max(0.0, self.power - dt * 12.0)
        p = self.power
        return (random.randint(-1, 1) if p > 0.6 else 0,
                random.randint(-1, 1) if p > 1.4 else 0)


# ---------------------------------------------------------------- particles

class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "glyphs", "color",
                 "fade", "gravity")

    def __init__(self, x, y, vx, vy, life, glyphs, color, fade=True, gravity=0.0):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.life = self.max_life = life
        self.glyphs = glyphs
        self.color = color
        self.fade = fade
        self.gravity = gravity


class Particles:
    """A small particle system. Draw it after the world, before the UI."""

    def __init__(self) -> None:
        self.items: list[Particle] = []

    def __len__(self) -> int:
        return len(self.items)

    def emit(self, x: float, y: float, count: int = 8, *, speed: float = 8.0,
             life: float = 0.5, glyphs: str = "·∙*", color: int = FLAME,
             spread: float = math.pi * 2, angle: float = 0.0,
             gravity: float = 0.0) -> None:
        for _ in range(count):
            a = angle + random.uniform(-spread / 2, spread / 2)
            s = speed * random.uniform(0.4, 1.0)
            self.items.append(Particle(
                x, y, math.cos(a) * s, math.sin(a) * s * 0.5,
                life * random.uniform(0.6, 1.0), glyphs, color, gravity=gravity))

    def burst(self, x: float, y: float, color: int = FLAME) -> None:
        self.emit(x, y, 14, speed=14, life=0.45, glyphs="*∙·", color=color)

    def update(self, dt: float) -> None:
        alive = []
        for p in self.items:
            p.life -= dt
            if p.life <= 0:
                continue
            p.vy += p.gravity * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            alive.append(p)
        self.items = alive

    def draw(self, canvas: Canvas) -> None:
        for p in self.items:
            x, y = int(p.x), int(p.y)
            if not canvas.inside(x, y):
                continue
            frac = p.life / p.max_life
            glyph = p.glyphs[min(len(p.glyphs) - 1,
                                 int((1 - frac) * len(p.glyphs)))]
            color = scale(p.color, 0.35 + 0.65 * frac) if p.fade else p.color
            canvas.put(x, y, glyph, color)


# ---------------------------------------------------------------- transitions

_DITHER = " ░▒▓█"


def dissolve(a: Canvas, b: Canvas, t: float, seed: int = 7) -> Canvas:
    """Blend one canvas into another with a stable random threshold."""
    out = Canvas(a.w, a.h)
    rnd = random.Random(seed)
    for i in range(a.w * a.h):
        pick = b if rnd.random() < t else a
        out.ch[i] = pick.ch[i]
        out.fg[i] = pick.fg[i]
        out.bg[i] = pick.bg[i]
        out.lit[i] = pick.lit[i]
    return out


def wipe(a: Canvas, b: Canvas, t: float, horizontal: bool = True) -> Canvas:
    out = Canvas(a.w, a.h)
    edge = int((a.w if horizontal else a.h) * t)
    for y in range(a.h):
        for x in range(a.w):
            i = y * a.w + x
            pick = b if ((x < edge) if horizontal else (y < edge)) else a
            out.ch[i] = pick.ch[i]
            out.fg[i] = pick.fg[i]
            out.bg[i] = pick.bg[i]
            out.lit[i] = pick.lit[i]
    return out


def fade_to(canvas: Canvas, t: float) -> Canvas:
    """Darken the whole canvas; t=1 is black."""
    out = Canvas(canvas.w, canvas.h)
    out.ch = list(canvas.ch)
    out.fg = list(canvas.fg)
    out.bg = list(canvas.bg)
    out.lit = [l * max(0.0, 1.0 - t) for l in canvas.lit]
    return out
