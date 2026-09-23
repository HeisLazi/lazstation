"""World generation: elevation, moisture, biomes, landmarks.

The world is one contiguous region -- no chunks, no streaming. 180x110 is
19,800 tiles, which builds in well under a second and lives happily in a
list. Simulation never walks the whole thing (see sim.py); only generation
and drawing do, and drawing only touches the viewport.
"""
import math
import random

from materials import MATERIALS

W, H = 180, 110


def _noise(rng, w, h, cells, octaves=3):
    """Value noise on a [0,1] grid, built from a few smoothed lattices."""
    field = [0.0] * (w * h)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        step = max(2, cells >> o)
        gw, gh = w // step + 2, h // step + 2
        lat = [rng.random() for _ in range(gw * gh)]
        for y in range(h):
            fy = y / step
            y0 = int(fy); ty = fy - y0
            ty = ty * ty * (3 - 2 * ty)          # smoothstep
            for x in range(w):
                fx = x / step
                x0 = int(fx); tx = fx - x0
                tx = tx * tx * (3 - 2 * tx)
                a = lat[y0 * gw + x0];       b = lat[y0 * gw + x0 + 1]
                c = lat[(y0 + 1) * gw + x0]; d = lat[(y0 + 1) * gw + x0 + 1]
                top = a + (b - a) * tx
                bot = c + (d - c) * tx
                field[y * w + x] += (top + (bot - top) * ty) * amp
        total += amp
        amp *= 0.5
    return [v / total for v in field]


def _biome(elev, moist):
    if elev > 0.78:
        return "peaks"
    if elev < 0.36:
        return "marsh" if moist > 0.45 else "waste"
    if moist > 0.54:
        return "forest"
    if moist < 0.34:
        return "waste"
    return "meadow"


def _material(rng, biome, elev, moist):
    if elev < 0.30:
        return "water" if elev < 0.26 else "shallow"
    if biome == "peaks":
        if elev > 0.86:
            return "rock"
        return "snow" if rng.random() < 0.72 else "stone"
    if biome == "marsh":
        r = rng.random()
        if r < 0.22: return "shallow"
        if r < 0.40: return "brush"
        return "dirt" if r < 0.72 else "grass"
    if biome == "forest":
        r = rng.random()
        if r < 0.34: return "tree"
        if r < 0.52: return "brush"
        return "grass"
    if biome == "waste":
        r = rng.random()
        if r < 0.10: return "rock"
        if r < 0.22: return "stone"
        return "sand" if moist < 0.22 else "dirt"
    r = rng.random()                                    # meadow
    if r < 0.06: return "tree"
    if r < 0.16: return "brush"
    if r < 0.22: return "stone"
    return "grass"


#: Landmarks are Skyrim's "see that mountain" -- visible from far off, and
#: each one is a reason to walk. They are placed, never randomised in kind.
LANDMARKS = [
    dict(key="beacon",  name="the Ashen Beacon",   glyph='↑', rgb=(255, 170, 60),  tall=True),
    dict(key="spire",   name="the Drowned Spire",  glyph='♦', rgb=(120, 200, 230), tall=True),
    dict(key="gate",    name="the Iron Gate",      glyph='∏', rgb=(180, 170, 150), tall=True),
    dict(key="barrow",  name="the Long Barrow",    glyph='∩', rgb=(150, 140, 120), tall=False),
    dict(key="grove",   name="the Hollow Grove",   glyph='↟', rgb=(110, 200, 130), tall=False),
    dict(key="pyre",    name="the Broken Pyre",    glyph='♠', rgb=(220, 110, 70),  tall=False),
]


class World:
    """Terrain, elevation and biomes. Elements live in sim.py, sparsely."""

    def __init__(self, seed=None):
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        rng = random.Random(self.seed)
        self.w, self.h = W, H

        elevf = _noise(rng, W, H, 44, 4)
        moistf = _noise(rng, W, H, 30, 3)

        # Pull the edges down so the region reads as an island, not a crop.
        for y in range(H):
            for x in range(W):
                dx = (x / W - 0.5) * 2
                dy = (y / H - 0.5) * 2
                edge = max(abs(dx), abs(dy)) ** 4
                v = elevf[y * W + x] * 0.78 + 0.30      # lift the land clear of the sea
                elevf[y * W + x] = max(0.0, v - edge * 0.42)

        self.mat = [""] * (W * H)
        self.elev = [0] * (W * H)
        self.biome = [""] * (W * H)
        for i in range(W * H):
            e, m = elevf[i], moistf[i]
            b = _biome(e, m)
            self.biome[i] = b
            self.mat[i] = _material(rng, b, e, m)
            self.elev[i] = min(9, int(e * 11))

        self.landmarks = []
        self._place_landmarks(rng)
        self._carve_roads(rng)

    # ------------------------------------------------------------ queries
    def inside(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h

    def at(self, x, y):
        return self.mat[y * self.w + x]

    def set(self, x, y, m):
        self.mat[y * self.w + x] = m

    def height(self, x, y):
        return self.elev[y * self.w + x]

    def walkable(self, x, y):
        return self.inside(x, y) and MATERIALS[self.at(x, y)]["walk"]

    def opaque(self, x, y):
        return not self.inside(x, y) or MATERIALS[self.at(x, y)]["opaque"]

    def cover(self, x, y):
        return MATERIALS[self.at(x, y)]["cover"] if self.inside(x, y) else 0

    # ------------------------------------------------------------ shaping
    def _place_landmarks(self, rng):
        spots = []
        for spec in LANDMARKS:
            for _ in range(400):
                x = rng.randrange(12, W - 12)
                y = rng.randrange(8, H - 8)
                if not self.walkable(x, y):
                    continue
                if any(abs(x - a) + abs(y - b) < 38 for a, b in spots):
                    continue
                spots.append((x, y))
                self.landmarks.append(dict(spec, x=x, y=y, found=False))
                self._build_site(rng, x, y, spec["key"])
                break

    def _build_site(self, rng, cx, cy, key):
        """A little ruin around each landmark, so arriving feels like arriving."""
        r = 4 if key in ("beacon", "spire", "gate") else 3
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                if not self.inside(x, y):
                    continue
                d = math.hypot(x - cx, y - cy)
                if d > r:
                    continue
                if d > r - 1.2 and rng.random() < 0.55:
                    self.set(x, y, "wall")
                elif rng.random() < 0.30:
                    self.set(x, y, "ruin")
                else:
                    self.set(x, y, "floor")
        for _ in range(3):                       # ways in
            a = rng.random() * math.tau
            self.set(max(0, min(W - 1, cx + int(math.cos(a) * r))),
                     max(0, min(H - 1, cy + int(math.sin(a) * r))), "door")

    def _carve_roads(self, rng):
        """Rough tracks between landmarks -- the world's own suggestions."""
        pts = [(l["x"], l["y"]) for l in self.landmarks]
        for i in range(len(pts) - 1):
            x, y = pts[i]
            tx, ty = pts[i + 1]
            guard = 0
            while (x, y) != (tx, ty) and guard < 900:
                guard += 1
                if self.at(x, y) not in ("water", "wall", "floor", "door"):
                    self.set(x, y, "road")
                if rng.random() < 0.82:
                    if abs(tx - x) > abs(ty - y):
                        x += 1 if tx > x else -1
                    elif ty != y:
                        y += 1 if ty > y else -1
                else:
                    x += rng.choice((-1, 0, 1)); y += rng.choice((-1, 0, 1))
                    x = max(0, min(W - 1, x)); y = max(0, min(H - 1, y))

    def spawn(self):
        """A walkable start, near the middle, not inside a landmark."""
        rng = random.Random(self.seed ^ 0x5EED)
        for _ in range(6000):
            x = rng.randrange(W // 4, 3 * W // 4)
            y = rng.randrange(H // 4, 3 * H // 4)
            if self.walkable(x, y) and self.at(x, y) not in ("floor", "door"):
                if all(abs(x - l["x"]) + abs(y - l["y"]) > 14 for l in self.landmarks):
                    return x, y
        return W // 2, H // 2
