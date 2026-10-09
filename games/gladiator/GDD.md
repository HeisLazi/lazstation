# Gladiator — Game Design Document
## Origins: The Unbound — Terminal Edition

**Status:** Living design document, pre-expansion  
**Game folder:** `games/gladiator/`  
**Platform:** LAZSTATION terminal console  
**Current implementation:** A small full-screen arena prototype with stamina,
stance reading, crowd favour, between-bout choices, animated impacts, and a
ten-opponent ladder.

This document is the design authority for expanding **Gladiator**. The
separate `unbound` packaging direction is retired. Gladiator is the canonical
terminal adaptation of *Origins: The Unbound*.

The document defines the intended game. A proposed feature is not considered
implemented until its rules, data, presentation, save behavior, and
verification path exist.

---

## 1. One-line pitch

**A human life is turned into arena property; fight, suffer, build a name, and
buy your freedom in a world where divine politics and an ancient anomaly are
starting to break through the walls.**

After freedom, the game becomes a mythic legacy RPG. A debt owed to Mors
eventually threatens the player's first child, forcing a choice between a
terrible bargain and revenge against the gods.

---

## 2. Player fantasy

The player should feel:

- the weight of a body that can be injured and changed;
- the danger of committing to an attack or defensive read;
- the satisfaction of becoming known through memorable fights;
- the pressure of being valuable to people who still legally own them;
- the emotional cost of winning freedom rather than receiving it as a menu
  reward;
- the power and danger of challenging forces that are much older than the
  player.

The player is not initially a chosen hero. They are a person reduced to a
ledger entry who becomes historically important through survival, decisions,
relationships, and deeds.

---

## 3. Design pillars

### 3.1 Readable tactical violence

Every important attack has a reason the player can understand. Enemy intent,
stance, range, stamina, posture, body position, and wounds must produce
decisions rather than opaque number changes.

### 3.2 Consequences that persist

Damage, choices, contracts, rivalries, reputation, faction standing, and
ethical decisions should outlive the individual turn whenever doing so creates
a meaningful future decision.

### 3.3 Depth through interaction

Depth comes from systems multiplying:

`combat → wounds → contracts → money/reputation → opportunities → relationships
→ legacy → postgame choices`

The game must not accumulate disconnected subsystems merely because they sound
impressive.

### 3.4 Terminal spectacle

The terminal is part of the fantasy. Text, colour, layout, particles, hitstop,
screen shake, banners, logs, animation frames, and carefully timed transitions
must make a fight feel physical without hiding the rules.

### 3.5 A world beyond the arena

The arena is the player's entry point into the wider Origins world. Factions,
gods, Mors, the Anomaly, politics, and family life must connect back to the
player's fighting career.

### 3.6 Agency without clean answers

The most important choices should offer competing costs, not a fake good
choice and a fake evil choice. The bargain and revenge routes are both
understandable and both dangerous.

---

## 4. Scope and delivery philosophy

### 4.1 Canonical scope

Gladiator will eventually contain:

1. a deep turn-based arena combat system;
2. a human gladiator career;
3. leagues, contracts, ownership, money, and freedom;
4. persistent wounds and body-part consequences;
5. rivals, factions, patrons, and a living arena world;
6. Mors and meaningful death/return consequences;
7. the post-freedom family and Mors-debt storyline;
8. bargain trials, revenge against the gods, and Lazi's later trials;
9. legacy-based possible godhood;
10. Anomaly and Origins lore.

### 4.2 Explicitly not first

These are not allowed to delay the first excellent fight:

- co-op or networking;
- a giant procedural item catalogue;
- every god and faction;
- a full city simulation;
- dozens of status effects;
- all postgame content;
- a complete world map;
- large amounts of decorative UI;
- a new shared-platform abstraction.

They remain possible later, but only after the core proof gates pass.

### 4.3 Implementation rule

All Gladiator work stays inside `games/gladiator/` unless a separate platform
change is explicitly approved. Editable content belongs in data modules;
simulation rules must remain testable independently of curses; terminal
presentation must respect the LAZSTATION contract.

---

## 5. Core game loop

### 5.1 Main career loop

```text
prepare
  → accept a bout or contract
  → scout/read the opponent
  → fight
  → record victory, defeat, wounds, reputation, and relationships
  → choose recovery/training/economic actions
  → manage owner/contract pressure
  → enter the next opportunity
```

### 5.2 Career arc

```text
property
  → survive the slave league
  → become valuable
  → earn or negotiate release
  → become free
  → establish a life and legacy
  → face the Mors debt
  → choose bargain or revenge
  → pursue trials or hunt gods
  → define a domain, remain mortal, or become something else
```

### 5.3 Moment-to-moment combat loop

```text
observe intent
  → choose positioning/stance/action
  → resolve commitment and consequence
  → read the new state
  → exploit, defend, recover, or retreat
```

---

## 6. Premise and world

The world rests on a fractured divine order. The gods are distant but their
institutions, laws, patrons, cults, armies, and grudges shape mortal life. The
Iron Duchy and other powers converted old sacred structures into prisons,
fortresses, and systems of control.

The Anomaly is older than the gods. It is not merely random chaos; it is a
reality-breaking presence that the gods attempted to contain and failed to
understand. Its influence should be discovered gradually, not explained in the
opening.

Mors is a real underworld ruled by a death god. It is a place with rules,
debts, residents, bargains, routes, and costs—not a generic game-over screen.

The arena is where these forces become visible to the player first. The
player's body is controlled by owners, while the arena turns that control into
public entertainment and political capital.

---

## 7. Story and lore structure

### 7.1 Surface layer

Available without lore hunting:

- food, healing, training, and money;
- owners and contracts;
- bouts, leagues, rules, and crowd expectations;
- injuries and recovery;
- named rivals;
- the immediate route to freedom.

### 7.2 Middle layer

Discovered through exploration, conversations, contracts, and arena history:

- the Iron Duchy;
- factions and patron gods;
- slave networks and resistance;
- arena politics;
- vanished fighters;
- Mors and its debts;
- the history of the player's owner and rivals.

### 7.3 Deep layer

For persistent investigators:

- the true nature of the Anomaly;
- why the gods fear or use it;
- why the player is an unusual variable;
- what “Unbound” means beyond legal freedom;
- the origin and purpose of Lazi's trials;
- whether divine order is containment, oppression, or both.

Lore must reward curiosity and never be required to understand the basic
combat/career loop.

---

## 8. The gladiator

The player controls one human gladiator. The character is not a fixed class
avatar. Their identity develops through:

- body and physical capability;
- weapon and armour choices;
- learned techniques;
- fighting habits;
- relationships;
- reputation;
- injuries;
- contracts;
- moral choices;
- the legacy they create after freedom.

### 8.1 Starting identity

The opening should establish:

- how the player became property;
- what they remember or do not remember;
- who currently controls their contract;
- what immediate survival requires;
- one personal thread that can grow into family, rivalry, or freedom.

The playable opening is a story tutorial rather than a setup menu. The player
is sold at auction, arrives in the slave chambers, claims a name, and builds a
starting profile in conversation with the chamber keeper. Height and a small
pool of physical and mental points establish initial capabilities, but never
select a permanent class. Chores teach the house, earn a small first purse,
and frame survival as work before it becomes spectacle.

In the dummy yard, the trainer offers the first weapon. This choice is made
inside the fiction after the profile exists, not before it. Weapons and
learned techniques define temporary fighting styles; a character can learn
across styles and has no locked class. The dummy lesson teaches movement,
attack, guard, focus, concealment, reloads, range, stamina, posture, and
wounds before the first living opponent.

The player may begin with an incomplete identity. This supports the Origins
theme that they are a variable the existing order did not account for.

### 8.2 Human scale

Early fights must make ordinary steel, fatigue, fear, and skill matter. Divine
or Anomaly power must feel earned and dangerous because it contrasts with this
starting scale.

---

## 9. Combat system

### 9.1 Combat identity

Gladiator is turn-based, tactical, and commitment-driven. It is not a
real-time action game with turns painted over it.

The core question is:

> **What is the opponent trying to make me do, and what am I willing to risk
> to punish it?**

The terminal equivalent of real-time combat is a short tactical exchange:

```text
read the immediate threat
  → choose a posture, position, and action
  → commit or react during the resolution window
  → watch the exchange animate
  → understand the changed battlefield
```

The combat model uses a compact grid as physical truth, with an initiative
timeline and commitment windows layered over it. This allows the game to have
real prediction, interruption, recovery, and counterplay without pretending
that keyboard input is real-time movement.

### 9.2 Required combat dimensions

The eventual combat model should support:

- arena/grid position and distance;
- initiative and tempo;
- stamina;
- attack commitment and recovery;
- readable intent/telegraphs;
- stances;
- guard/posture;
- weapon reach and properties;
- ranged weapons and projectile travel;
- armour and protection;
- targeted body locations;
- wounds that change available actions;
- environmental arena conditions;
- morale/crowd pressure where appropriate.

The exact rules must be specified and tested before broad content production.

### 9.3 Spatial model

The default arena is a compact **5x5 or 7x7 grid**. Special authored arenas
may be larger once the camera/viewport and minimum terminal layout are proven.
The grid determines:

- position and facing;
- line of sight;
- distance;
- weapon reach;
- threatened cells;
- escape routes;
- cover and hazards;
- whether stealth is possible.

The rules resolve exact cells and attack geometry. The interface also labels
distance in readable bands such as **adjacent**, **near**, **far**, and
**unreachable**, so the player does not need to count cells every turn.

### 9.4 Stances

Stance is a layered system:

1. **Universal posture** describes the fighter's current intent, such as
   pressure, guard, mobile footwork, recovery, concealment, or commitment.
2. **Weapon style** describes what the equipped weapon can do from that
   posture, such as spear control, shield binding, greatweapon commitment,
   dagger entry, or net control.

Ordinary stance changes are quick. Entering a powerful, concealed, braced, or
high-commitment state costs tempo or stamina and can be punished. Stances must
change the threat map, available reactions, exposed body locations, and
recovery rules—not merely apply flat percentage bonuses.

### 9.5 Range

Range uses exact grid distance and weapon geometry underneath a readable
distance-band interface. Attacks should preview or clearly describe:

- the cells they can reach;
- the cells they threaten;
- whether line of sight is blocked;
- whether the attack controls, pushes, pulls, or passes through a space;
- what a stance changes about that geometry.

Range is a first-class combat axis, not a melee-only measurement. A ranged
fighter and a melee fighter should be making different decisions every turn,
not using the same attack rules with different numbers.

### 9.5.1 Ranged combat

Ranged weapons may include bows, slings, javelins, thrown weapons, and later
setting-specific or divine weapons. Each ranged attack must define:

- projectile path or attack geometry;
- travel time and initiative position;
- ammunition, reload, draw, or preparation requirements;
- minimum and optimal range;
- accuracy and precision rules;
- noise and visibility consequences;
- interaction with cover, shields, armour, and obstacles;
- what happens if the target moves before impact;
- what melee pressure does to the attacker's options.

The terminal should show a projectile's threatened line or cells before the
player commits. A fired projectile may resolve later in the initiative
timeline, allowing the target to move, take cover, intercept it, or deliberately
remain in the line to bait a follow-up. A fast close-range shot and a slow
fully drawn shot must create different tactical risks.

Ranged combat must have a real resource and positioning economy:

- ammunition or recoverable projectiles limit repeated safe attacks;
- draw/reload actions create commitment windows;
- long range improves safety but reduces reliability or impact;
- close range can improve damage but exposes the shooter to melee pressure;
- moving, turning, concealing, and firing compete for tempo;
- a wounded arm, hand, eye, or shoulder changes ranged options;
- losing line of sight can protect the target while also allowing repositioning.

### 9.5.2 Melee answers to ranged pressure

Melee fighters need deliberate counterplay rather than a passive damage race.
Depending on weapon, stance, and arena, they may:

- advance behind cover;
- sprint or commit to a closing line;
- raise a shield or guard a projected body location;
- deflect or intercept a projectile;
- use smoke, dust, darkness, crowd movement, or terrain;
- throw a weapon or use a short-range attack;
- force the ranged fighter into a corner or bad angle;
- punish the draw/reload/recovery window;
- use stealth and broken sightlines to approach.

Ranged fighters likewise need counterplay against a successful approach:

- retreat and reposition;
- switch to a sidearm;
- create distance with a push, trap, or movement technique;
- use cover and overwatch;
- fire a delayed or area-denial attack;
- accept a weaker close-range shot to preserve a better escape.

The game should support at least three distinct ranged identities before
content breadth expands:

1. **Skirmisher:** mobile, short-to-medium range, repositioning and thrown
   weapons.
2. **Marksman:** deliberate draw/reload commitment, precision targeting, high
   payoff, vulnerable if pressured.
3. **Controller:** javelins, nets, traps, smoke, or area denial that shape
   movement more than raw damage.

These are styles, not mandatory character classes. A player may combine
ranged and melee tools, but carrying both should create weight, preparation,
and opportunity costs.

### 9.6 Stealth and concealment

Stealth is a universal tactical layer, while an assassin is a full combat
style built around it.

Any fighter may use line-of-sight breaks, dust, darkness, crowd noise, cover,
feints, or concealment postures to hide position or intent. Assassin styles
specialize in:

- approach and disengagement;
- hidden attack direction;
- marks and weak-point attacks;
- decoys and false intent;
- precision targeting;
- execution windows.

Stealth is not permanent invisibility. It breaks when the fighter attacks,
makes excessive noise, enters exposed space, is tracked, or is correctly
predicted. Opponents have counterplay through searching, listening,
area attacks, guarding exits, lighting the arena, and forcing open-ground
engagements.

### 9.7 Timeline and commitment

Combat uses a hybrid timeline:

- immediate enemy intent is readable;
- later actions are uncertain;
- scouting, perception, stance, and stealth alter what can be known;
- speed, weapon weight, wounds, and stamina influence resolution order.

Every action has a visible commitment phase. The default rules allow limited
cancels, interrupts, and reactions based on stance, weapon, and resources.
Agile styles cancel more easily; heavy styles gain power by accepting stronger
commitment and recovery risk.

Major exchanges create a short commitment window in which the player may
change geometry, guard a body part, evade, bind, interrupt, or counter at a
cost. The player should feel responsible for a read, not punished by an
unexplained random animation.

### 9.8 Reaction layer

When a telegraphed attack is about to resolve, the player may have several
valid answers:

- move out of the attack geometry;
- close distance or force a bad angle;
- guard a specific body part;
- bind or deflect the weapon;
- interrupt the wind-up;
- evade into a better cell;
- take a lesser hit to create a counter;
- accept the attack and preserve a more important resource.

No reaction is universally correct. The right answer depends on range, stance,
weapon, posture, stamina, focus, wounds, arena geometry, and what the opponent
is trying to force.

### 9.9 Combat resources

The combat model uses three resources with distinct jobs:

- **Stamina:** physical effort for attacks, movement, defence, recovery, and
  demanding weapon techniques.
- **Posture:** balance and structural control; it represents guard, stagger,
  exposure, bracing, and the ability to remain dangerous under pressure.
- **Focus:** perception and precision; it supports reads, concealment, counters,
  deliberate targeting, and assassin techniques.

Focus follows a hybrid economy. Observation and correct reads rebuild it;
powerful precision, concealment, and counter actions spend it. A player cannot
simply wait for focus to refill without making tactical choices.

The HUD must show these as visibly different concepts. If playtesting shows
that three resources create more bookkeeping than decisions, one may be
compressed or derived without discarding the underlying combat purpose.

### 9.10 Body targeting

Ordinary attacks resolve likely body locations through geometry, stance,
weapon, and technique profiles. Precision actions can spend resources to
explicitly target the head, arm, torso, or leg.

This keeps normal turns fast while making deliberate targeting a meaningful
investment. Targeting must connect to:

- current posture and guard;
- armour and weapon interaction;
- immediate combat effects;
- persistent injury thresholds;
- later action availability.

### 9.11 Action categories

The initial action grammar should include:

- light attack;
- committed/heavy attack;
- defend/guard;
- reposition/footwork;
- feint;
- taunt or crowd play;
- weapon-specific technique;
- yield/retreat where the rules allow it.

Each action must state:

- stamina cost;
- timing/priority;
- range;
- accuracy or resolution rule;
- posture/guard effect;
- body-part exposure;
- possible counterplay;
- terminal feedback.

### 9.12 Intent and readable opponents

Opponents must expose enough information for skillful decisions without
revealing every hidden variable. Intent may be shown through:

- stance;
- named wind-up;
- weapon position;
- movement direction;
- fatigue;
- a short event-feed line;
- a one-frame or multi-frame animation.

Bosses and elite opponents may obscure or manipulate information, but their
patterns must remain learnable.

### 9.13 Opponent intelligence

Opponents use three layers of intelligence:

1. **Patterned baseline:** each enemy has a learnable style and routine.
2. **Reactive decisions:** the enemy observes stance, wounds, range,
   resources, and repeated player habits.
3. **Persistent rival memory:** named opponents remember prior fights and can
   evolve across the player's career.

Adaptation must remain explainable. The player should be able to identify
which habit was read, which counter was selected, and what new behaviour they
can test next.

### 9.14 Arena interaction

Position is always meaningful. Selected authored arenas may add:

- cover and blind corners;
- pillars, walls, gates, or elevation;
- destructible objects;
- sand, fire, traps, or weather;
- crowd and official events;
- beasts or environmental threats.

Arena rules should be introduced as legible tactical features, not random
noise. A special arena must create a decision that would not exist on a plain
floor.

### 9.15 Injuries

Damage is tracked separately from win/loss. A victorious fighter can leave the
arena more damaged than the loser.

Initial body locations:

| Location | Example persistent consequence |
|---|---|
| Arm | reduced two-handed options, weaker parries or weapon control |
| Leg | reduced repositioning, worse escape options, altered reach control |
| Ribs | increased cost or severity of later hits |
| Head | less reliable reads, increased stagger or confusion risk |

Injury rules must be deterministic enough to explain after a fight:

`hit location + impact + armour + guard + accumulated trauma → wound state`

No injury system ships until a wounded state changes the next combat decision
in a visible, testable way.

### 9.16 Combat feedback

The game should use:

- hitstop for major impacts;
- screen shake scaled to impact;
- sparks/particles;
- colour-coded damage and status feedback;
- readable combat log;
- brief banners for decisive events;
- animation frames that never obscure the actual state.

Presentation is subordinate to rules. A spectacular effect that makes the
result unclear is a defect.

---

## 10. Career, leagues, and freedom

### 10.1 League structure

The intended long arc is:

```text
slave league → club league → elite Unbound league → freedom/legacy
```

Exact league names and promotion rules remain content decisions, but every
promotion must change more than enemy numbers. It should alter:

- contract value;
- opponent quality and style;
- political attention;
- available trainers and equipment;
- crowd expectations;
- injury/recovery pressure;
- faction opportunities.

### 10.2 Contracts and ownership

Contracts answer:

- who owns or sponsors the fighter;
- how long the obligation lasts;
- what the purse and cut are;
- what happens after a loss;
- what freedom costs;
- what risks the owner can impose;
- whether the player can negotiate, escape, or exploit the contract.

The player's buyout/freedom value must be visible and change through play.

### 10.3 Reputation

Reputation is not one universal score. At minimum, the design should
distinguish:

- crowd fame;
- owner confidence;
- league standing;
- faction standing;
- personal relationships;
- fear/respect among rivals.

The implementation may begin with fewer values, but each value must create a
different decision before it is added.

### 10.4 Recovery and preparation

Between bouts the player chooses how to spend limited resources:

- heal;
- train;
- repair or improve equipment;
- work a contract;
- scout an opponent;
- build relationships;
- rest and lose opportunity;
- fight while injured.

“Heal” must not be a meaningless wait button. Recovery needs an opportunity
cost, a resource cost, or a timing consequence.

---

## 11. World, factions, and gods

Factions should represent competing answers to power and freedom. Initial
examples from the wider Origins material include:

- a military/order faction;
- an information/shadow faction;
- a merchant/pragmatist faction;
- a divine/judgment faction;
- later, resistance or Anomaly-aligned groups.

These are candidate structures, not locked names or final content.

Factions may affect:

- contracts and opponents;
- training and equipment;
- healing;
- legal protection;
- arena access;
- information;
- Mors routes;
- postgame allies and enemies.

Gods should initially appear through consequences, patrons, omens, laws,
champions, and faction interests. Direct god confrontations belong to the
postgame unless the design proves an earlier encounter is necessary.

---

## 12. Death and Mors

Death must carry consequences without becoming arbitrary.

Mors is intended to become a playable layer later, containing:

- a death god and underworld rules;
- debts and bargains;
- routes back to the overworld;
- trials or fights scaled to the player's life;
- unique knowledge and resources;
- permanent or run-level costs for staying too long.

The first implementation should not attempt the full underworld. It should
first establish a clear, testable death state and preserve enough save data
to expand into Mors without corrupting old careers.

---

## 13. Post-freedom family and Mors debt

Freedom is a transition, not the final ending.

### 13.1 Family

Depending on player choices and timing, the gladiator may have a spouse and a
first child before or after freedom. The game should support both:

- a child born during the career, creating pressure while the player is still
  property;
- a child born after freedom, making the post-freedom arc feel like a second
  life.

### 13.2 Mors debt activation

The debt remains dormant until the player has a first child. Once the condition
is met, Mors claims the child as the consequence of the player's earlier
relationship with death and return.

The claim must be foreshadowed and then presented as an explicit choice, not
silently forced:

```text
accept Mors's bargain → trials to recover the child
reject the bargain → revenge against the gods
```

The child is a hostage at this stage. They are not reduced to a passive
reward forever; later writing must preserve their personhood and presence.

### 13.3 Timeskip

The transition into the post-freedom chapter depends on the player's chosen
life:

- a mortal life emphasizes family, community, and vulnerability;
- ruling emphasizes law, politics, succession, and enemies;
- rejecting the gods emphasizes isolation, resistance, and divine retaliation.

The timeskip should be represented as a chapter transition with branch-aware
history, not as a fully simulated thirty-year calendar unless later testing
proves that playable years create better decisions.

---

## 14. The bargain route: impossible trials

The bargain route offers a chance to recover the child, but every trial should
ask what the player is willing to lose.

### 14.1 Trial types

The mixed campaign may contain:

- tactical battles against mythic enemies such as cyclopes;
- assassination or protection assignments;
- oracle rescue and escort operations;
- multi-stage puzzles;
- relic, armour, or weapon hunts;
- investigations into divine weaknesses;
- bargains with entities that alter future rules;
- moral decisions that affect humanity, followers, and endings.

### 14.2 Moral trial principle

A trial can be a death sentence, but it must be legible:

- the player understands the stakes;
- alternatives exist, even if they are harder;
- the consequence is recorded;
- later content reflects the decision;
- the game does not label one answer as objectively correct.

Example: Mors orders the player to assassinate a child prince from a nation
the death god despises. The child resembles the player's own child. The
player may obey, refuse, deceive Mors, find another route, or accept a
different cost. The system must support more than a binary morality popup.

### 14.3 Recovery outcome

Completing the bargain route can return the child, but it should not reset the
player to an unmarked state. Trials may alter:

- humanity;
- reputation;
- relationships;
- follower belief;
- divine attention;
- equipment;
- the player's understanding of the Anomaly.

---

## 15. Revenge route: hunt the gods

Rejecting the bargain makes the gods active enemies.

The revenge route is not a linear boss list. The player must build the means
to challenge powers that are initially beyond them through:

- mythic weapons and armour;
- forbidden knowledge;
- oracle alliances;
- faction support;
- divine weakness research;
- relic puzzles;
- assassination, sabotage, and political disruption;
- tactical battles against champions and monsters;
- decisions about which gods to confront and in what order.

The gods retaliate. Refusing their terms should change the world:

- hunters and champions pursue the player;
- contracts become harder or more valuable;
- allies are pressured;
- safe locations become compromised;
- divine factions attempt to rewrite the player's public story.

### 15.1 Revenge-specific godhood

The revenge path can lead to godhood by defeating or displacing gods and
claiming a domain. Its central danger is becoming the same kind of power the
player opposed.

Possible revenge outcomes include:

- destroy the responsible gods and remain mortal;
- rule through a new human order;
- claim a divine domain and become what was hated;
- fail, be killed, or lose the child;
- uncover a third truth about Mors and the Anomaly later.

---

## 16. Lazi trials and possible godhood

Lazi is foreshadowed throughout the game through signs, fragments,
impossible interventions, and conflicting stories.

After the child is recovered through the bargain route, Lazi's second-tier
trials become available.

### 16.1 Purpose

The trials have two connected purposes:

1. test whether a mortal can hold immense power without becoming a tyrant;
2. prepare a counterweight or successor capable of confronting failed gods and
   the Anomaly.

### 16.2 Structure

The Lazi trials are a mixed campaign:

- some are combat trials;
- some are difficult puzzles;
- some are moral/philosophical tests;
- some combine all three;
- each should leave a lasting mark on the player's legacy.

### 16.3 Reward

Completing the trials grants **power without automatic divinity**. It may
provide:

- extraordinary abilities;
- forbidden knowledge;
- access to impossible places;
- protection against divine power;
- authority and followers;
- a new relationship to the Anomaly.

The player must still create a lasting legacy to become a god.

### 16.4 Domain-based godhood

Godhood requires both:

- **deeds** that define and prove a domain;
- **followers** who recognize, follow, or believe in the player through that
  domain.

Possible domains include freedom, war, endurance, mercy, rebellion, justice,
death, protection, or a player-shaped alternative. The chosen domain must
change the ending and the world response.

Remaining mortal is a valid success state. So is ruling without divinity.

---

## 17. Terminal UX and presentation

### 17.1 Contract constraints

Gladiator is a full-screen LAZSTATION game:

- use the SDK's curses bezel helpers;
- draw inside the picture area;
- budget against the 80x24 minimum;
- handle resize;
- keep rules independent of curses;
- persist through `TERMSTATION_SAVE_DIR`;
- exit `0` on clean completion and `130` on Ctrl-C;
- never write outside `games/gladiator/` for game-specific work.

### 17.2 Combat screen

The minimum combat HUD should make these readable without hunting:

- player health and stamina;
- opponent identity, health, stance, and intent;
- position/range;
- active wounds and guard/posture;
- current round/turn;
- recent event log;
- legal actions and their costs.

### 17.3 Animation rules

Animation is feedback, not a separate simulation. Every effect must:

- be short enough not to make turns feel sluggish;
- be skippable or bounded where appropriate;
- preserve the resulting state in the log/HUD;
- render safely at minimum dimensions;
- be testable through PTY snapshots or deterministic frame checks.

---

## 18. Data and save architecture

### 18.1 Data-driven content

Editable data should eventually be separated from rules:

- fighters and opponents;
- weapons and armour;
- techniques;
- arenas and conditions;
- leagues and contracts;
- factions and gods;
- lore entries;
- trials and puzzles;
- family/relationship content.

Content authors must be able to redirect names, descriptions, stats, and
encounter data without rewriting simulation rules.

### 18.2 Save requirements

Saves must include a version integer and tolerate additive defaults. They must
preserve:

- career identity;
- current league and contract;
- combat progression;
- wounds and recovery;
- money and reputation;
- relationships;
- discovered lore;
- faction standing;
- Mors debt flags;
- family/timeskip state;
- postgame route;
- trial choices and consequences;
- legacy/domain/follower progress.

No new field may be assumed to exist in an older save.

### 18.3 Save invariants

- clean exits save;
- Ctrl-C saves safely where possible;
- invalid or partial values are handled explicitly;
- a failed bout does not silently erase unrelated progress;
- deterministic seeds/records can reproduce rule outcomes where required;
- `_summary` remains within LAZSTATION's display limit.

---

## 19. Verification gates

No major system is complete until it has evidence at the correct layer.

### Gate A — combat rules

- action costs and legality;
- initiative/priority;
- stamina;
- guard/posture;
- damage;
- intent and counterplay;
- body location;
- wound creation;
- wound effects on subsequent actions;
- win/loss/yield.

### Gate B — one complete fight

- a real fight works at 80x24 and 110x30;
- the player can understand why damage occurred;
- at least one injury changes the next decision;
- animation does not corrupt layout;
- no traceback or terminal-state leak.

### Gate C — persistence

- save/load roundtrip;
- additive migration;
- wound persistence;
- career progression;
- interrupted/clean exit behavior.

### Gate D — career slice

- multiple bouts;
- recovery decision with an opportunity cost;
- money/purse;
- reputation/contract consequence;
- a named rival or recurring opponent;
- meaningful failure state.

### Gate E — freedom transition

- the freedom condition is visible;
- the player can reach and understand the transition;
- legacy state is preserved;
- branch-aware timeskip data can load.

### Gate F — postgame vertical slice

- first child can be created through a tested path;
- Mors debt activates only under the intended condition;
- explicit bargain/revenge choice persists;
- one bargain trial and one revenge operation work;
- consequences are visible in later state.

### Gate G — trials and godhood

- Lazi trials unlock only after the correct route;
- combat, puzzle, and moral trial results persist;
- power is not automatically converted into godhood;
- deeds and followers can be measured;
- domain selection changes the ending.

### Required commands

At minimum, each implementation slice should use the smallest applicable set
of:

```text
python3 -m unittest ...
python3 tools/ptytest.py ...
./bin/lazstation doctor
git diff --check
```

The exact test modules and scenarios must be added with the implementation,
not invented after the fact.

---

## 20. Phased roadmap

### Phase 0 — preserve and baseline

- record current Gladiator behavior;
- add headless rule boundaries around the existing combat;
- document current save shape and terminal behavior;
- keep the current prototype playable.

### Phase 1 — defining fight

- introduce a real turn/action model;
- establish intent, position, stamina, guard, and body locations;
- implement one opponent with a readable pattern;
- prove a wound changes the same fight.

### Phase 2 — persistent fighter

- persist wounds across fights;
- add weapons/armour/techniques in a small data-driven set;
- add recovery choices and costs;
- add deterministic rule tests and PTY scenarios.

### Phase 3 — career

- leagues;
- contracts and ownership;
- purses, buyout/freedom value, and reputation;
- recurring rivals;
- training, scouting, and faction hooks.

### Phase 4 — world and Mors foundation

- named factions and patrons;
- lore discovery;
- explicit death state;
- first playable Mors interaction;
- safe versioned migration.

### Phase 5 — freedom and legacy

- freedom transition;
- spouse/family paths;
- branch-aware timeskip;
- first child state;
- Mors debt foreshadowing and activation.

### Phase 6 — bargain/revenge postgame

- explicit route choice;
- one complete bargain trial;
- one complete revenge operation;
- god retaliation;
- child recovery/failure consequences.

### Phase 7 — Lazi and legacy godhood

- Lazi foreshadowing and reveal;
- mixed Lazi trials;
- followers/deeds/domain tracking;
- mortal, ruler, revenge-godhood, and other endings.

### Phase 8 — breadth and polish

- additional leagues, arenas, gods, factions, trials, puzzles, enemies,
  equipment, lore, and endgame variations;
- only after earlier gates remain green.

---

## 21. Open design questions

These are intentionally unresolved and must be answered before the relevant
phase, not guessed into early code:

- exact turn/grid geometry;
- deterministic versus seeded randomness boundaries;
- precise body-part damage model;
- how ownership and legal freedom work numerically;
- exact league count and promotion conditions;
- which gods are original canon and which are only placeholders;
- the death god's final name and personality;
- the jealous goddess's final name and motive;
- what the player remembers at the opening;
- whether Mors debt is created by a specific first return or a broader history;
- how much of the timeskip is simulated versus summarized;
- how followers are represented without reducing belief to a single popularity
  bar;
- which domains are available and how player-created domains are bounded;
- whether revenge and bargain routes can reconnect after their first major arc.

---

## 22. Non-negotiable design tests

Before adding a system, ask:

1. What decision does this create?
2. What existing system does it interact with?
3. What can the player observe?
4. What happens when the player fails?
5. How is it represented in a terminal?
6. How is it saved and migrated?
7. What deterministic or scenario test proves it works?
8. Can the game explain the outcome after it happens?

If a feature cannot answer these questions, it remains a brainstorm note, not
an implementation requirement.
