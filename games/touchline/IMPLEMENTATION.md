# Ekse Slaan Ball — implementation work plan

**Created:** 24 September 2026.
**Status:** planned work only; no package below has started or passed its gate.
**Reviewed baseline:** `c13466e`, game 0.2.0, plus the personality-development design update in this planning change.

Read [DESIGN.md](DESIGN.md) for product behavior and [ROADMAP.md](ROADMAP.md) for milestone acceptance. This document specifies how to reach those outcomes without turning the whole design into one rewrite. Package IDs are stable; update status and evidence after each delivery. Do not mark progress from the presence of scaffolding alone.

## 1. Execution decisions

1. Preserve the current playable career while a new match engine is developed under game-local modules. Experimental scenarios use separate save locations and cannot overwrite careers.
2. Use the existing Python runtime and standard library first. No dependency installation, shared SDK edits or platform rewrite is a prerequisite for the initial prototype.
3. Introduce only the data/contracts needed by the next packages. Avoid building empty implementations for every eventual staff role or competition.
4. Establish identity, time, units, reproducible randomness and observation boundaries early. Add rich behavior incrementally behind those contracts.
5. Establish a small working loop before expanding scope: select distinct players → define coordinated behavior → simulate → inspect events → adjust → repeat.
6. Use individual commits for coherent verified packages or smaller slices. Plans, tests and handoffs must identify what remains unsupported.
7. The first implementation assignment is P00 only. Proceed into subsequent packages when included in the active implementation scope; do not silently turn a bounded assignment into all seventeen packages.

### Game-folder organisation decision

The game brief's instruction to put rules in `main.py` conflicts with the agreed need to separate a much larger simulation. At P00, record the bounded exception in a game-local architecture note: `main.py` remains the launch entry point; rules live in game-local modules; authored content stays separate and editable. Preserve every other console contract. This is an ordinary technical reconciliation of the accepted architecture, not a reason to request another broad approval or modify shared files.

Keep the current entry point intact until integration. Introduce a uniquely named package such as `esb/` inside `games/touchline/`, rather than generic top-level modules that collide with other games. The exact file split can adapt to evidence; the following responsibilities must remain distinguishable:

| Area | Responsibility | Introduce |
|---|---|---|
| `esb/model.py`, `esb/time.py`, `esb/randomness.py` | Typed records, stable identities, clock and reproducible random streams. | P01–P02 |
| `esb/match/` | Motion, ball, decisions, rules, events and match progression. | P03–P06 |
| `esb/tactics/` | Validated instructions, relationships, conditions and routines. | P02–P07 |
| `esb/people/` | Capability, readiness, development, identity and relationships. | P02, P09, P13 |
| `esb/knowledge/` | Observations, reports, metrics and club-specific views. | P10–P11 |
| `esb/club/` | Appointments, staff work, governance, policies and communication. | P12–P14 |
| `esb/economy/` | Agreements, obligations, ledger and market decisions. | P15 |
| `esb/world/` | Calendar, competitions and career progression. | P08–P09, P16 |
| `esb/persistence.py`, `esb/presentation/` | Save adapters and terminal rendering/navigation. | P07–P08 onward |
| Data/scenario modules | Original content, archetypes, rules and proof setups with editing comments. | As needed |

The current `content.py`, `tideway.py`, `test_game.py` and manual remain valid until a deliberate integration replaces their responsibilities. Do not create the entire tree in P00.

## 2. Dependency order and playable checkpoints

```text
P00 baseline → P01 contracts → P02 player/tactic records
    → P03 movement → P04 possession → P05 match rules → P06 tactical proofs
    → P07 playable laboratory → P08 career integration → P09 preparation/health
    → P10 observations → P11 scouting/analysis → P12 authority/staff
    → P13 player life/culture → P14 media → P15 market/economy
    → P16 long careers/competition proofs
```

This is the recommended single-writer delivery order, not a request to run agents concurrently. P12/P15 may later be split further if their scope requires it; retain the command/authority boundaries already defined in P01.

| Checkpoint | What can actually be used |
|---|---|
| P00 | Existing game with a documented, reproducible baseline and known failures. |
| P06 | Headless tactical scenarios with inspectable recorded traces. |
| P07 | A terminal laboratory where the user can change players/instructions and inspect the result. |
| P09 | A career matchweek with selection, preparation, injuries, match decisions and persistent consequences. |
| P11 | Evidence-limited recruitment and opposition analysis that informs a real decision. |
| P14 | A club staffed by distinct people, with policies, evolving relationships and selective media interaction. |
| P16 | A connected long-career proof with contracts, finances and flexible competition relationships. |

## 3. Initial engineering packages

### P00 — baseline, constraints and evidence (F0)

**Dependencies:** none. **Scope:** inspection, baseline tests, benchmark harness and game-local architecture/verification notes.

- Re-read local instructions, game brief, design, actual code and Git state. Do not assume the platform's uncommitted files are ours to stage.
- Record current version, entry point, save schema, import requirements and the shared UI dependency. The working tree currently has an untracked `sdk/termstation_ui.py`; do not claim a clean checkout is self-contained until its ownership/integration is resolved. Leave that file untouched and record the dependency.
- Run existing game tests and one isolated season path at both required terminal sizes. Record actual outcomes, including failures. `doctor` validates manifests, not simulation realism.
- Capture version-2 save fixtures from synthetic careers: fresh, in-progress match, midseason and completed season. Store small purpose-built fixtures without user career data.
- Add a game-local benchmark command recording environment, dataset, seed, wall time and output size for current matches/seasons. Baselines describe current behavior, not targets for realism.
- Record integrity work items with reproductions: unavailable-player fallback, expiry without release, user-only season prize, incomplete added-division history, and mixed curses/direct-ANSI rendering. Do not repair unrelated platform behavior in this package.
- Write the module boundary decision and choose a reproducible test command for the new package.

**Exit:** another developer can reproduce the baseline, identify known failures and understand the next package without conversation history. No gameplay regression or career save rewrite is introduced.

**Planned verification:** existing `python3 -m unittest games.touchline.test_game`; existing season scenario through `tools/ptytest.py`; `lazstation doctor` with isolated writable data directories; fixture/content validation; `git diff --check`. Confirm command prerequisites rather than silently masking import failures.

### P01 — shared contracts, time and reproducibility (F0)

**Dependencies:** P00. **Deliver:** minimal typed records and pure command/event interfaces, with serialization tests.

- Stable player/club/match/event IDs; explicit match time versus world date; units for positions, time, money and measurements.
- Separate immutable player capability snapshots, mutable match state, career state and club knowledge.
- Named deterministic random streams for football actions, world events and reporting. UI rendering and report generation cannot consume football randomness.
- A versioned event envelope with cause/parent IDs and recorded outcomes. A command validates before it changes state.
- Contracts for scheduled work and once-only settlement, without implementing an entire calendar or ledger.
- Reserved records for identity, experience, preference and culture histories; do not fill them with fabricated prior life events.

**Exit:** round-trip serialization and interrupted/resumed synthetic updates are identical. Invalid inputs fail before partial mutation. Importing domain code does not initialise curses, read saves or write awards.

### P02 — distinct players and editable tactical intentions (F1)

**Dependencies:** P01. **Deliver:** a small authored proof roster and validated tactical definitions.

- Author enough balanced squad depth for 11v11 scenarios, substitutions and contrasting profiles. Include differences in acceleration, anticipation, receiving, distribution, aerial execution and goalkeeper behavior; avoid deriving everything from overall ability.
- Represent preferred foot, physical facts, supported capabilities, current readiness and action tendencies separately. Define units and meaningful bounds.
- Define phase anchors, relative positioning, individual intentions, coordinated relationships and pressing/marking assignments. Conditions/routines are data with priorities, expiry and fallback.
- Validate illegal or contradictory data and surface explainable warnings. Do not implement a complex UI yet.
- Give generation/imported legacy data provenance: inferred fields are not historical measured facts.

**Exit:** fixtures can express the agreed proof tactics and individual differences without an engine-specific preset bonus. Profiles remain distinct after serialization. Definitions have precise intended behavior ready for P03–P06 tests.

### P03 — motion, ball flight and receiving (F1)

**Dependencies:** P02. **Deliver:** deterministic physical/action primitives with replayable small scenarios.

- Player movement, turning, acceleration and bounded travel; ball ground/air travel, height, bounce and settling.
- Driven/chipped/floated passes with travel time, intended receiver/area and plausible execution error.
- Receiving orientation, first touch and reachable interception windows. Support controlled knockdowns and uncontrolled deflections.
- Simultaneous intent evaluation from a shared snapshot, then deterministic resolution of contested outcomes. Avoid array order deciding who reaches the ball.
- Prototype an adjustable fixed simulation step; compare results/performance at several resolutions before choosing a default. UI frame rate stays unrelated.

**Exit:** physical invariants hold; legal interception depends on arrival/height/time; player order and pitch mirroring do not create systematic advantages. Simple traces explain why a receiver controlled or lost the ball.

### P04 — continuous possession and player decisions (F1)

**Dependencies:** P03. **Deliver:** contested open play with perceivable choices and persistent possession.

- Perception and feasible-action generation separated from action choice and execution.
- Support movement, carries, passes, pressure, challenges, shots and goalkeeper responses using actual local state.
- Regains, deflections and rebounds continue from the resulting positions. Preserve pass/assist lineage and chronological events.
- Record actual options and actions for developer inspection; expose only observable information to player-facing traces.
- Introduce baseline shot-quality estimates separately from finishing/goalkeeping execution; label them provisional until calibrated.

**Exit:** controlled player changes affect the intended part of the action chain. A better decision-maker can choose a better option without receiving an unexplained technique boost. Scores and core event statistics reconcile.

### P05 — rules, restarts and complete matches (F1–F2)

**Dependencies:** P04. **Deliver:** a rules-complete small-world match without a management UI.

- Kickoffs, throw-ins, goal kicks, corners, free kicks, penalties, offside, fouls, advantage, cards and substitutions.
- Clock, stoppage, half-time, ending conditions and configurable extra time/shootouts.
- Legal starting positions and restart transitions; designated players and fallbacks if they become unavailable.
- Availability, substitution history, reduced teams and keeper replacement. Resolve undersized squads through explicit rules, never by silently selecting injured players.
- Shared full-match simulation and replay output. No old-engine probability fallback inside an otherwise spatial match.

**Exit:** fixtures complete or report a valid exceptional outcome; event order, goals, assists, minutes, eligibility and restarts reconcile. Save/resume works at a restart and during open play.

### P06 — coordinated tactics and counterplay proofs (F1)

**Dependencies:** P05. **Deliver:** proof suite, repeated-run reports and example tactics assembled from shared components.

- Finish unit movement, cover shadows, tracking/handover, pressing support, transition recovery and conditional rule arbitration.
- Implement positional-possession, aggressive man-oriented pressing and kickoff-to-throw-in trapping scenarios with successful and failed execution.
- Add compact block/counter, direct second-ball, fluid-combination, vertical-combination, wide-isolation and spare-defender scenarios in separate small slices.
- Add match objectives and opposing responses based on observed state; represent a response's preparation and communication costs.
- Evaluate several player profiles and opponents for each tactic. Include an unfamiliar custom combination to check composability.

**Exit:** recorded movement establishes that the tactic happened; statistical sweeps show trade-offs rather than guaranteeing particular match winners. Successful attacks are not sufficient evidence if the intended mechanism never occurred.

## 4. Playable and management packages

These packages retain bounded deliverables but should be refined at their entry using evidence from the initial engine. Do not prematurely freeze every screen or formula.

| Package | Dependencies / milestone | Deliverable | Completion evidence |
|---|---|---|---|
| P07 Tactical laboratory | P06 / F2 | Game-local scenario launcher, player selection, instruction editing, timeline/positional replay, saved tactics and repeatable experiments. | A user changes an instruction, inspects the observed effect and repeats a trial; 80×24/110×30 borders, resize and keyboard navigation pass. |
| P08 Career integration and migration | P07 / F2 | Match adapter, settlement adapter, versioned saves and integration with the current two-tier career; all fixtures use a documented engine version. | Managed/quick outcomes agree; settlement occurs once; old saves migrate safely; paused legacy matches retain their original resolution rules. |
| P09 Preparation, health and learning | P08 / F2 | Calendar dates, training/recovery allocation, readiness, medical histories, exposure-based risk, rehabilitation and unit learning. | A congested week requires meaningful selection decisions; cleared differs from match-ready; no unavailable-player fallback or repeated per-render injury draws. |
| P10 Observation infrastructure | P09 / F3 | Club coverage/access, reports with provenance, staff assignment capacity, stable uncertainty and a metric registry. | Same match produces different legitimate club knowledge; missing/repeated/stale evidence cannot become exact hidden truth. |
| P11 Scouting and analysis desk | P10 / F3 | Role-specific searches, comparisons, recruitment dossier, opposition briefing, evidence replay and resilience/compatibility review. | A report changes a real selection or recruitment recommendation; metrics retain denominator/cohort/context; small samples and disagreement remain visible. |
| P12 Authority and working staff | P11 / F4 | Appointments, owner/board roles, head-coach/manager mandates, budgets, tasks, delegation and attributable decisions. | Same decision follows legitimate different routes under two roles; combined staff functions support small clubs; domain commands enforce authority. |
| P13 Player lives and evolving culture | P12 / F4 | Relationship/memory updates, preferences, settlement, policies, private conversations, sparse milestones, mentorship and gradual habit/value development. | Academy-to-mentor scenario and alternatives survive multiple seasons/save boundaries; identity does not collapse into obedience or age bonuses. |
| P14 Public attention and communication | P13 / F4 | Fictional outlets/accounts, sourced stories, exposure, transcripts, press staff and responses linked to relationships. | Reposts cannot multiply penalties; words/promises match transcripts; local/elite exposure differs; useful delegation and quiet weeks exist. |
| P15 Market and club economy | P14 / F5 | Contract dates, renewal/expiry, agent interests, timed offers, loans, scheduled obligations, ledger, forecasts and AI squad planning. | One recruitment-to-season-end path reconciles sporting, people and financial effects; no duplicated ownership, obligations or free-agent transfer fees. |
| P16 Sustainable careers and competition proofs | P15 / F6 | Intake/development/retirement, staff/manager moves, culture succession, archives and small synthetic multi-competition scenarios. | Long-run viability, qualification/call-up integrity, predictable save growth and measured performance before world expansion. |

P13 sub-slices: private identity/state/memory first; working policies and settlement next; leadership/mentorship development last. P15 sub-slices: ledger/obligations and expiry first; negotiations and agency second; loans and integrated AI recruitment third. Each sub-slice needs a working scenario, not disconnected screens.

## 5. Player evolution implementation contract

Use longitudinal records with at least player ID, experience ID/date, context, participating people, observed behavior, appraisal and affected habit/value dimensions. Keep underlying state, historical state and observers' reports distinct.

Update at appropriate world-time boundaries from accumulated meaningful experience. Resolve each experience once, with bounded changes, consolidation and possible decay. A daily update must not accelerate development just because the user opened a screen repeatedly. A save resumed after many steps must produce the same history.

Leadership combines demonstrated conduct, communication, role opportunities and teammates' directed trust. Mentorship is an ongoing relationship with contact and review, not a one-click trait transfer. Distinguish formal captaincy from actual influence. Preserve quirks and domain-specific preferences when habits change.

Mentorship records include participants, formal/informal origin, focus areas, start/end dates, meaningful contacts, demonstrated examples, trust/compatibility evidence and reviews. Let the user propose pairs/groups and focuses; staff and players supply informed feedback rather than a hidden perfect-pair score. Tactical/positional mentoring feeds relevant learning and practice; personal mentoring feeds the experience/appraisal model. Bound mentor capacity and prevent the same contact being counted as several independent lessons. Support selective learning, unsuccessful pairings, changing mentors, continued guidance during injury where feasible and reduced contact after transfers.

Build the following test stories with synthetic players; they are scenario inputs, not guaranteed narratives:

| Scenario | Required observation |
|---|---|
| Academy player learns useful routines with a trusted coach | Over a meaningful period, some habits can improve while creative freedom/preferences remain distinct. |
| Same initial player under inconsistent treatment | Change can stall, differ or reverse; no universal discipline formula forces the same endpoint. |
| Senior player becomes a mentor | Influence requires demonstrated conduct, trust and contact; assignment alone has no instant effect. |
| Same mentee with different mentors/focuses | Development can differ in the demonstrated areas without copying all traits; learned football behavior requires practice and retains execution limits. |
| Mentor is unavailable or assigned too many players | Contact/capacity constrains development; opening a mentoring screen cannot generate lessons. |
| New academy arrival joins after original manager leaves | Retained people/routines can transmit culture; departures and new priorities can also change it. |
| Formerly unreliable player improves | Updated observations can overturn an old scouting reputation; historical reports are retained. |
| Repeated fines, praise or repeated processing of an event | No exploitable instant personality improvement or duplicate state change. |

## 6. Data, persistence and compatibility

- Maintain a documented schema version and engine/rules version. Version the public tactic/routine format independently where changes alter interpretation.
- Preserve legacy identities and authored content. Convert only known fields; mark inferred capabilities as inferred and unsupported history as unknown.
- Never convert a live old-engine match into a spatial state invented from its score. Finish/resume it using the retained legacy path, then migrate at a defined boundary. Retain that path until all supported saves have a safe route.
- Prefer a season boundary for changing the career's match engine so a competition edition has consistent rules. If a different boundary becomes necessary, document it explicitly and label historical engines; do not silently mix them.
- Preserve the original save through migration using the game's existing save location and a versioned backup. Validate the converted state before atomic replacement; errors leave the original recoverable.
- Test fresh, live-match, midseason and season-end saves, including incomplete lower-division history. Do not fabricate recorded observations or match results to fill gaps without an explicit migration policy.
- Maintain deterministic replay records and immutable settled results; projections such as tables/reports can be rebuilt from their defined inputs. Separate once-only settlement from viewing a result.
- Cache keys include engine/model version, evidence version and relevant parameters. Cache invalidation cannot reveal old or unauthorised knowledge.

## 7. Verification and evidence contracts

Every delivered package records: base/commit SHA, owned paths, test command/results, scenario seeds, relevant artifacts, measured limitations and next package. Keep a concise game-local status file when implementation starts. Do not commit transient save files, massive traces or screenshots by default; retain small reproducible fixtures and scenarios.

Use invariants and scenarios that can detect an incorrect model, not tests that merely restate a formula. Cover action chronology, conservation of possession/ball state, legal player participation, bounded motion, once-only events and projection consistency. Symmetry tests should distinguish exact deterministic identity from statistical fairness; changing entity IDs must not create a structural team advantage.

Calibration uses several profiles/opponents and held-out seeds. Compare intended mechanism counts, rates, opportunities and outcome distributions. Scoring plausibility alone cannot approve movement or tactical logic. Run long-career checks when world/finance/development changes, not after every documentation or UI edit.

Player-facing changes require PTY scripts with named assertions at 80×24 and 110×30, including resize and save/resume where relevant. Use separate `TERMSTATION_SAVE_DIR` locations for concurrent or repeated runs. Run doctor under writable isolated data directories. Investigate bezel failures at the ownership boundary; do not add more unexplained direct terminal writes around curses.

### Initial performance targets to measure, not claimed results

- Input/navigation response: target p95 below 100 ms on the recorded reference machine for ordinary screens.
- Quick full match: initial target p95 below 5 seconds for the small proof roster without rendering.
- The current 12-club matchday: initial target below 15 seconds for background fixtures and world updates, with visible progress/cancellation at safe boundaries.
- Define memory/trace/save growth budgets from P00/P03 measurements before long careers and richer positional archives.

These are engineering goals, not observed capabilities or promises about every terminal. Report misses and profile them. Adjust computation, retention or scope explicitly rather than changing simulation rules depending on what the player watches.

## 8. First implementation handoff

```text
Work in games/touchline only. Read docs/GAME-BRIEF.md and the game's DESIGN.md,
ROADMAP.md and IMPLEMENTATION.md. Execute P00 only: inspect the current tree,
record the game-local module exception, establish reproducible existing-game
tests/PTY evidence and benchmarks, and document baseline integrity gaps and
the uncommitted shared UI dependency. Use isolated synthetic saves and preserve
all unrelated files/worktrees. Do not repair platform files, replace the match
engine, create all future module folders or author more leagues in this slice.
Review and commit only explicit owned paths. Report actual checks and failures,
the commit, artifact locations and the precise P01 starting point.
```

The next substantial build after P00 is P01–P06 in bounded packages. P07 is the first user-facing proof of the new engine. The current request creates this implementation plan; it does not begin those gameplay packages.
