# Poke and Mon -- hands-on playtest checklist

Bots have driven this game for thousands of battles, so crashes and blank
screens are unlikely. What bots can't judge is **feel**. This list is about that:
is it fun, readable, fair, and does anything look wrong to a human eye.

## Run it

Normal: launch from the TermStation console like any game.

Scratch saves (so you never touch your real one), from `games/beastling/`:

```
python3 playtest_seed.py fresh /tmp/pt_fresh     # also: mid, late, post
PYTHONPATH=../../sdk TERMSTATION_SAVE_DIR=/tmp/pt_fresh python3 main.py
```

| stage | what you get |
|---|---|
| fresh | nothing, start the story |
| mid | 2 badges, level ~18 team, 1,500 coins, a bag of supplies |
| late | 4 badges, level ~30, 4,000 coins |
| post | all 5 badges, level ~55, 9,000 coins -- Champion's Hall is open |

Play at **66x24** at least once (the declared minimum) and once at your normal
terminal size. Anything that vanishes, wipes or runs off the edge is a bug.

Tip: after "Camp" -> "Save and quit", delete the scratch dir to start over.

---

## 1. First 15 minutes (fresh)

- [ ] Title screen reads well; "Poke and Mon" shows in the header.
- [ ] Starter choice: can you tell the three apart before choosing?
- [ ] Meadow Path: do fights feel quick (about 3-5 turns)? Any move you never use?
- [ ] Catch something with a lure. Is the catch chance shown and believable?
- [ ] Lose a fight on purpose. Is the penalty (100 coins) fair, the message clear?
- [ ] Reach Wren the Gardener (first champion). **Read her box**: does the level
      and "aces carry gear" line help you decide whether to fight yet?
- [ ] Is it clear what to do next at every screen, without reading code?

## 2. Combat feel (any stage)

- [ ] Weather (Flare Rush / Tide Pull): is "Blaze (5 left)" clear? Does it matter?
- [ ] Statuses: burn, paralyze, sleep, confused -- is each one readable
      (tag next to the HP bar) and not annoying? Sleep especially: too punishing?
- [ ] Abilities: do you ever *notice* them, or are they invisible?
- [ ] Crits and "super effective": satisfying, or too random?
- [ ] Anything where you can't tell what just happened from the log (it only
      shows the last 4 lines)?
- [ ] Try swap and run. Swap should cost the turn.

## 3. Variety and rarity

- [ ] Walk Meadow Path ~30 times: do you see 6+ different beasts?
- [ ] Do you ever see "A rare X appears!"? (about 1 in 50). Does it feel special?
- [ ] Try to hold a 4th beast of the same family: lure should refuse ("lure (full)").
- [ ] Field notes: do 36 species fit and read cleanly?

## 4. Shop, items and economy (use `mid`)

- [ ] Camp -> Supplies: Lures / Medicine / Battle gear / Type sashes / Training hall.
- [ ] Locked items greyed with the badge requirement. Any price that feels wrong?
- [ ] Buy and equip gear. Does swapping give the old item back to the bag?
- [ ] In battle: **item** option appears, costs the turn, Cancel is free.
- [ ] Rest costs coins now. Is the price shown on the menu? Does a partial rest
      (when broke) feel fair rather than punishing?
- [ ] Training hall: is the price curve motivating or a wall?
- [ ] Find a **rare treasure** by KOing a rare spawn, or buy Rare Scent (500c).
      Does hunting for one feel worth it?
- [ ] Are you swimming in coins or always broke? Note when it flips.

## 5. Champions (use `mid`, then `late`)

- [ ] Fight each champion near their top level. Winnable but not trivial?
- [ ] Do their geared aces read as a real threat (Mending Berry heal, Guard Charm)?
- [ ] After a loss, do you know *why*? (log clarity)
- [ ] Reward screen: item + purse + badge. Satisfying?

## 6. Post-game (use `post`)

- [ ] Camp -> Champion's Hall: 5 rematches + Battle Spire.
- [ ] Rematch: 5-6 geared beasts. Hard enough to need potions?
- [ ] Rematch level scales with your team. Does it feel tracked to *you*?
- [ ] Battle Spire: floor 1 -> 5 (boss). Do you get the rest stop after the boss?
- [ ] Does the Spire have a "just one more floor" pull? Where does it stop being fun?
- [ ] Retreat vs keep climbing: is the decision interesting?

## 7. Tournament mode -- the Arena District

The Tournament is its own little world: a hub of places (Arena Gate, Squad
Hall, Market, Infirmary, Yard, Hall of Fame). HP and PP carry over between
rounds; coins from prizes pay for treatment and supplies.

- [ ] Main menu -> Tournament. Name screen is one line, then the District hub.
- [ ] Squad Hall -> Free draft: 36 species over two pages. Typing a number from
      the other page flips to it (it does NOT draft it); the Squad line lists
      your picks from both pages.
- [ ] Ranked draft: point costs shown, budget enforced.
- [ ] Hub shows the run, how many are standing, and the next rival
      (types, team size, levels). Does that change what you do first?
- [ ] Arena Gate fight: moves show PP and ▲/▼ (super effective / resisted).
      Does PP running out force real choices, or is it noise?
- [ ] Swap menu: each beast shows "KOs in N, KO'd in M" against the current
      foe. Is that readable at a glance? Does it make swaps feel informed?
- [ ] Let a beast faint right after switching in: you must be ASKED who comes
      next (no Cancel), and the screen says what happened.
- [ ] Infirmary after a rough round: pick a beast, then heal / PP / revive.
      Revive is per beast (about one round's prize). Can you afford
      everything? Is choosing who to revive for the next rival a real choice?
- [ ] Market items mid-fight (Potion, Super Potion, Full Heal, Revive, Ether):
      worth the coins versus the Infirmary?
- [ ] Yard: permanent training per species. Worth saving coins for between runs?
- [ ] Try the lazy plan -- one squad type, one strong move every turn. How far
      does it get? (Simulated: about 3.6 rounds of 6, vs 5.2 for careful play.)

## 8. 2v2 Synergy Duel (Camp, needs 2+ healthy beasts)

- [ ] Four beasts readable on one screen at 66x24.
- [ ] Synergy pairs: Ember+Spark, Tide+Bloom, Stone+Gloom -- is the bonus noticeable?

## 9. Things only you will notice

- [ ] Any text that is cut off mid-word, misaligned, or confusing.
- [ ] Any beast whose name, type or stats feel off.
- [ ] Any moment you wanted to do something and couldn't.
- [ ] The point where you'd stop playing, and why.

Write down anything odd with the exact steps -- "Camp -> Supplies -> Gear page 2,
the price column cuts off" is far more useful than "shop looks weird".
