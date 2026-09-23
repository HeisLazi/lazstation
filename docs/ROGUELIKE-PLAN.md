# The roguelike — design, round 2

No code. No name yet. Two judge rounds and one owner ruling are folded in.

Two aspects carry the whole game and everything else waits on them:
**combat** and **the run loop**.

## 1. Combat — read the wind-up, punish the opening

Terminal combat usually fails because you cannot see what is happening.
Animation is thin, damage numbers are noise, and "bump the monster and hope"
is a dice roll wearing a sword. Over a 1–2 hour run that is fatal: an unfair
death in hour two makes people quit for good.

So combat runs on **perfect information**, which is the one thing a terminal
is genuinely excellent at. A glyph *is* a telegraph.

### The spine

Every enemy runs a two-beat cycle and both beats are visible:

1. **Wind-up.** The tiles it is about to hit are marked now, before it
   happens. You can always see what is coming.
2. **Strike.** It lands exactly where it said.

And the hinge that makes this a system rather than a warning light:

> **An enemy winding up is an enemy that is open.** Hit it during the wind-up
> and you do full damage and *stagger* it — the strike never happens.

Every telegraph is therefore both a threat and an invitation. Combat is
read-and-punish: bait the wind-up, leave the marked tiles, hit the thing that
has committed. Sekiro's rhythm in turns, and it reads perfectly in ASCII.

### The punish must cost something

**This is the fix that keeps it from going rote**, and it is a constraint on
encounter design, not a rule on its own. If stepping out and punishing is
always safe, optimal play never changes and the game is solved by encounter
twelve.

So: **punishing means standing where the next telegraph will fall.** Rooms are
built with overlapping threat — never one enemy politely at a time. The
question each turn is not "can I punish" but "which punish can I afford."

### Fragility, and the one mistake you are allowed

You have **6 HP**; most hits take 1–2. No attrition phase, no chipping away —
every hit is an event.

But 6 HP plus perfect information is *too* harsh, because every death is then
provably your own fault, which is exhausting across ninety minutes. The answer
is not more HP. It is **one recoverable mistake**:

> **Step-through.** Spend a charge to walk through a marked tile unharmed.

### Depth comes from telegraph shapes, not stat blocks

| Shape | What it teaches |
|---|---|
| line | step sideways, never back |
| cone | get close or get out — the middle is worst |
| burst around self | melee is punished; range or disengage |
| delayed (fires in 2 turns) | you must plan against a clock |
| moving (charges along a path) | the safe tile moves as it does |
| linked (two enemies share a tile) | the board is the threat, not the enemy |

Six shapes overlap into far more than six encounters. Two enemies with
different shapes force a real choice about which one you may punish this turn.

### Position and force over damage

Your attacks move things — knockback into hazards, into other enemies, into
their own telegraphed tiles. The best kills are performed by the board. A
crowded room becomes an asset rather than a death sentence.

## 2. The economy — charges, and they do both jobs

*Owner's ruling: scarcity lives in combat, as recovery charges.* The synthesis
below also makes them the run's currency, which closes the loop's hole without
inventing a second economy.

**Step-through charges are the only scarce thing in the game.**

- **In a fight** they are your one recoverable mistake: walk through a marked
  tile unharmed.
- **Between fights** they are the currency: every exit offers **either a
  technique or charges**, and the strongest techniques *cost* charges to take.
- They refill only at a region boundary. Never mid-region.

So every door asks one honest question: **do I get stronger, or do I stay
alive?** One resource, two jobs, and the answer changes depending on how badly
the last fight went — which means the loop reads the player's actual state
rather than a menu.

## 3. The run loop — 1 to 2 hours

**Four regions, ~6 encounters each, a boss apiece.** Around 28 encounters at
2–3 minutes each is 60–90 minutes, with the tail for a careful run.

Every encounter ends in a choice of exits, each showing two things up front:

- **what it gives** — a technique, or charges
- **what it adds to the run** — a new enemy type, or a condition (darkness,
  narrow rooms, a hunter that follows you)

You are always trading "make the run harder" against "make yourself better at
it," and now also against "stay able to survive a mistake." A decision every
three minutes, informed, never once per run.

### Techniques change the puzzle, never the numbers

- your punish knocks the target back two tiles
- you see telegraphs two turns ahead instead of one
- staggering an enemy also staggers whoever is adjacent
- your first punish each fight does not cost your action
- a stagger refunds half a charge

Every one alters reading or punishing — the two things combat is made of.
Nothing on this list is "+2 damage", and nothing ever will be.

## 4. Metaprogression — breadth, never power

Owner's rule, and it is the right one: **nothing that makes playing easier.**

- achievements
- **alternate starts** — a different opening kit and technique; sideways, not
  stronger
- **character unlocks** — characters whose core verbs differ, the way Slay the
  Spire's characters differ, not the way a stat upgrade differs
- small cosmetic upgrades

No permanent damage or health upgrades. A run won on the tenth attempt is won
because the player got better, not because the save file did.

## 5. Companions — interactable events

A companion is **a person who changes a rule of the run and can be lost**:

- a scout who extends telegraph vision by a turn — follows you, can be killed
- a prisoner who opens routes but draws more enemies
- a wounded fighter who will hold a corridor for three turns, once

Modifiers with a face and a risk. No approval meter, no relationship arc, no
dialogue tree. Taking one costs charges, so a person competes directly with
your own survivability — which is what makes losing one hurt.

**Cut: the `[READ 12]` dialogue check as originally written.** A d20 deciding
what you get on walking into a room is a slot machine with a font — the player
has no input. If a check survives at all it reads **run state**: you earn the
scout because you have been staggering instead of fleeing, or because the
prisoner is still alive. Same visible number, but a verdict rather than a roll.

## 6. Cut, and why

- **Open world.** Dead. A 1–2 hour permadeath run and an open world want
  opposite things — wandering and safety versus pressure and a clock. Hades,
  the owner's own reference, has a persistent *hub* and strictly **linear
  runs**; the hub already exists here as the console's between-run screen.
- **The route map** (six regions, you see four, you pick the order).
  Decoration: an uninformed choice made once per run, at the cost of building
  50% more regions. The door choice every three minutes is strictly better
  because it is informed and frequent. Four regions, made good.
- **Dialogue skill checks as written.** See above.

## 7. Still open — needs the owner

1. **Setting and fantasy.** What are you, where, and why are you descending?
   The combat fiction wants someone fragile and perceptive — a duelist, not a
   warrior — but the world is wide open.
2. **The characters.** Metaprogression unlocks characters whose *core verbs*
   differ. What those verbs are is the single biggest content decision left.
3. **The name.**
