# Unbound — design plan (pre-build)

A terminal game in the *Origins: The Unbound* universe, built for termstation.
Not the Godot doc. That doc is real-time action (Hades-style, "no dice in
fights") for a game a human builds over 35 weeks in an engine we don't have.
This is the *current* stated direction instead: gladiator-first, tactical
grid combat, persistent injuries, a league ladder, contracts/economy. That
direction is buildable here — it's dice-friendly, turn-based, and termstation
already has the pieces (`games/gladiator` proved the setting works; today's
Hollow proved a telegraphed tactical-grid combat spine works).

Building as a new game (`unbound`), not a rewrite of `games/gladiator` —
that one works and stays as the arcade-sized taste of the world; this is the
career-length version.

## The concept

You are property. A name on a ledger before you are a name anyone cheers.
Bought into the **slave league**, you fight because the alternative is worse.
Win, and your contract has a price — and someone with enough gold can end
your indenture. Lose enough, and you're property that stopped being worth
feeding.

**The whole arc is upward mobility bought in blood: slave league → club
league → the elite Unbound league → buy your own freedom.**

## Why this reuses today's proven work, not a rebuild

- **Telegraphed tactical combat** (Hollow, proven this session): an opponent
  who's about to strike shows it, and hitting them mid-committal is the
  punish. That's Souls-like mastery on a grid — the doc's own reference list
  for combat feel. We keep the spine, lose nothing.
- **`games/gladiator`**: already proves stance-reading, stamina and crowd
  favour work in this exact setting. This game is what that one becomes at
  ten times the length.
- **The chemistry engine, verbs, actors-as-materials** (Wildreach, scrapped
  for being the wrong *game*, not wrong *code*): sits in git history at
  `3afbdac` if a grid arena ever wants environmental hazards. Not proposed
  for v1 — flagging only so it's not forgotten.

## The three systems that multiply (the BotW lesson still applies)

| System | What it is | What it multiplies with |
|---|---|---|
| **Tactical grid combat** | telegraphed strikes, punish, positioning, weight | injuries (where you get hit is what breaks) |
| **Persistent injuries** | wounds don't reset between fights; a broken arm changes what you can do until it heals | economy (healing costs money you don't have), the ladder (fight hurt or forfeit) |
| **Contracts & the ladder** | your price, your record, your owner, your route up | injuries (a hurt fighter is worth less), combat (a must-win fight for your contract feels different from a sparring bout) |

Everything else in the doc — the city political sim, 12 archetypes, co-op
netcode, prestige/NG+, the secret god character, 15 named NPC arcs — is real,
good material, and **cut from v1** for the same reason Crimson Desert's
reviews warned about: many systems, thinly connected, is overwhelm. It's
deferred, not deleted, same as this session's earlier cuts.

## The loop — two decisions, not one

*Judge's finding: "heal has no decision in it — pay money, wait, be better.
That's a menu." Fixed below: recovery reuses the shape that already worked
today for Wildreach's charges — one resource, two jobs, and the right answer
depends on how the last fight went.*

1. **Fight** — tactical grid combat, telegraphed, read-and-punish, and every
   defensive option has a body part attached. The result (win/loss) and the
   damage ledger (what got hit, how hard) are tracked separately — a win
   raises your record and price; the ledger, regardless of the result,
   becomes whatever wound you carry out of the ring.
2. **Fight hurt, or sit out** — a wound doesn't force a choice by itself. The
   ladder doesn't wait: sit out to heal and your price decays and your slot
   goes to someone else; fight hurt and you're paid, but you're fighting on
   a leg that won't reposition, into an opponent who will find that leg.
3. **Climb or get bought** — enough wins and your owner can sell your
   contract upward (club league) or you can, eventually, buy it yourself.

That's the whole game: fight, and decide what to do about what it cost you.

## Injuries — made unavoidable by design, not left to chance

*Judge's finding, and it's correct: written as "consequence of losing," a
player who reads and punishes well never takes a hit, and the system never
fires. Hollow's own bots proved this — the reading policy went six fights
without a scratch. That can't be true here.*

**Fix: full avoidance is never free.** Fights run long enough, and against
enough opponents, that some damage is coming — the decision is never "do I
get hit," it's **where**. Blocking, taking a hit on your guard arm, eating
it on the ribs to protect your legs — every option has a body part attached,
and standing there doing nothing costs stamina you need for the punish.

**Correction from the owner: injury is not tied to winning or losing at
all.** It comes purely from how much you got hit and how hard — the same
fight in UFC where the winner walks out more marked up than the loser,
because winning on points after fifteen hard minutes still means you took
fifteen hard minutes. There is no branch for "you lost, so you're hurt" —
there is only a running ledger of every shot that landed on you, its power,
and where, and that ledger is what a wound is made of. Winning correlates
with less injury only because a dominant fighter usually gets hit less —
it's a consequence of the fight, not a rule about the outcome.

Wounds land on a body part and *change what you can do*, and outlive the fight:

| Location | A bad wound means |
|---|---|
| Arm | can't two-hand, punishes matter less |
| Leg | can't reposition well — the thing tactical grid combat is *about* |
| Ribs | every hit taken afterward costs more |
| Head | your reads get worse — telegraphs are harder to trust |

This is what "persistent injuries/body parts" from your notes actually buys:
every fight's damage has a *location*, the location outlives the fight, and
because avoidance was never free, every fighter accumulates some.

## Contracts & economy

- Your price rises with wins, falls with losses.
- Your owner takes a cut of every purse.
- A buyout number exists from the start — visible, so climbing toward your
  own freedom is a real number going down, not a vague promise.
- Losing badly enough (or an untreated wound going bad) can end the run
  outright — permadeath fits the setting: a slave who can't fight isn't kept.

## Cut from v1, explicitly

City hub, senate/political sim, 12 archetypes, co-op, prestige/NG+, named
NPC cast, the secret Lazi character, status-effect grid, item rarity tiers —
all real, all in the source doc, all **deferred**. v1 is one fighter, one
ladder, three systems.

## Permadeath — a career ends the way a slave's does

*Judge's finding: starting as property changes this in the plan's favor.
A slave who can't fight isn't kept — so death and career-ending injury are
the same outcome, and unlike Hollow's sudden death, this one is visible
coming: a wound that won't heal, a price that's fallen too far. Dread, not
a surprise, and it falls out of the injury system for free.*

**Floor, so attrition can't end a career in four unlucky fights:** the slave
league guarantees a minimum run of fights before a contract can be ended by
your owner. Bad luck early doesn't end the game before it's taught anything.

## The doc is not abandoned

The owner's framing: this is an ideas doc, salvaged from an earlier attempt,
and the terminal version exists precisely because web/React attempts at this
game keep collapsing under their own weight. The intent is to build this as
*true to the doc's world as the medium allows*, not to permanently discard
everything past the gladiator opening. Factions, the Colosseum's politics,
named characters, the gods, the city — all real, all still wanted, all
layered in once the fighting core (this stage) is proven. Deferred, staged,
not cut.

## Row budget

Same risk Hollow already solved — viewport, HUD, log band combat replaces.
The pattern carries over; not re-litigating it.

## Build order — prove the pillar before the ladder exists

**First: one fight, with locations.** A single grid bout where damage lands
somewhere specific and the HUD shows which part is hurt. This tests the one
thing that makes this game different from Hollow, before any ladder,
contract, or economy code exists. If a located wound doesn't change how the
next thirty seconds of that same fight play, the pillar is hollow.

Then: the wound persisting into a second fight. Then the fight-hurt-or-heal
decision. Then the ladder and contracts.
