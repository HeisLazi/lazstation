# Game design document — round 3

The previous two documents were systems specs. They were mechanically sound
and completely lifeless, which is the note that produced this one: *it needs
to feel alive.*

So this one is built the way a studio builds one — concept first, then
pillars, then a narrated minute of play, then features, then the slice.

---

## 1. The concept

> **You are a Knifewright: someone who wins a fight by reading it. You descend
> through the Hollow, a drowned cathedral where the dead cannot stop
> performing the rituals they died doing — which is exactly why you can see
> every blow before it lands.**

The hook is that **the core mechanic and the fiction are the same thing.**
Enemies telegraph because they are echoes, locked in a loop they cannot break.
You are the only thing down there with free will, and your whole power is that
you can *watch*. Striking mid-ritual does not just damage them — it **breaks
the loop**, which is why a staggered enemy's blow never lands.

That is not flavour pasted onto a mechanic. Perfect information *is* the
ghost story.

### Alternatives, if this one does not land

- **The Duelling Circuit** — masked duelists, each with a style and a tell.
  Telegraph = their tell. Warmer, more readable, less strange.
- **The Engine** — you are inside a vast machine that is killing you.
  Everything telegraphs because machines run on cycles. Colder, more Cogmind.

---

## 2. The three pillars

Everything in this game must serve one of these, or it is cut.

1. **You see it coming.** Perfect information, always. Death is never a
   surprise, and the game is never unfair.
2. **The opening is the fight.** Every threat is simultaneously an invitation.
   Reading beats reacting; patience beats aggression.
3. **The run is a story you can retell.** Not a score. An anecdote — *"I lost
   the scout on floor three and had to finish the Warden on one heart."*

---

## 3. A minute of play — what it actually feels like

> You step into a flooded transept. Two shapes in the dark.
>
> The **Sallow Duelist** turns to face you, and the floor in front of him
> lights with three marked tiles — a lunge, and it will land next turn. Behind
> him a **Censer-Bearer** begins to swing, and a ring of tiles around *itself*
> starts to glow. Not yet. In two.
>
> You could step back out of the lunge. Safe. Nothing happens, and he resets.
>
> Or you can step *inside* it — one tile diagonal, out of the marked line and
> right up against him — and put the knife in while he is committed. Full
> damage, and the lunge dies in his chest. But that puts you inside the
> Censer-Bearer's ring, and that ring lands in two turns.
>
> So the fight is a question, and you have one turn to answer it: **can you
> kill the Duelist and be gone before the censer swings?**
>
> You take the punish. He folds. The ring brightens.
>
> You have one charge left. You could spend it and walk out through the fire
> untouched — but charges are what you trade at the next door, and you wanted
> that technique.
>
> You run instead. You make it. Barely. Something behind the wall starts
> breathing, and the log says: *the Hollow has noticed you.*

That is the game. Everything below exists to produce that minute.

---

## 4. How it feels alive

This is the section the last two documents did not have, and the reason they
read as dead. Aliveness is not one feature; it is eight cheap ones.

| System | What it does | Cost |
|---|---|---|
| **Named enemies with tells** | not "goblin A" — the Sallow Duelist, the Censer-Bearer, the Choirmaster. Each has one readable personality trait expressed in how it moves | low |
| **Barks** | one line of text tied to state. *"The Duelist smiles."* *"Something is breathing behind the wall."* Cheapest aliveness per byte in all of game design | very low |
| **The Rival** | a named Knifewright descending ahead of you. You find rooms she has already cleared, her corpses, her notes. She helps once. She is the fourth boss | medium |
| **Enemies react to each other** | they flinch, they flee at low health, they call others, they can be made to hit each other. Behaviour you can read and exploit | medium |
| **The world acts without you** | a torch gutters out, a door swings, water rises a tile, something moves in the dark two rooms away | low |
| **Scars persist** | a room you burned stays burnt for the run. Your route is visible behind you | low |
| **The Hollow notices** | a run-long escalation: the more loudly you fight, the more it sends. Your play style changes the run | medium |
| **The death screen tells your story** | not a score. A paragraph naming what killed you, who you lost, and what you were carrying | low |

**The Rival is the single highest-value item on this list** and should be in
the first playable build, not deferred to polish. A world with one other named
person in it stops feeling like a test harness immediately.

---

## 5. Features, by tier

### Must have — this is the game
- grid tactical combat, one screen, perfect information
- telegraphs: marked tiles shown a turn before they land
- **punish**: hitting a winding-up enemy does full damage and staggers it
- overlapping threat: rooms are built so punishing costs you position
- 6 HP; every hit is an event
- **step-through charges**: the one recoverable mistake, and the run currency
- 6 telegraph shapes (line, cone, burst, delayed, moving, linked)
- knockback — into hazards, into enemies, into their own marked tiles
- 4 regions x ~6 encounters + a boss each
- door choice between fights: a technique, or charges, and what it adds
- techniques that change the puzzle, never the numbers
- named enemies, barks, the death-story screen
- permadeath

### Should have
- **the Rival** (argued above: promote this to must-have if anything slips)
- companions as run modifiers who cost charges and can be lost
- the Hollow's escalation
- persistent scars within a run
- animation on telegraph / strike / stagger via the fx layer
- 3 characters with different core verbs (metaprogression)

### Could have
- alternate starts
- cosmetic unlocks
- a bestiary that fills in as you learn each enemy's tell
- daily seed

### Will not have
- open world · route map · stat upgrades of any kind · crafting · hunger
- approval meters · dialogue trees · anything that makes a later run easier

---

## 6. The build path — vertical slice first

A vertical slice is one room containing *everything the finished game has*,
at final quality. It is not a prototype; it is a core sample.

**The slice:** one room. Two enemies, two telegraph shapes, overlapping
threat. One technique. One charge. Barks. Animation on the strike. The
death-story screen. Nothing generated, nothing scaled.

When that room is fun, the game is fun and the rest is volume. When it is
not, we have lost an afternoon instead of a fortnight.

Then, in order: generation -> a full region -> the door choice -> the Rival
-> regions 2-4 -> metaprogression.

---

## 7. Open — owner's call

1. **Which concept**: the Hollow, the Duelling Circuit, or the Engine.
2. **The name.**
3. Whether the Rival is in the slice. (Recommendation: yes.)
