# Engineering contracts and worked acceptance cases

**Status:** implementation specification, 24 September 2026. APIs and types below are proposed contracts, not existing code. Implement only those needed by the active package. Read [LUNA_HANDOFF.md](LUNA_HANDOFF.md) for execution and [IMPLEMENTATION.md](IMPLEMENTATION.md) for scope.

## 1. Concrete defaults

| Concern | Default to implement | Verification |
|---|---|---|
| Domain imports | Standard-library Python; no curses/SDK/I/O inside domain imports. | Import in a subprocess without terminal/save environment. |
| Identifiers | Opaque stable strings; deterministic counters/namespace derivation, never built-in `hash()`. | Separate processes produce equal IDs/events for equal inputs. |
| Match time | Integer ticks plus explicit tick duration; integer event sequence breaks equal-time ties. | Save/resume preserves exact order. |
| World time | Explicit calendar date plus scheduled-event sequence; no assumption one match equals one payroll week. | Two matches in a week do not double payroll. |
| Geometry | Metres, metres/second, metres/second²; origin/orientation documented; ball height in metres. | Unit/invariant and mirrored-scenario checks. |
| Capability scale | Initial internal normalised 0–1 capabilities; physical quantities retain units. | UI ranges are report projections, not direct access to truth. |
| Relationship/state scale | Internal bounded 0–1 dimensions with separate meanings; no single shared overall. | Bound checks and no silent unit mixing. |
| Money | Integer minor units plus currency ID in the new economy; convert legacy £k explicitly. | Exact ledger reconciliation, no float rounding drift. |
| Randomness | Named serializable deterministic streams by subsystem/match. | A report/UI call cannot alter later football. |
| Unknown | Explicit absent/unknown value and coverage reason, never numeric zero. | Filtering/report calculations retain missingness. |
| Serialization | Versioned JSON-compatible records; enums/IDs/dates validated at the boundary. | Invalid references/schema fail without mutating existing save. |

Normalised scales are engineering defaults, not claimed calibrated psychology or physiological measurements. Derive formula coefficients through recorded experiments; do not invent clinically precise probabilities. Record any default revision before migrating saved data.

## 2. Minimum record ownership

Introduce these incrementally, not as one giant universal dictionary.

| Record | Required concepts | Owner |
|---|---|---|
| PlayerIdentity | ID, birth date/known age provenance, physical facts with units, preferences/history references. | People/world |
| CapabilityProfile | Version, supported capabilities, measured physical quantities, action tendencies, provenance. | People; snapshotted by match |
| MatchState | Version, engine version, teams, tick, ball, players, possession, legal state, score projection, RNG streams. | Match |
| MatchEvent | ID, match/tick/sequence, kind, actor/target IDs, causal/action IDs, observable outcome and evidence references. | Match event writer |
| TacticDefinition | Version, phases, roles/intentions, relative anchors, conditions, priority, fallback, routine definitions. | Tactics |
| Observation | ID, underlying event/session reference, observer/club, date, method, coverage, measured/estimated values. | Knowledge |
| Report | ID/version, authorised inputs, subject, as-of date, method, uncertainty, findings and unavailable fields. | Knowledge |
| RelationshipEdge | Directed person IDs, dimensions, supporting events, last contact, observer knowledge. | People |
| PersonalExperience | ID/date, subject, cause, awareness, appraisal, resulting state changes and processed status. | People |
| Mentorship | ID, origin/initiator, participants, focus, state, contacts, capacity commitment and reviews. | People/staff |
| Appointment | Person/club/role, dates, authorities, limits and reserved decisions. | Club |
| Contract/Obligation | Parties, effective dates, amounts/conditions, status and settlement references. | Economy |
| Fixture/CompetitionEdition | Stable participants, dates, rule version, stages/qualification and resolution state. | World |

Public events and private debug traces must be separate views. Rendering code receives a presentation/knowledge view, not the entire world record. Maintain references to source events so reports remain inspectable after caching or archiving.

## 3. State transition rules

### Match

Start with an explicit legal state: pre-match, restart-ready, in-play, interval, finished or valid exceptional ending. Exact enum names can follow code conventions. Events cause transitions; the UI never assigns a new score or possession owner itself.

For one step:

1. Snapshot the legal match state and active instructions.
2. Build each player's perception from observable local information.
3. Generate feasible actions and intentions, then select them using the appropriate stream.
4. Resolve movement/ball travel and contested actions with documented tie handling.
5. Emit chronological events with the real actors and outcome.
6. Update projections, apply rule transitions and validate invariants.

Do not resolve one entire team's attacks before the opponent gets a decision. A regain/deflection creates the next state from its actual location and movement. Event ordering must not be changed later to make a commentary sequence appear plausible.

### Command boundary

Use a result that distinguishes accepted events from a structured rejection. Validate identity, current state, authority, resources and legal timing before mutation. Failed commands emit no completed transaction and leave state unchanged. An idempotency key identifies the same request retried; a retry returns the prior result or an explicit already-processed response.

Functions may return a new state or mutate an owned state under a clear contract; do not mix styles invisibly. Failed multi-record transactions must not leave half-completed effects. Pure event projection is preferred where practical, but a full event-sourcing framework is not required.

### Friendship and autonomous mentoring

Relationships are directed. Store friendship/affinity separately from trust, respect, tactical familiarity and rivalry. Mutual friendship is not guaranteed from one positive edge. Missing edge means no recorded relationship, not hatred.

On a meaningful shared-context event, evaluate a bounded set of relevant people: those present, existing ties and direct interactions. Opportunity is required before initiating contact. Personality, perceived need, affinity and current capacity shape a proposal; no all-pairs scan per physics tick.

Mentoring states: `offered` → `active` → `paused` or `ended`; an offer may also become `declined` or `expired`. Reactivation requires availability and willingness. Transitions record who acted and why. A player-initiated offer follows the same acceptance/capacity rules as a manager proposal. Manager notification is optional when the relationship is private.

An active record alone teaches nothing. A completed contact references demonstrated behavior, focus and experience. Resolve it once through the learning/appraisal model. Mentors cannot spend the same available time on unlimited separate contacts. Group work can involve several people but has explicit shared time and attention allocation.

### Separation and reunion

After a confirmed roster/registration change, emit one world event. People with relevant known relationships may become aware of it through appropriate channels. Create a personal experience keyed by subject, cause and effect family; retries cannot duplicate it.

- Departure can affect belonging, trust or mood according to bond strength, remaining support and circumstances.
- Reunion can give a large short-term boost to belonging/comfort while future support depends on actual contact.
- Preserve cross-club relationship edges. Update contact opportunities rather than deleting friendship.
- A rumour, accepted offer or cancelled negotiation is not a completed departure/reunion.
- Separate short-term event effects from sustained relationship support; apply the shared bounded effect budget once.
- A new co-signing without prior bonds gets normal introductions, not a best-friend bonus.

Do not set technical capability, automatic goal probability or tactical familiarity directly from the transfer relationship event.

## 4. Acceptance scenarios with explicit assertions

These IDs should appear in tests/status reports as their packages are built. They are required examples, not an exhaustive test suite. A fixed draw can test a branch; statistical claims need repeated trials.

| ID / package | Setup and action | Observable assertions |
|---|---|---|
| CORE-01 / P01 | Serialize a seeded state after several updates; resume in another process. | Event IDs/order, state and future random draws match uninterrupted execution. |
| CORE-02 / P01 | Submit an invalid command and retry a valid processed command. | Invalid leaves state unchanged; retry cannot duplicate events/resources. |
| PLAYER-01 / P02–P04 | Two profiles have identical technique but different scanning/decision behavior. | Their recognised/selected options can differ; pass execution capability itself is unchanged. |
| MOTION-01 / P03 | Defender cannot reach the ball before it passes, including legal height constraints. | No interception event by that defender; no teleporting to the interception point. |
| MOTION-02 / P03 | Mirror a scenario and swap team processing order. | Geometric relationships mirror; no persistent processing-order advantage over a seed suite. |
| BALL-01 / P03–P04 | A contested aerial delivery produces an uncontrolled deflection. | Ball remains at the resolved position/velocity; next possession requires a real recovery action. |
| MATCH-01 / P04–P05 | Pass, shot, save, rebound and goal. | Scorer/assist follow actual lineage; save/rebound/goal totals reconcile; no random post-goal assist. |
| MATCH-02 / P05 | Injury/unavailability leaves too few eligible players. | Apply explicit competition rule; never silently field an unavailable player. |
| TACTIC-01 / P06 | Full-back moves inside while winger preserves width. | Recorded positions/support options show both behaviors; no preset bonus accounts for the result. |
| TACTIC-02 / P06 | Opponent rotates against a strict marker with/without a handover instruction. | Tracking/cover differs and the resulting space is observable, irrespective of goals. |
| TACTIC-03 / P06 | Kickoff delivery toward deep touchline, then an opposition throw. | Legal delivery/restart, travel time and pressing assignments occur; escape remains possible. |
| TACTIC-04 / P06 | Deep block with outlet versus aggressive pressure; alternate physical profiles. | Box protection, outlet availability and second-ball support occur; compare mechanisms across trials. |
| VIEW-01 / P07–P08 | Run identical instructions in quick and interactive presentation. | Final state/events match; drawing/report queries are read-only. |
| SAVE-01 / P08 | Load a mid-match legacy v2 save. | Preserve legacy engine resolution and original save; no invented spatial history. |
| MED-01 / P09 | Simulate equal workloads with and without rendering/repeated medical views. | Injury draws occur at defined exposures only; viewing cannot change recovery or risk. |
| KNOW-01 / P10 | Rich and poor coverage for the same world match. | Reports contain only their permitted observations; absent positional data remains unknown. |
| KNOW-02 / P10–P11 | Open/reissue a report from the same recording repeatedly. | No newly independent evidence or rerolled hidden skill estimates; retained source IDs. |
| AUTH-01 / P12 | Head coach and manager attempt the same reserved financial action. | Appointment-specific result; denied action leaves finances and contracts unchanged. |
| BOND-01 / P13 | Shared session, trusted senior willing to help, newcomer receptive; no manager command. | A player-initiated offer can be accepted; origin/participants/contact record persist. |
| BOND-02 / P13 | Same scenario with newcomer declining or senior at capacity. | No active mentorship/no lesson; refusal does not automatically create animosity. |
| BOND-03 / P13 | Confirm close friend's transfer; compare with an unrelated player. | Contextual separation reaction for the bonded player, no universal squad penalty; edge survives. |
| BOND-04 / P13/P15 | Two established friends join; apply settlement twice. | Positive reunion/settlement effect once; repeated processing and unrelated co-signings get no extra boost. |
| BOND-05 / P13/P15 | A friend's move is rumoured then cancelled. | No completed separation/reunion effects; any uncertainty experience has its own evidence. |
| MENTOR-01 / P13 | Several meaningful contacts on one focus over time, versus no-contact control. | Changes follow actual experiences in the supported dimensions; no whole-person trait copy. |
| CULTURE-01 / P13/P16 | A former mentee gains respect, then offers help to a new arrival after coach departure. | Autonomous proposal possible from retained history/culture; age/title alone does not cause it. |
| MEDIA-01 / P14 | One interview, provocative headline and many reposts. | Exact transcript retained; no invented promise; duplicates do not multiply state penalties. |
| MONEY-01 / P15 | Two fixtures in one payroll interval plus an instalment retry. | Wages and instalment each settle once on their schedule; entries and balances reconcile. |
| LOAN-01 / P15 | Loan, recall and optional purchase across save/resume. | Ownership, registration, eligibility and obligations follow distinct transitions without duplicates. |
| WORLD-01 / P16 | Club player receives a national call-up during a club competition. | Club employment preserved; availability and schedule change; eligibility/rule version recorded. |

Strong relationship reactions should be visible in the people simulation. Do not require every test to prove a goal/result changed: football variance and other causes must remain possible.

## 5. Later-package execution cards

Use these to turn the broad packages into concrete work. Refine exact file names at entry; keep behavior and evidence stable.

### P07–P09: expose and integrate the football

- P07: create a separate game-local laboratory entry; scenario chooser → roster/instruction edit → run/pause → select recorded event → inspect positions. Add save/load for tactics, not career migration. PTY tests exercise a real changed instruction and replay selection.
- P08: create the legacy/new-engine adapter; validate new match input; settle once into the career; preserve old historical engine labels. Add synthetic migration tests before enabling a new career engine. Test exit/resume at open play and a restart.
- P09: implement world dates and scheduled preparation, then medical histories and rehabilitation, then learning/unit familiarity. Connect all three to actual available training time and match exposure. Keep mood/medical state distinct.

### P10–P12: evidence and authority

- P10: implement observation permissions and coverage before any rich analytics screen. A query takes club ID and as-of date. Add report caching keyed by inputs/method/version; show why a field is unavailable.
- P11: build one role search, two-player comparison and one opponent preparation brief first. Each finding links to permitted supporting events. Add metrics only with registry definitions and denominator tests.
- P12: implement appointment checks as a domain function used by all commands; then task capacity/delegation; then staff/board proposals and logs. UI-disabled buttons alone do not enforce authority.

### P13: people, bonds and development

1. Add relationship edges, personal experiences, awareness and once-only appraisal. Prove state bounds and serialization.
2. Add shared-context contact opportunities and autonomous friendship/mentoring offers. Prove BOND-01/02 before adding a mentoring assignment menu.
3. Add actual contacts, trust/compatibility feedback, mentor capacity, focus-specific learning and review. Prove MENTOR-01 and no-contact controls.
4. Add place/policy preferences, conversations, sparse personal events and support choices using the same experience pipeline.
5. Add confirmed departure/reunion reactions and integration with the roster-change boundary; P15 later connects full transactions. Prove BOND-03/04/05 with domain events, without faking an implemented transfer market.
6. Add long-horizon habit/value changes, earned leadership and cultural continuity. Record histories and preserve individual differences.
7. Add concise player/relationship views and notifications only for known meaningful developments. Never force the manager to approve every friendship.

### P14–P16: public/world consequences

- P14: source events → stories → audience exposure → individual experiences. Add transcript-backed responses and press-staff delegation. Reuse P13 effects; do not build a competing morale system.
- P15a: ledger, dated obligations, contract expiry and AI/human symmetry. P15b: offers, player/agent choice, reputation/policy/place compatibility and medical/registration checks. P15c: loans, recall/purchase and AI succession/recruitment. Each requires a real integrated path.
- P16: use synthetic calendars/competitions to test qualification, calls and congestion before authoring geography. Run long careers measuring viable squads, player exits, money, culture/mentoring continuity and archive growth. Record remaining limitations rather than adding emergency immortal players or unlimited funding.

## 6. Review questions before completion

- Is every visible explanation supported by actual state/events or clearly labelled as staff interpretation?
- Can the same result be reproduced without curses and resumed from a saved state?
- Is a private or unknown fact accidentally exposed by sorting, tooltips, replay or an AI decision?
- Are mutations occurring during rendering, report access, imports or repeated command delivery?
- Does a new feature change a real decision and have a measurable downside/limit where appropriate?
- Can existing friendships/mentoring arise autonomously and persist through transfers without bonus farming?
- Does the test assert the intended mechanism, or merely a favourable score/mood value?
- Have we claimed a future interface/package is implemented because its schema or placeholder exists?

Record unresolved answers as remaining work. A smaller completed slice is acceptable; a falsely completed parent package is not.
