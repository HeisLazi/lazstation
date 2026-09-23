# Wildreach — design plan (pre-build)

Status: **engine spike proven, game not started.** Nothing below is built yet
except where marked PROVEN.

## How this plan is governed

The plan goes to a judge, and **the judge's job is to reject it.** It is not
there to approve; it is there to be convinced, the way an investor is convinced
— every feature has to argue for its own existence or it does not get funded.

The rule: **three prompts.** A point may be debated across at most three
exchanges. If it is not proven by then, the judge is right and its ruling
stands. No feature enters this game because nobody argued against it.

## The pitch

An open-world RPG where you never get given the solution. The world is made of
materials, and elements change them. That is the whole engine. Every problem —
a locked gate, four bandits, a river, a cave you cannot see into — is solved by
pointing the world's own physics at it.

## Why this and not "a big RPG"

The research came back with a warning, not just ideas. Crimson Desert's reviews
landed on "utterly overwhelming" — many systems, thinly connected. Breath of the
Wild's designers said the opposite thing: *combining simple elements produces
complex results.* Depth is a small number of systems **multiplied**, not a long
list **added**.

So the budget goes on three systems that multiply against each other:

| System | What it is | What it multiplies with |
|---|---|---|
| **Chemistry** | fire, water, ice, charge, steam, smoke — on a sparse tile map | terrain (what burns, what conducts), combat (surfaces hurt) |
| **Terrain** | elevation, cover, opacity, materials, weather, wind | chemistry (wind drives fire uphill), combat (height advantage, line of sight) |
| **Actors as materials** | every living thing is made of the same stuff as the ground: an armoured enemy stood in water *is* a conductive tile that walks | both of the above — this is not a third system, it is the first two applied to things with HP |

**One grid. One turn clock. No mode switch.** You never leave the world to have
a fight. BG3's turn grammar — action, bonus, move, visible d20 — is the *pacing*
of an encounter, not a separate game you enter. This is the judge's correction
and it dissolves the two-modes problem: "tactical combat" named a mode, when the
thing that actually multiplies is a property.

## The verbs — what the player can actually do

An engine that produces unencoded outcomes proves nothing if the player cannot
*aim* it. The verb set is what converts the simulation into agency. Every verb
below goes through `sim.apply()` or `world.set()` — there is no verb that only
talks to the player's own stats.

**Six verbs. Funded.** Each has a terrain effect *and* an actor effect, which is
what makes ~12 interaction paths out of six verbs:

| Verb | On terrain | On an actor |
|---|---|---|
| **torch** (light / throw / drop) | ignites anything in `BURNS` | sets them alight |
| **water flask** (throw / pour) | wets ground so it will not take flame; makes steam on fire | soaks them: they will not burn, but they now conduct |
| **oil flask** (pour a trail) | lays a fuse fire will run down | they burn hot and long |
| **frost flask** | freezes water into a bridge you can walk | they stop moving |
| **iron rod** (plant) | draws the next strike to a chosen tile | — |
| **blade** (cut / shove) | clears brush: a firebreak and a sight line | melee, and Crimson Desert's weight — shove into fire, into water, off a height |

Plus **look**, which is not an action: what is this made of, and what will it do.
The game teaches itself by being read, so this is always available and free.

### Verbs cut from the first draft

- **`wait`** — not a verb, the absence of one. Ticking without acting is free in
  any turn-based sim; listing it only inflated the count.
- **plain arrow** — the fire arrow does all the work; a plain shot multiplies
  with nothing. (Ranged ignition folds into **torch**: throw it.)
- **`scrape`** (grass → dirt firebreak) — duplicates **blade** (cut brush →
  firebreak). Two verbs, one outcome. Exactly the padding the multiply-or-cut
  rule exists to catch.

Five of the six candidate solutions below come out of six verbs. The cut five
were buying nothing.

### Explicitly cut, and why

Each of these is *additive*: it costs authoring and multiplies with nothing.

- hunger / thirst / warmth meters — busywork, not decisions
- crafting trees, fishing, cooking — Crimson Desert's overwhelm
- companion approval sim — BG3's best feature and pure authoring; no emergence
- faction reputation — a spreadsheet pretending to be a world
- radiant/generated quests — Skyrim's own weakest system, infinite filler
- level-by-doing skill trees — numbers going up is not depth

**Feature-creep rule for the whole build:** a new feature must *multiply* with
at least two of the three core systems, or it does not go in. If it only adds a
number, a meter, or a menu, it is cut.

## What Skyrim / Fallout / BG3 / BotW / Crimson Desert each contribute

- **BotW** — the three chemistry rules. This is the engine. PROVEN.
- **BG3** — the *grammar* of a turn, and visible dice. You see `d20+4 vs 14`.
- **Fallout: NV** — every problem has several solutions, and the game shows you
  the check. We get this **free**: we author the lock, not the three ways past it.
- **Skyrim** — "see that mountain, you can go there." Landmarks visible from far
  off are quests without quest-givers. Plus unscripted collisions: a storm
  arrives mid-fight and now the water you are stood in is a liability.
- **Crimson Desert** — weight in combat (knock things into terrain, and the
  terrain matters), and weather that changes how you move and what you can see.

## PROVEN so far (the spike)

Three files exist: `materials.py`, `worldgen.py`, `sim.py`. All headless.

- 180×110 world generates in **88ms**; 75–81% walkable; **99% of land
  reachable**; all 6 landmarks reachable, across 3 seeds.
- A world turn costs **0.0009ms** quiet, **0.87ms avg / 6.9ms worst** during a
  full wildfire. Sparse elements: an empty meadow is free.
- **The emergence check — 7/7.** These outcomes are not encoded by any single
  rule; they fall out of rules meeting each other:
  1. fire crossed 20 tiles of oil into a grove that was never adjacent to it
  2. same fire, opposite winds → front drifts **+11.8 east vs −12.4 west**, and
     only +0.8 across the wind (this began as a weak ±1.5 result; the judge
     flagged it as noise, which exposed a real bug — the downwind test matched
     upwind tiles too)
  3. a stream held as a firebreak: 400 tiles burnt before it, **0 beyond**
  4. a charge ran a 21-tile pool end to end
  5. rain smothered a 87-tile blaze — by wetting ground, not by a rule saying so
  6. fire + water → steam
  7. lightning sought high conductive ground 12/12

That last point is the one that matters: **the engine already produces
solutions nobody wrote.** That is the thing worth building a game on.

## The row budget (76×20 inside the bezel)

Decided before any `draw()` is written, because this has bitten four games:

```
row 0        HUD: health, time, weather, wind, place
row 1        rule
rows 2–16    viewport (15 rows), scrolls over the world
row 17       rule
rows 18–19   log (2 lines)
```

**Combat replaces the log band with the action bar — it never adds rows.**

## Build stages, each with a kill criterion

0. **The six verbs, then the three-solutions test** (above). This is **a build
   stage, not a checkbox** — the gate cannot run until the verbs exist, and six
   verbs × terrain × actors is real work. Its output is a headless answer to the
   only question that matters: *can the player aim this thing on purpose?*
   *Kill the whole design if:* fewer than three sequences exist.
1. **Viewport + movement + the verbs.** Scroll the world inside the bezel, walk,
   and act on it. *Kill if:* **the bezel gets scrubbed, or the world scrolls
   without the frame staying put.** Framerate is explicitly **not** the
   criterion: the real per-cell chain (material → element → light → rgb) across
   76×15 with 175 live elements measures **0.59ms**, plus a 1.12ms repaint,
   against a 33ms budget at 30fps. A criterion that cannot fail is not a
   criterion — the honest risk here is correctness, not speed.
2. **Chemistry made visible.** Fire that animates, smoke that drifts, water that
   shines. The spike above, on screen.
   *Kill if:* **six consecutive frames dumped from the PTY harness do not reveal
   which way the fire is running.** The earlier wording — "reads as recoloured
   tiles" — was unfalsifiable: I would be the one judging, after building it,
   wanting it to work. This version is decided by frames on disk, with tools
   that already exist.
3. **Sight + light.** Shadowcast FOV (`fx.add_light` has no occlusion, so a torch
   would glow through stone — this is game logic, not SDK). Deliberately after
   chemistry: it blocks nothing, it is the fiddliest thing here, and seeing the
   chemistry read on screen teaches more per hour.
   *Kill if:* the light pass costs more than ~4ms per frame.
4. **Actors.** Enemies bound by identical rules, encounter pacing, visible d20.
   The kill criterion is written as a headless test **at the start of this
   stage, not the end**: place an enemy, ignite upwind, tick, assert it dies to
   the fire. *Kill if:* an enemy never once dies to the world instead of to the
   player.
5. **Content.** *Constrained:* what sits at a landmark must be a chemistry or
   terrain problem — a flooded vault, a gate that only fire opens, a peak you
   reach by freezing the falls. **Not** a note and a corpse. Prose is the
   seasoning, never the puzzle. Without this constraint Stage 5 becomes 80% of
   the work and adds none of the depth.

Stages 1–4 are the game. Stage 5 is volume, and only starts once 1–4 hold.

## The gate: the three-solutions test

This decides whether Wildreach is a game or a nice fire simulation. It runs
**before Stage 1**, headless, on the existing spike plus the verb list:

```
give the player: torch, water flask, oil flask, frost flask, iron rod, blade
place: a barred gate, a moat, four bandits behind it
assert: at least three distinct verb sequences reach "past the gate / bandits down"
```

The engine's 7/7 proves the *world* produces unencoded outcomes. It does not
prove a *player* can produce them on purpose. Those are different claims, and
the gap between them is where systemic games die. If three sequences cannot be
enumerated, the player is a spectator and the design is wrong.

Candidate solutions the design should already permit, with nothing authored:
burn the gate (`door` is in `BURNS`) · freeze the moat and walk over it · lay an
oil trail to the bandits and touch it off · plant the rod in a storm and let
lightning do it · push one into the water and spark it · cut the brush for a
clean bowshot.

## Save format

Versioned from turn one. World state (burnt tiles, looted sites, dead actors)
is large and will churn; `ts.load`'s default-merge will not rescue a
restructured blob. `version` int + a migration branch, and a `_summary` so the
console's CONTINUE card shows where you are.
