# Ekse Slaan Ball — foundation delivery and acceptance

**Planning baseline:** 24 September 2026. All milestones below are planned, not delivered.
Read [DESIGN.md](DESIGN.md) first. This roadmap states milestone outcomes; [IMPLEMENTATION.md](IMPLEMENTATION.md) defines the engineering packages, dependencies and initial handoff. These documents record future work; this planning change contains no gameplay edits.

## Order and working rules

Build depth on a small dataset before expanding leagues. Each milestone supplies a usable, inspectable result and evidence for the next. Preserve the current playable game during replacement; prototype code must not silently become the production engine.

Keep all game work under `games/touchline/`. Resolve the documented game-local module exception before restructuring rules; shared platform changes remain a separate task. Keep content editable, preserve unrelated work, stage explicit owned paths, and commit each verified slice.

Use headless verification for rules and `tools/ptytest.py` at 80×24 and 110×30 for playable paths. Use isolated save directories. Check resize, borders, clean exit, save/resume and `lazstation doctor` whenever integration changes. Documentation-only updates need link/content review and diff checks, not fictional gameplay test claims.

## F0 — establish contracts and reproducible baselines

**Deliver:** a current capability map; explicit domain boundaries; player/club/staff/competition/observation identities; metric definitions; save migration strategy; baseline match/season measurements; a benchmark harness with recorded hardware and runtime.

- Separate current behavior from intended behavior and identify fixtures demonstrating known integrity gaps.
- Resolve unavailable-player fallback, contract expiry semantics, AI/human financial symmetry and migration of incomplete past seasons as explicit work items.
- Define units, event chronology, RNG streams, rule versions and the distinction between world truth and club knowledge.
- Define player identity/state/memory and story/exposure records, keeping personality, temporary mood, football capability and public reputation separate.
- Make personality and culture histories versioned from the start so later development does not overwrite who a player used to be.
- Choose a synthetic proof dataset with contrasting player profiles, tactics and information resources.

**Gate:** documentation and executable baseline cases agree; no existing save is silently reinterpreted. Establish measured performance targets for F1 before claiming a world scale is feasible.

## F1 — prove expressive football

**Deliver:** a headless spatial match prototype, structured tactic definitions, simple tactical replay and a first player capability model.

- Implement movement, ball travel, receiving, passing, carrying, interception, shots and goalkeeping with continuous possession.
- Include ball flight/height, bounce and controlled/uncontrolled second balls; test perception and receiving orientation separately from technique.
- Add pressing assignments, cover, tracking/handover and phase transitions.
- Add explicit restart states and the minimum throw-in/kickoff mechanics needed to test the pressing routine.
- Build the positional-possession, man-oriented-press and kickoff-trap proof cases from shared components.
- Include contrasting player profiles whose capabilities change execution in observable ways.
- Exercise user-authored combinations beyond the three supplied examples.
- Extend headless scenarios to compact blocks/counters, direct second-ball play, fluid combinations, vertical combinations, wide isolation and spare-defender systems. Stage these as small cases over shared mechanics rather than one large content release.

**Gate:** replay traces explain advantages and failures without formation bonuses standing in for movement. Players cannot teleport; the opponent can escape a trap; failed actions remain live football. Changing team iteration order does not advantage a side. Replays and headless outcomes agree.

**Not yet:** many leagues, complete club politics, exhaustive attribute lists or a full tactical editor.

## F2 — make the football playable and coachable

**Deliver:** integrated matchday, tactic/unit/routine editing, training rehearsal, player dossiers and save/resume.

- Complete legal match states: fouls, cards, offside, substitutions, set pieces, stoppage time and configured extra time/shootouts.
- Add conditional rule priority, abort/fallback behavior, conflict warnings and instruction delays.
- Add tactical learning, unit familiarity and physical load without duplicating penalties.
- Add persistent injury histories, relevant exposure and staged rehabilitation; distinguish medical eligibility, match readiness and uncertain availability forecasts.
- Add explicit match objectives, rehearsed alternatives and bounded player improvisation. Opponent adaptation follows observable evidence.
- Establish a shared preparation calendar and test squad compatibility/resilience when a key player is absent.
- Offer key/extended/quick viewing over the same engine and recorded tactical replay.
- Replace the old engine only after parity/integrity gates and migration checks pass.

**Gate:** three tactical proof paths are playable at both terminal sizes. The user can inspect an error, change a plan, rehearse it and see a different pattern across repeated trials. No viewing mode changes the match rules or consumes additional outcome randomness.

## F3 — scouting and analytics with real information limits

**Deliver:** observations, staff assignments, reports, recruitment dossiers, opposition briefs and an analysis desk.

- Implement low-resource, intermediate and elite information environments on the same simulated world.
- Separate access, observation, interpretation and advice. Add source/sample/date/confidence metadata and persistent scout disagreement.
- Link metrics to available event sequences; enforce coverage requirements for positional analysis.
- Provide role-specific searches, comparisons, cohorts, opportunity-adjusted metrics and small-sample warnings.
- Add staff capacity, costs and deadlines needed for report production; fuller organisational behavior follows in F4.
- Use the hybrid player presentation and prove that changing rating format reveals no hidden information.
- Distinguish public reputation, media claims and popularity from observed football evidence; reports cannot expose private emotional state or infer personality from nationality.
- Include exposure-aware availability reviews and known destination/working preferences, showing missing records and uncertain adaptation rather than categorical injury or personality labels.

**Gate:** the same prospect can have materially different but defensible dossiers at two clubs. A wealthy club cannot query nonexistent coverage. Local knowledge can create an advantage. Reports improve through new evidence; repeated purchases cannot manufacture certainty. An opposition brief changes a real preparation decision.

## F4 — appointments, staff and club authority

**Deliver:** persistent ownership/board/executive records, head-coach and manager appointments, staff tasks, player relationships, communication and decision logs.

- Implement negotiated authority, reserved board powers, approval thresholds and reporting lines.
- Make recruitment and staffing workflows respect that authority at both UI and rules layers.
- Let small clubs combine staff functions while suffering credible capacity constraints.
- Add staff contracts, working relationships, proposals, disagreements and accountable decisions.
- Make owner resources, willingness to fund and club cash distinct.
- Deliver player-life work as sub-slices: (a) preferences, memories and private conversations; (b) fictional media sources and exposure; (c) transcript-backed press conferences, staff support and delegation.
- Give different players different appraisals of the same praise/criticism, including negligible reactions. Bound and deduplicate football effects.
- Include positive and ordinary experiences, regional climate preferences, settlement and trusted relationships without identity-based stereotypes or blanket performance modifiers.
- Scale ongoing media coverage with exposure/resources while supporting local scrutiny and temporary attention spikes.
- Add sparse personal milestones and leave requests with calendar consequences, different appraisals and player-care support. Ordinary life should usually resolve without a managerial interruption.
- Make coaching policies independently configurable within the appointment mandate; implement clear scope, exceptions, consistency, private discussions and reputation from actual conduct.
- Test preferences for particular leagues/places and lifestyle features without treating whole countries as one culture or assigning preferences from nationality.
- Introduce experience-driven habit/value development, earned leadership and compatible mentorship; preserve distinct temperaments and permit non-change or alternative paths.
- Give mentoring explicit focuses, formal/informal relationships, contact limits and progress reviews; distinguish learning football decisions from copying a mentor's personality or ability.

**Gate:** the same recruitment case follows different legitimate paths for head coach and manager. Delegation never expands authority. A sporting director can propose an alternative with reasons. A finance lead can flag future risk. A tiny club can still complete a season with combined staff roles.

**Player-life/media gate:** a public story, player exposure, private conversation and later selection form an inspectable causal chain. Different personalities can respond differently without guaranteed results. Headlines cannot create promises absent from the transcript. Reposts do not stack repeated penalties. Routine media can be delegated, quiet weeks occur, and a supportive choice does not guarantee victory.

## F5 — contracts, transfers, agents, loans and financial survival

**Deliver:** timed negotiations, competing buyers, expiring contracts, loan pathways, payment schedules and forecasts.

- Implement player/agent interests, total-cost comparisons and medical/registration outcomes.
- Add destination/policy compatibility to negotiations and a post-signing integration plan. Transfer expectations reflect club-relative cost, role and publicity through the existing player/media model.
- Add renewal/expiry, free agency, clauses and promises with deadlines.
- Add loan ownership/registration separation, monitoring, recall and purchase options/obligations.
- Use ledger-backed scheduled payroll and other financial events, including AI clubs.
- Connect relegation/promotion, facilities and investment to future commitments.
- Ensure AI clubs build and maintain squads rather than merely accepting user transactions.

**Gate:** a complete season connects a tactical need to scouting, an authorised deal, promised minutes, match performance and next-season finances. Deals, loans and clauses survive save/resume and settle exactly once. An AI-only league maintains usable squads under the same constraints.

## F6 — durable careers and competition foundations

**Deliver:** development/retirement, staff/manager movement, institutional history, competition formats and long-run simulation evidence.

- Implement sustainable intake, exits, contract turnover, aging and progression.
- Verify academy-to-leader-to-mentor paths across seasons, including cultural continuity after a manager departure and reputations catching up with changed behavior.
- Add manager job changes and evolving club plans under visible objectives.
- Validate domestic league/cup, continental qualification and national selection as separate relationships using small fictional fixtures.
- Exercise mismatched calendars, registration deadlines, travel/rest and cup congestion.
- Introduce persistent archives and measured retention rules for detailed evidence.

**Gate:** long careers preserve financial/contract/eligibility invariants and meaningful competitive variation. Qualification and call-ups work without changing club employment. Geography/content expansion has an established schema and measured cost.

**Later content:** countries, continents, domestic pyramids, African and other continental competitions, qualifiers and world tournaments. Research the actual desired formats when that content work begins. This milestone does not require building the full world.

## Acceptance matrix

| Requirement | Evidence that can fail |
|---|---|
| Tactical creativity | A custom tactic assembled from public components produces its intended movement without adding engine special cases. |
| Counterplay | Each proof tactic encounters plausible opposing solutions; no preset dominates every matchup and squad. |
| Player distinction | Controlled changes to anticipation, acceleration, touch or passing affect different stages/actions rather than one overall success multiplier. |
| Personality and autonomy | Stable preferences, personal history and current context shape different responses while preserving credible improvisation and the player's technical profile. |
| Personality development | Repeated meaningful experiences can change habits and values at credible rates; age, captaincy, mentorship assignment and punishment cannot guarantee transformation. |
| Transfer adaptation | Fee, expectations, role, location and relationships influence separate transition processes; lower fees never guarantee lower pressure or improved ability. |
| Personal events | The same event can have different or negligible effects; leave updates availability; repeated purchases/support cannot farm performance bonuses. |
| Coaching environment | A known policy can attract or deter a signing; consistency and exceptions matter; neither strictness nor leniency dominates every squad. |
| Medical individuality | Injury risk responds to relevant exposure/history with uncertainty; recurrence and rehabilitation survive saves; susceptibility is not destiny and cleared is not fully match-ready. |
| Emotional effects | One event cannot be counted through multiple overlapping modifiers; recovery/decay and bounded feedback prevent inevitable form spirals. |
| Media integrity | Every story has a source; exposure is required for a reaction; repeats are deduplicated; quotes/promises reconcile to transcripts. |
| Context and privacy | Climate preference differs from physical heat load; lower-tier attention differs from elite exposure; reports do not reveal private thoughts or infer traits from origin. |
| Communication usability | Delegation handles routine coverage, high-stakes choices remain inspectable, and positive/quiet periods prevent a constant crisis loop. |
| Physical integrity | Position, speed, time, ball travel and offside invariants hold across adversarial cases. |
| Match integrity | Event chronology, scorers/assists, possessions, restarts, minutes, legal substitutions and final statistics reconcile. |
| Reproducibility | Save/resume and quick/interactive presentation reproduce identical outcomes for identical decisions and rules. |
| Information boundaries | Clubs cannot access uncovered matches, hidden attributes, exact opposing tactics or private medical data through reports/search/replay. |
| Scouting uncertainty | New independent evidence improves calibrated estimates on average; repeated/stale evidence does not falsely narrow them. |
| Contextual analytics | Cohort, denominator, minutes, opportunities and missing coverage change reports correctly; missing is never silently zero. |
| Staff constraints | Work cannot complete without capacity/access/time; multi-role staff face realistic task contention. |
| Authority | Every executable club action checks the appointment/delegation mandate, including headless commands. |
| Contracts and loans | Expiry, recall, conditional clauses, competing offers and registration cannot duplicate players or obligations. |
| Financial integrity | Scheduled payments reconcile to ledger balances; budgets differ from cash; AI and human rules are symmetric. |
| Career sustainability | Long-run cohorts have credible turnover, age distributions and resource constraints without immortal squads or universal inflation. |
| Competition flexibility | Different sizes/calendars and qualifying paths resolve once; call-ups preserve club membership. |
| Terminal usability | Full scenarios at both sizes retain bezel, navigation, legible uncertainty, keyboard help and recoverable saves. |

## Calibration and playtest protocol

Separate correctness, plausibility and enjoyment. Passing invariants does not establish realistic football; plausible aggregate goals do not prove tactical credibility.

- Run seeded matchup matrices across styles, squad strengths and player profiles. Use repeated trials and uncertainty intervals, not one winning match.
- Measure scoring distributions, draws, shots, passing, possession sequences, territory, regain locations, fouls/cards, set pieces and player involvement. Define targets from appropriately matched evidence before tuning.
- Validate baseline chance predictions against held-out outcomes and inspect subgroups. Do not tune and report calibration on the same samples.
- Use paired experiments where meaningful and separate RNG streams so a tactical change is not confused with unrelated random-number consumption.
- Test symmetry, extreme instructions, contradictory routines, empty/undersized squads, tired players, sendings-off and interrupted matches.
- Simulate long careers and inspect wage/cash distributions, squad viability, contract churn, youth opportunities, competitive balance and save size.
- Evaluate whether users can explain their team's behavior, act on a scouting report and complete routine weeks without repetitive administration.
- Run paired media/player-life scenarios with identical football inputs. Measure effect sizes, recurrence, recovery and interruption frequency; reject tuning where press-conference choices systematically overpower tactical/player-quality differences.
- Test a high-expectation signing under different football/support conditions, a player declining a known policy mismatch, a personal-leave return and an injury recurrence/rehabilitation path. Include healthy spells for susceptible players and setbacks despite sensible management; no selected narrative may be guaranteed.
- Record engine/rules version, seeds, dataset, measurements and known limitations with each milestone. Establish performance targets from F0 measurements and remeasure when fidelity/world size changes.

## First implementation handoff

Use the first implementation handoff in [IMPLEMENTATION.md](IMPLEMENTATION.md). Execute its bounded starting package when gameplay implementation is requested; the current task is planning. Preserve unrelated console work and keep continent authoring and real-club data imports deferred.
