"""The world simulation: chemistry, weather, wind, time.

Pure. No curses, no drawing, no input. State in, state out -- so the whole
thing can be driven headlessly by a test, which is exactly how the emergence
check in tests/ works.

It ticks once per world turn, never per frame. Rendering interpolates
between ticks; it never simulates. Elements are stored sparsely, so a turn
costs O(active elements), not O(19,800 tiles) -- a forest fire is expensive
and an empty meadow is free.
"""
import random

from materials import (ASHES, BURNS, CONDUCTS, ELEMENTS, LIFETIME, MATERIALS,
                       REACTIONS, SOAKS, WEATHER, BIOME_WEATHER, DAYLIGHT)

NEIGHBOURS = [(-1, -1), (0, -1), (1, -1), (-1, 0),
              (1, 0), (-1, 1), (0, 1), (1, 1)]
CARDINAL = [(0, -1), (0, 1), (-1, 0), (1, 0)]


class Sim:
    def __init__(self, world, seed=0):
        self.world = world
        self.rng = random.Random(seed)
        self.elem = {}            # (x, y) -> [name, ttl]
        self.burning = {}         # (x, y) -> turns of fuel left
        self.turn = 0
        self.hour = 7
        self.minute = 0
        self.weather = "clear"
        self.weather_left = 40
        self.wind = (1, 0)
        self.wind_left = 30
        self.events = []          # (kind, x, y, detail) -- drained by the view

    # ------------------------------------------------------------ rule 2
    def apply(self, x, y, el, ttl=None):
        """Put an element on a tile, letting it react with what is there.

        This single function is Rule 2 (element changes element) and the
        entry point for Rule 1 (element changes material). Everything that
        creates fire, water, ice or charge goes through here, which is why
        there is no list of special cases anywhere else.
        """
        if not self.world.inside(x, y):
            return None
        cur = self.elem.get((x, y))
        if cur:
            out = REACTIONS.get((cur[0], el))
            if out is not None:
                if out != cur[0]:
                    self.events.append(("react", x, y, out))
                if out is None:
                    self.elem.pop((x, y), None)
                    self.burning.pop((x, y), None)
                    return None
                el = out
            elif cur[0] == el:
                cur[1] = max(cur[1], LIFETIME.get(el, 3))
                return el

        mat = self.world.at(x, y)

        # Rule 1: an element changes a material's state.
        if el == "fire":
            if mat not in BURNS:
                return None                      # nothing here will take
            self.burning[(x, y)] = BURNS[mat]
            self.events.append(("ignite", x, y, mat))
        elif el == "wet":
            if mat in SOAKS:
                self.world.set(x, y, SOAKS[mat])
            if (x, y) in self.burning:           # rain on a burning tile
                self.burning.pop((x, y), None)
        elif el == "ice":
            if mat == "water":
                self.world.set(x, y, "ice")
                self.events.append(("freeze", x, y, mat))
                return None
            if mat == "shallow":
                self.world.set(x, y, "ice")
                return None

        self.elem[(x, y)] = [el, ttl if ttl is not None else LIFETIME.get(el, 3)]
        return el

    def element_at(self, x, y):
        e = self.elem.get((x, y))
        return e[0] if e else None

    def douse(self, x, y):
        self.elem.pop((x, y), None)
        self.burning.pop((x, y), None)

    # ------------------------------------------------------------- a turn
    def tick(self):
        self.turn += 1
        self._clock()
        self._wind()
        self._weather()

        born = {}
        dead = []

        for (x, y), cell in list(self.elem.items()):
            name, ttl = cell
            if name == "fire":
                self._fire(x, y, born)
            elif name == "spark":
                self._spark(x, y, born)
            elif name in ("steam", "smoke"):
                self._drift(x, y, name, born)
            elif name == "ice":
                self._ice(x, y, born)

            cell[1] -= 1
            if cell[1] <= 0:
                dead.append((x, y))

        for (x, y) in dead:
            self._expire(x, y)
        for (x, y), (el, ttl) in born.items():
            if (x, y) not in self.elem:
                self.apply(x, y, el, ttl)

        self._ambient()
        return self.events

    def _expire(self, x, y):
        cell = self.elem.get((x, y))
        if not cell:
            return
        name = cell[0]
        if name == "fire":
            fuel = self.burning.get((x, y), 0) - 1
            if fuel > 0:                         # still has something to eat
                self.burning[(x, y)] = fuel
                cell[1] = LIFETIME["fire"]
                return
            mat = self.world.at(x, y)
            if mat in ASHES:
                self.world.set(x, y, ASHES[mat])
                self.events.append(("burnt", x, y, mat))
            self.burning.pop((x, y), None)
            self.elem[(x, y)] = ["ember", LIFETIME["ember"]]
            return
        if name == "ember":
            self.elem[(x, y)] = ["smoke", LIFETIME["smoke"]]
            return
        self.elem.pop((x, y), None)

    # ------------------------------------------------------------- fire
    def _fire(self, x, y, born):
        wx, wy = self.wind
        wet_air = WEATHER[self.weather]["douses"]
        for dx, dy in NEIGHBOURS:
            nx, ny = x + dx, y + dy
            if not self.world.inside(nx, ny):
                continue
            here = self.elem.get((nx, ny))
            if here and here[0] in ("fire", "ember", "wet", "ice", "steam"):
                continue                          # wet and ice stop it dead
            mat = self.world.at(nx, ny)
            if mat not in BURNS:
                continue
            chance = 0.55 if mat == "oil" else 0.34 if mat == "brush" else 0.22
            dot = dx * wx + dy * wy               # fire runs downwind
            if dot > 0:
                chance *= 2.6 if dot > 1 else 2.0
            elif dot < 0:
                chance *= 0.12
            if self.world.height(nx, ny) > self.world.height(x, y):
                chance *= 1.5                     # and uphill
            if wet_air:
                chance *= 0.10
            if self.rng.random() < chance:
                born[(nx, ny)] = ("fire", LIFETIME["fire"])
        if self.rng.random() < 0.30:
            born.setdefault((x + wx, y + wy), ("smoke", LIFETIME["smoke"]))

    # ------------------------------------------------------------ charge
    def _spark(self, x, y, born):
        """A charge runs through anything that conducts, all in one turn."""
        seen = {(x, y)}
        stack = [(x, y)]
        while stack:
            cx, cy = stack.pop()
            for dx, dy in CARDINAL:
                nx, ny = cx + dx, cy + dy
                if (nx, ny) in seen or not self.world.inside(nx, ny):
                    continue
                wet = self.element_at(nx, ny) == "wet"
                if self.world.at(nx, ny) in CONDUCTS or wet:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
                    born[(nx, ny)] = ("spark", 1)
                    self.events.append(("arc", nx, ny, None))
            if len(seen) > 260:                   # a lake is not infinite
                break

    def _ice(self, x, y, born):
        for dx, dy in CARDINAL:
            nx, ny = x + dx, y + dy
            if self.world.inside(nx, ny) and self.world.at(nx, ny) == "water":
                if self.rng.random() < 0.12:
                    self.world.set(nx, ny, "ice")
                    born[(nx, ny)] = ("ice", LIFETIME["ice"])

    def _drift(self, x, y, name, born):
        wx, wy = self.wind
        nx, ny = x + wx, y + wy
        if self.world.inside(nx, ny) and (nx, ny) not in self.elem:
            if self.rng.random() < 0.6:
                born[(nx, ny)] = (name, max(1, self.elem[(x, y)][1] - 1))

    # ----------------------------------------------------------- ambient
    def _clock(self):
        self.minute += 3
        while self.minute >= 60:
            self.minute -= 60
            self.hour = (self.hour + 1) % 24

    def _wind(self):
        self.wind_left -= 1
        if self.wind_left <= 0:
            self.wind_left = self.rng.randint(25, 70)
            self.wind = self.rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1),
                                         (1, 1), (-1, -1), (1, -1), (-1, 1)])

    def _weather(self):
        self.weather_left -= 1
        if self.weather_left <= 0:
            self.weather_left = self.rng.randint(45, 140)
            # biome at the centre of interest decides the mood
            self.weather = self.rng.choice(
                BIOME_WEATHER.get(self.focus_biome, BIOME_WEATHER["meadow"]))
            self.events.append(("weather", 0, 0, self.weather))

    focus_biome = "meadow"

    def _ambient(self):
        spec = WEATHER[self.weather]
        if spec["douses"]:
            # Rain does not "put fires out" -- it wets the ground, and wet
            # ground will not take a flame. The fire dies because it runs
            # out of anything dry to reach, which is the same reason a real
            # one does. Snow behaves the same way; it just looks colder.
            el = "ice" if self.weather == "snow" else "wet"
            for (x, y) in list(self.burning):
                for dx, dy in NEIGHBOURS:
                    if self.rng.random() < 0.34:
                        nx, ny = x + dx, y + dy
                        if self.world.inside(nx, ny) and (nx, ny) not in self.burning:
                            self.apply(nx, ny, el)
                if self.rng.random() < 0.30:
                    self.douse(x, y)
                    self.apply(x, y, "steam")
        if spec["charge"] and self.rng.random() < spec["charge"]:
            self.strike()

    def strike(self, x=None, y=None):
        """Lightning. Prefers height and conductive ground, as it should."""
        w = self.world
        if x is None:
            best, bx, by = -1, None, None
            for _ in range(120):
                cx = self.rng.randrange(w.w)
                cy = self.rng.randrange(w.h)
                score = w.height(cx, cy) + (6 if w.at(cx, cy) in CONDUCTS else 0)
                if score > best:
                    best, bx, by = score, cx, cy
            x, y = bx, by
        self.events.append(("strike", x, y, None))
        self.apply(x, y, "spark")
        if self.world.at(x, y) in BURNS and self.element_at(x, y) != "wet":
            self.apply(x, y, "fire")
        return x, y

    # ------------------------------------------------------------- light
    def daylight(self):
        return DAYLIGHT[self.hour] * WEATHER[self.weather]["light"]

    def clock_text(self):
        return f"{self.hour:02d}:{self.minute:02d}"
