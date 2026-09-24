# Ekse Slaan Ball — simulation and club management plan

**Status:** design baseline, 24 September 2026. Gameplay implementation is not part of this change.
**Scope:** the football, people, information and organisational foundations; large-world content is deferred.
**Implementation baseline inspected:** `f036338` (playable game version 0.2.0).

This is the current game design entry point. It supersedes the scope and architecture proposals in `wip/touchline/touchline/DESIGN.md`, which remains historical research. Neither document is evidence that a proposed mechanic exists. Read `docs/GAME-BRIEF.md` for console integration. The delivery order and acceptance gates are in [ROADMAP.md](ROADMAP.md).

## 1. Product direction and decisions

The player should be able to invent a football idea, recruit and coach people to execute it, observe what actually happens, and adapt the club around the consequences. A creative tactical engine, credible player differences and trustworthy information are the centre of the game. Club administration supplies constraints, competing interests and long-term consequences.

The world must accommodate both elite clubs and modest local clubs. Namibian and African football matter to the intended experience alongside major European football. A smaller club deserves a complete, distinctive career, with different resources and problems. The engine must not equate geography with talent, professionalism or tactical intelligence.

### Accepted direction

- Composable tactics: structures, movement, individual assignments, coordinated relationships, conditions and rehearsed sequences.
- A spatial match engine that can express tactical ideas beyond predefined formations.
- Deep recruitment scouting, opposition scouting and performance analysis linked to actual evidence.
- Unequal information infrastructure across clubs and competitions, generally correlated with resources and league level.
- Players whose physical characteristics, capabilities, judgment, habits and learning make them suitable for different tasks.
- Persistent owners, board members, executives and football staff with meaningful responsibilities.
- Distinct head-coach and manager careers, governed by negotiated responsibilities rather than job title alone.
- Future domestic, continental and international football, including African competition pathways; build the foundations before authoring that world.
- Existing original content remains the playable dataset. Real clubs, players and competition branding are not introduced by this plan.

### Recommended defaults for implementation

These are technical/product defaults, not claims that every detail has been separately selected by the user.

| Question | Default | Reason |
|---|---|---|
| Player ratings | Hybrid: measured facts, observed metrics and uncertain staff assessments. | Supports informed judgment without presenting hidden ability as fact. |
| Assessment display | Plain-language bands initially; optional familiar 1–20 ranges from the same report. | Presentation changes do not reveal additional knowledge. |
| Hidden ability | Continuous internal capabilities with explicit units where applicable. | Avoids tying simulation resolution to an interface rating scale. |
| Match space | Lightweight continuous two-dimensional positions; zones for interpretation/UI. | Supports movement, passing angles, marking and interception timing. |
| Match viewing | Key highlights, extended viewing, tactical replay and quick simulation over the same rules. | Separates observation pace from simulation resolution. |
| Career role | Head coach or manager with a visible, negotiated authority agreement. | Supports narrow football responsibility and broad club involvement. |
| World size now | Small proof dataset with contrasting resource levels. | Validate depth before adding leagues. |
| Runtime | Offline simulation and deterministic authored explanations. | Core play requires no paid data feed, language model or network. |

Do not promise literal support for every imaginable tactic. The acceptance target is that users can construct coherent combinations the developers did not explicitly script. Novel ideas must produce observable behavior and credible counterplay.

## 2. Current implementation versus target

The existing game provides seeded match resolution, an event log, tactical probability modifiers, scouting ranges, training, recruitment, two divisions and promotion/relegation. Preserve useful invariants and save compatibility while rebuilding depth.

Current limitations verified in `main.py` and `content.py`:

- Formations use broad positional slots and probability modifiers; they do not coordinate spatial player movement.
- Matches generate attacks in six 15-minute periods. A regain does not directly initiate the opposing possession, corners do not resolve complete routines, and an assist can be selected after the scoring action.
- Secondary attributes are mostly derived from five seed skills. Position labels and overall scores do too much work.
- Scouting purchases a small number of increasingly narrow reports; there is no observation network or analyst workflow.
- Transfers settle immediately against fee/wage thresholds. Agents exist as text, and loans are absent.
- Contract years decrease without expiry consequences. Aging caps at 40 without retirement.
- Payroll is deducted per match; season prizes currently benefit only the managed club.
- Lineup fallback can reintroduce unavailable players when fewer than eleven are available.
- Staff, governance, career authority and international structures are absent.

These are foundation gaps, not completed depth. Existing rule tests establish some consistency and tactical direction; they do not establish realism, calibration or long-career stability.

## 3. Tactical language

### 3.1 Layers of a tactic

| Layer | Editable concepts |
|---|---|
| Principles | Progression priorities, acceptable risk, width, depth, tempo, patience, directness, freedom. |
| Phase structures | Build-up, progression, established attack, defensive block, attacking transition, defensive transition. |
| Unit relationships | Overlap/underlap, third-player run, cover, exchange positions, overload, weak-side outlet, retreat. |
| Individual behavior | Receiving position, preferred action, marking assignment, pressing route, run timing, support distance. |
| Conditional rules | Observable trigger, participating players, coordinated response, priority, duration and abort condition. |
| Routines | Kickoffs, goal kicks, throws, corners, free kicks, pressing traps and repeatable attacking sequences. |

Roles and style presets are editable bundles of these components. They must not grant hidden bonuses or privileged engine actions. A formation is a useful initial structure, not a limit on the shapes possible during play.

Support asymmetric structures, position exchanges, local overloads, fixed spacing and fluid combinations around the ball. Instructions can be relative to teammates, opponents, ball position and available space rather than only fixed coordinates.

### 3.2 Movement and coordination

An instruction describes an intention within physical and perceptual limits. A full-back cannot instantly move from an overlap into central cover. Moving one player changes the spaces and passing options available to everyone else.

Examples the system must express:

- A winger holds width until the full-back overlaps, then attacks an inside channel.
- A midfielder supports the first build-up line when pressed; otherwise occupies a space behind midfield.
- A striker drops toward the ball while a teammate threatens the space behind.
- The team overloads one flank while preserving an outlet on the opposite side.
- A defender follows a dropping forward only while another defender can cover depth.
- Several players combine near the ball with freedom to exchange positions while designated teammates preserve defensive balance.

Track intended structure, actual positions and coordination failures separately. When the plan fails, explain whether the problem was perception, timing, execution, opposition behavior, physical limitation or conflicting instructions. Staff interpretation can remain uncertain.

### 3.3 Pressing and marking editor

Configure triggers such as a poor touch, backward pass, slow lateral pass, receiver facing their own goal, isolated receiver or pass to a targeted opponent. Define the first presser, pressing angle, supporting assignments, commitment and retreat conditions.

Marking can follow a named opponent, positional counterpart or entrant to an area. Configure distance, interception versus challenge priority, tracking limits, handovers and whether a player may leave the defensive line. Permit hybrid zonal/man-oriented approaches and maintaining a spare defender or accepting isolated duels.

A trap may deliberately leave a passing option available. Cover shadows, supporting pressure and timing must determine whether it closes successfully. Opponents can escape through movement, dribbling, goalkeeper support, width or longer distribution. Repeated exposure gives opposing staff evidence; it does not automatically reveal the tactic file.

### 3.4 Conditions and routines

Each conditional instruction contains: trigger, participants, intended actions, priority, active phase, expiry, abort condition and fallback. Present this as a football editor; users need not write code.

Example: if their full-back receives facing their own goal, the winger presses, the striker blocks the centre-back return pass, and the midfielder closes the pivot. Abort if the receiver escapes into open space or supporting pressure cannot arrive.

The editor detects incompatible duties, uncovered areas, unrealistic travel requirements and unassigned responses. Show the risk and let the player accept legal but risky ideas. Illegal restart setups cannot execute. Bound rule evaluation and resolve priorities deterministically so custom rules cannot cause endless oscillation.

Routines describe coordinated intentions with branches, not guaranteed action scripts. The opponent remains active during every step. A routine can break down, continue through a fallback or return to open play.

### 3.5 Three required proof cases

**Positional possession:** width, interior occupation, an inverted full-back, drawing pressure, a weak-side switch and protection behind the attack. Show why moving one player changes passing options and transition exposure.

**Aggressive man-oriented press:** assignments, tracking/handover rules, isolated defensive duels and an opponent escaping through a rotation, carry or long pass. No blanket tackle bonus substitutes for pressure.

**Kickoff into a throw-in pressing trap:** play back, attempt a long delivery near a deep touchline, advance legally while the ball travels, organise for the opposition restart, contest the first/second ball, retreat if bypassed. Include inaccurate delivery, quick restart and successful opposition escape as possible outcomes. This tests the PSG-inspired idea raised by the user; shipped content remains original.

These are scenario families, not special-case implementations. All three must use the public tactic components.

## 4. Match engine and matchday

### 4.1 Simulation model

Maintain player/ball positions, orientation, movement, acceleration, ball travel, pressure, interception opportunities, offside state, assignments and restart state. Internal granularity must be chosen by prototype profiling; a coarse presentation grid must not dictate the physics model.

Resolve perception → feasible options → decision → attempted action → contested execution → new state. Players have incomplete perception and differing decision speed. Simultaneous movement must not depend on which team is processed first. Use stable update ordering and separate reproducible random streams where needed.

Possession persists. Regains become new attacking situations; blocks, rebounds, clearances and second balls remain live. Resolve set pieces, fouls, advantage, cards, penalties, offside, substitutions, stoppage time and competition-dependent extra time/shootouts through explicit states.

Distinguish pass selection from passing execution; run recognition from running speed; jump timing from standing height; shot selection from finishing. Goalkeepers require positioning, handling, claiming, distribution and sweeping decisions, not one universal save rating.

### 4.2 Events, explanations and statistics

Record event identity, simulation time, possession/action links, actors, start/end positions, context, intended action, result and relevant rule decisions. Preserve the actual assist chain. Every statistic, highlight and report must derive from defined events or observations of them.

Record chance quality before the shot outcome, with location, angle, body part, service, pressure, defender obstruction and goalkeeper location where supported. Distinguish baseline chance estimates, execution and goalkeeper response. Do not label an uncalibrated heuristic as validated xG or expected threat.

Technical debug traces can contain hidden truth. Player-facing commentary and advice must respect what could be observed and what the club knows. Reports distinguish observed patterns from suggested causes; a plausible explanation is not proof that one tactical setting caused a result.

### 4.3 Control and viewing

Simulation resolution is independent of highlights. Support quick simulation, key moments, extended sequences and a step-through tactical view. The same inputs must produce the same football regardless of presentation speed. Pause at appropriate intervention points, including injuries and dismissals. Tactical instructions have plausible communication/application delays.

Enable player-selected substitution pairings, role reassignment, planned match-state responses and opponent-specific instructions. Replays show the recorded match; they do not resimulate it. A tactical laboratory may run explicitly labelled experiments against known test opponents, without exposing an upcoming opponent's hidden state.

Weather, surface, pitch dimensions, travel and crowd context earn inclusion through concrete effects. They must not become arbitrary universal penalties.

## 5. Player model overhaul

### 5.1 Separate the person, capability and evidence

| Layer | Examples | Visibility |
|---|---|---|
| Identity and measurable facts | Age, height, preferred foot, playing history, measured sprint result, medical examination. | Known when documented/measured; each measurement has date and provenance. |
| Underlying capability | Passing execution, acceleration curve, anticipation, first touch under pressure, coordination. | Internal simulation state; player sees assessments and evidence. |
| Habits and choices | Risk preference, early release, carries inside, run selection, scanning and pressing tendencies. | Learned from observation; habits can change through coaching. |
| Current condition | Fatigue, match readiness, confidence, recovery, acute injury and adaptation. | Partially observed through club staff and player feedback. |
| Development | Maturation, trainability, learning, attribute-specific aging and career history. | Future outcomes uncertain; potential is a forecast, not a visible guaranteed cap. |

Measured maximum speed is not an exact readout of every future sprint. Height does not directly determine aerial success: reach, jumping, timing, strength, positioning and opposition all matter. Avoid counting the same physical advantage repeatedly through several correlated ratings.

### 5.2 Capabilities must affect distinguishable actions

- Ball execution: receiving and first touch, short/long passing, crossing/cutbacks, ball carrying, ball striking, heading and tackling.
- Perception and decisions: scanning, anticipation, option recognition, response time, composure, risk selection and off-ball judgment.
- Physical execution: acceleration, speed, agility, balance, strength, reach/jumping, endurance and recovery.
- Defensive skills: orientation, positioning, tracking, interception judgment, challenge timing and coordinated pressure.
- Goalkeeping: set position, reaction, handling, claims, one-on-ones, sweeping and distribution.
- Learning and teamwork: role/position familiarity, communication, coordination and adaptability.

The exact attribute list is provisional. An attribute earns a place when a controlled test shows a distinct effect. Do not derive dozens of near-identical attributes from five base numbers. Authored profiles and generation must support unusual, credible combinations and correlated traits without making players interchangeable.

### 5.3 Presentation decision

Default dossiers combine facts, performance evidence and plain-language scout judgments with confidence. Offer an optional 1–20 assessment view, displaying ranges/unknowns where appropriate. Both views consume the same report. The current 0–100 values are migration inputs, not a permanent promise about presentation.

Do not expose a universal true overall or exact potential in ordinary play. Role fit is a contextual judgment against the actual duties, opposition, squad and requested standard. Explain requirements, strengths, risks and evidence; avoid one score silently averaging away a critical weakness.

An illustrative report might say: "Strong recovery pace observed; promising receiving under pressure; aerial timing uncertain. Six full matches, mostly against weaker opponents. Suitable for an aggressive covering role if paired with a strong aerial defender." Any numbers in mockups must be labelled illustrative.

Optional future sandbox visibility is a separate save setting, not an information leak through a UI toggle.

### 5.4 Careers and development

Separate short-term fitness, sharpness, accumulated fatigue, injury and rehabilitation. Track role learning and unit familiarity through actual training and shared play. Development depends on appropriate challenge, coaching, opportunities, maturation, health and environment; minutes alone do not guarantee growth.

Support attribute-specific aging, plateaus, late development, position changes, decline and retirement. Youth evaluation considers maturation and observation bias without treating body size, nationality or early dominance as destiny. Preserve development history and uncertainty in forecasts.

Promises, trust, contract satisfaction, settlement and role expectations have separate causes. People respond to their interests and history, with explicit promise deadlines and conditions. Avoid repeated morale multipliers that make small confidence changes dominate football ability.

## 6. Scouting and analytics as a complete information system

### 6.1 Truth is not the club's database

The simulator knows what occurred; every club has an information view built from observations, purchased coverage, reports and its own records. An observation records source, observer, date, match/session, subject, coverage, method, uncertainty and supported facts. Reports reference their inputs and retain previous versions.

Do not give analysts exact hidden attributes or the full world event stream and then add cosmetic error. Missing coverage must actually limit queries and conclusions. Player agents' claims and rumours are labelled separately from independently observed evidence.

Information can become stale. Repeated views of the same footage are correlated evidence, not new independent confirmation. Conflicting scouts retain their disagreement. A new report requires time, access and staff capacity; it cannot be spammed to reroll a preferred answer.

### 6.2 Infrastructure and league differences

| Environment | Typical available evidence | Main constraints |
|---|---|---|
| Modest local club | Results, basic minutes/goals, local contacts, live reports, occasional recordings. | Travel, incomplete records, staff time and small observation samples. |
| Developing professional club | More video, manual event tagging, regional scouts, basic physical monitoring. | Uneven opponent coverage, limited specialist capacity and report delays. |
| Well-resourced elite club | Broad video/event coverage, specialist analysts, richer own-team tracking and testing. | Interpretation, integration, uncertainty, information overload and cost. |

League level influences default coverage and commercial availability. Club funding, staff competence, access, local knowledge and deliberate investment determine actual capability. Promotion does not instantly create a department. Relegation can reduce funding while existing knowledge and contracts persist. Affiliation, pooled services or a gifted local scout can create exceptions.

A wealthy club scouting an uncovered competition still faces missing footage and comparable data. It can send observers; it cannot buy observations that never existed. An established local network can identify a player before an elite database does. Better tools should improve coverage, timeliness and inference without guaranteeing correct decisions.

### 6.3 Recruitment workflow

1. Define the job from the tactic and squad plan: essential behaviors, acceptable compromises, budget, availability and development horizon.
2. Discover candidates through networks, competition searches, video, statistical filters, recommendations, trials and agents.
3. Triage using available evidence; display missing data explicitly rather than ranking unknowns as zero.
4. Assign live/video observation or testing with time, travel, staff and financial costs.
5. Compare candidates across role behavior, context, adaptation, likely availability and total commitment.
6. Present a dossier with supporting sequences, disagreements, sample limitations and a recommended next action.
7. Track the decision and review actual outcomes to improve department evaluation.

Support longlists, shortlists, saved filters, alerts, watch assignments, succession plans, loan monitoring and age-group development tracking. Scouts have regional knowledge, access, judgment, specialties and consistent biases. Reports belong to the club's history; staff departure changes future capacity and personal contacts without arbitrarily deleting institutional records.

### 6.4 Opposition scouting and match preparation

Report likely lineups and shapes as probabilities, with source dates and uncertainty. Analyse build-up routes, pressing triggers, marking behavior, restarts, substitutions, recurring match-state responses and individual matchups.

Connect recommendations to the user's plan: where the opponent may isolate a defender, which receiver can be trapped, which run can disrupt assignments, and what recovery demands the plan creates. Include supporting match sequences and counterarguments.

Produce a concise preparation brief: three actionable patterns, likely personnel, major unknowns, suggested rehearsal and workload implications. Allow deep drill-down without requiring it. During a match, analysts update hypotheses from observable play; they never read the opposition tactic configuration or unseen condition.

### 6.5 Analytics catalogue

Metrics are introduced only when the engine and observation model support their definitions.

| Analysis family | Intended outputs | Necessary context |
|---|---|---|
| Chance creation and finishing | Shot maps, calibrated xG, service types, chance involvement, finishing uncertainty. | Shot context, sample size, penalties, opposition and role. |
| Progression and possession | Line-breaking passes, carries, receiving between lines, switches, turnovers under pressure. | Available opportunities, team style, territory and pressure definitions. |
| Pressing and defence | Press attempts, forced retreats, regains, escapes conceded, interceptions, coverage failures. | Assignment, local support, possession exposure and opponent options. |
| Movement and structure | Width/depth, passing networks, spacing, runs, overloads and protection behind attacks. | Tracking/positional coverage and phase. |
| Duels and aerial play | Contested opportunities, success, second-ball outcomes and matchup effects. | Opponent, location, service quality and physical context. |
| Goalkeeping | Shot stopping, cross claims, sweeping, distribution under pressure. | Opportunity difficulty and defensive environment. |
| Physical and medical | Workload trends, sprint exposure, recovery, readiness and risk assessments. | Measurement access, uncertainty and player-specific history. |
| Recruitment and development | Role-specific comparisons, trajectories, adaptation evidence and total-cost scenarios. | League/context adjustment, age, minutes, evidence quality and forecast horizon. |

Every metric needs a registry entry: name, unit, event/observation definition, denominator, exclusions, sample count, coverage requirement, model version and caveats. Different definitions must not share an indistinguishable label.

Allow per-90 and opportunity-based rates, phase/role filters, rolling windows and explicit comparison populations. Percentiles identify their cohort. Per-90 metrics alone do not correct for possession, role or opposition. Show small-sample uncertainty and shrink unstable estimates toward an appropriate baseline; never present missing data as a precise zero.

Avoid automatic conversion of statistical output into true ability. A striker's goals depend on service and opposition; a defender's low tackle count may reflect successful positioning. Cross-league translations are uncertain models, not universal multipliers. A local league player can be outstanding without an elite club having enough evidence to know it.

### 6.6 Analysis experience and evaluation

Offer searchable dossiers, side-by-side comparisons, shot/passing maps, trend plots, textual summaries and selectable event sequences. The terminal equivalent of a video link opens the available replay/observation, not hidden simulation truth. Reports must state when positional detail is unavailable.

Keep facts, model estimates and staff advice visually distinct. Analysts can explain evidence and alternatives without claiming certainty about causation. Richer departments can offer more specialised reports, but the main desk still surfaces decisions and deadlines rather than hundreds of unprioritised metrics.

Evaluate report calibration, recommendation usefulness, coverage and error against withheld simulation truth in developer tests. Clubs do not receive that truth. Test deliberate selection bias, repeated evidence, stale reports, low samples and data-poor competitions.

## 7. Club organisation, ownership and playable authority

### 7.1 People and institutions

Owners, board members and executives are persistent people with tenure, relationships, financial constraints, objectives, patience and defined authority. Support ownership structures as data: private owner, consortium, member-led organisation or other authored models. Separate the owner's wealth, willingness to invest and the club's cash.

The board can balance sporting results, solvency, youth development, playing identity and commercial ambitions. Significant decisions use visible processes, thresholds and recorded reasons. Internal disagreement is possible, but not every routine decision requires a political minigame.

Promises, recruitment disputes, investment proposals, appointments and results create institutional memory. Ownership changes may change priorities and available funding; they do not automatically inject arbitrary cash or erase commitments.

### 7.2 Head coach versus manager

These are game defaults, not universal claims about real job titles. Each appointment has an authority agreement that can be negotiated and changed with explanation.

| Decision | Head-coach default | Manager default | Final constraint |
|---|---|---|---|
| Tactics and match selection | Leads. | Leads. | Eligibility, availability and competition rules. |
| Training and match preparation | Leads with staff. | Leads or delegates. | Medical restrictions, facilities and staff capacity. |
| Recruitment needs | Defines profiles; recommends targets. | Controls football shortlist and can negotiate. | Agreed budget, executive approvals and player choice. |
| Transfer/contract execution | Sporting director normally executes. | Can execute or delegate within mandate. | Contract authority and board spending limits. |
| Football staff | Recommends; agreed appointments may be delegated. | Broader appointment authority. | Budget and reserved board roles. |
| Academy strategy | Contributes and requests pathways. | Can lead football development policy. | Club charter, resources and executive oversight. |
| Facilities and budgets | Makes requests and supplies football case. | Proposes allocations/investment and manages agreed budgets. | Ownership/board approve major expenditure. |
| Commercial deals, borrowing, ownership | Receives relevant consequences and can advise. | Broader consultation where agreed. | Executive/board reserved powers. |

A manager is not automatically the owner. Even broad control exists within an employment mandate. Delegation cannot grant powers the player does not possess. Head coaches must have meaningful influence: argue for a profile, request alternatives, challenge an unsuitable signing and negotiate permitted vetoes.

Career offers display responsibilities, objectives, resources, reporting line, approval thresholds and accountability. The board assesses decisions within the role's control, while still evaluating team performance. Dismissal follows visible deterioration and warnings; it creates a career transition, not silent save deletion.

### 7.3 Staff roles and work

| Role/function | Concrete work and consequences |
|---|---|
| Managing director / chief executive | Coordinates operations, approved budgets, contracts and major proposals. |
| Sporting director / director of football | Squad succession, recruitment strategy, negotiations, loans and football continuity. |
| Finance lead | Cash forecasts, payment schedules, risk reports and spending checks. |
| Head of recruitment / chief scout | Assignments, regional coverage, standards, shortlist synthesis and report review. |
| Scouts | Live/video observations, networks, candidate discovery and longitudinal reports. |
| Recruitment analysts | Contextual comparisons, role searches, evidence screening and model limitations. |
| Performance/opposition analysts | Match review, opponent patterns, live analysis and preparation evidence. |
| Assistant and specialist coaches | Training design, unit learning, goalkeeper work, individual development and advice. |
| Set-piece coach | Routine development, rehearsal, opposition restart analysis and adaptation. |
| Head of academy / development staff | Intake pathways, youth coaching, progression and loan coordination. |
| Sports scientist / strength and conditioning coach | Load planning, physical development, testing and recovery monitoring. |
| Doctor / physiotherapist / rehabilitation staff | Diagnosis, treatment, return-to-play assessments and rehabilitation. |
| Player-care / psychology function | Settlement, communication and wellbeing support within appropriate professional boundaries. |
| Operations / commercial function | Travel, facilities, matchday operations and authorised revenue activities. |

Functions can be combined in small clubs; the model must not require an elite-sized staff to field a team. People have skills, availability, workload, wages, contracts, relationships and working preferences. Hiring ten analysts cannot generate ten independent observations from one match recording.

Tasks consume capacity and time, produce attributable outputs and compete for resources. Delegation specifies objectives, limits, exceptions and escalation. Staff explain proposals and decisions; users can inspect a decision log. Conflicts between a coach and sporting director arise from incompatible priorities or evidence, not arbitrary mood rolls.

## 8. Recruitment, contracts, loans and finance

Maintain squad plans for tactical requirements, depth, succession, eligibility and development. AI clubs run the same processes under their own authority and information limits.

Transfers progress through enquiry, interest, negotiation, personal terms, medical and registration. Rival interest, deadlines, replacement needs and failed related sales can change the situation. Valuation, asking price, estimated total cost and agreed fee are distinct.

Players and persistent agents have separate interests, reputations, relationships and alternatives. Agent portfolios create connections without conferring omniscience. Rumours, provisional interest and actual offers remain distinguishable. No club fee is charged for a free agent; signing and agent fees have explicit recipients.

Contracts track start/end dates, wages, scheduled increases, bonuses, options, release conditions, promotion/relegation adjustments and explicit promises. Expiry and renewal affect employment, registration, payroll and market availability. Clauses and payments settle once and remain auditable.

Loans distinguish parent ownership/contract from borrowing registration and match eligibility. Record duration, fees, wage contribution, playing-time/role expectations, recall terms and purchase options/obligations. Track development and actual use. A manager change at the borrowing club can change the loan's value and trigger a review.

Finances distinguish cash, operating results, authorised budgets and future commitments. Use a ledger and scheduled payments for payroll, transfers, bonuses, revenues, facilities and debt. Forecast sporting scenarios without inventing precision. Instalments, conditional obligations and relegation risks must appear before approval. Apply income and costs consistently to human and AI clubs.

Facility investment has time, capacity and recurring costs. Sponsors, matchday income and competition distributions have schedules and terms. Financial trouble produces explainable warnings and remedies under authored rules. Board control and executive action must follow the same authority model as ordinary operations.

## 9. Global football foundations; content expansion deferred

Design identifiers and rules for countries, regions, confederations, clubs, national teams, competitions, editions, stages, fixtures, venues and participants. Club employment and national-team selection are different relationships: an international call-up must not transfer a player away from their club.

Future scope includes domestic leagues/cups, continental club competitions, qualifiers, national-team continental tournaments, World Cup-style tournaments and club world competitions. African pathways, including CAF Champions League-style qualification, must be expressible alongside European and other systems. Exact names, current rules and real-world content require a separate researched content decision; do not encode assumed universal European rules now.

Required foundations:

- Competition-specific scheduling, seasons, calendars, registration, suspensions, tie-breakers and match rules.
- Group, league and knockout stages, single/two-leg ties, byes, seeding, draws and qualification places.
- Explicit qualification links between competition editions, with rules versioned for the save.
- Different season calendars, travel/rest requirements, venue constraints and fixture congestion.
- National selection/eligibility records capable of representing future call-up, release and eligibility decisions without implementing every jurisdiction now.
- Awards, prize distributions and financial commitments attached to competitions, not hardcoded league IDs.
- Domestic promotion/relegation, continental qualification and international selection treated as separate processes.

Use synthetic test competitions to prove these capabilities before authoring continents. Retain every active participant needed to explain qualification and fixtures. Any future simulation-detail tiers must preserve contracts, eligibility, resources and credible results; changing what the player watches cannot secretly change outcomes.

## 10. Architecture, persistence and terminal contract

Use separable domains: match simulation, tactics, player development, observation/scouting, analytics, governance/staff, contracts/finance, calendar/competitions, persistence and interface. Keep authored tables, prose, rule profiles, map/routine diagrams and fixtures in editable game-local data modules with editing comments.

`docs/GAME-BRIEF.md` currently says rules go in `main.py`; the historical design proposes separating simulation and UI. This plan recommends game-local rule modules with `main.py` as entry point. That recommendation is a documented contract exception to reconcile explicitly at implementation start, not permission to silently edit shared SDK/console files. Preserve the content/rules separation and game-folder boundary regardless.

Pure simulation must import and run without curses, filesystem writes, awards or UI services. Use explicit commands and resulting events at domain boundaries. Do not require full event sourcing for every field, but retain auditable histories for match actions, observations, contracts, payments, authority changes and major career decisions.

Version saves, rules and analytic models. Save RNG state/stream counters where needed and resume mid-match exactly. Keep stable identities across transfers, loans, retirement and staff moves. Define migration behavior for older saves, including incomplete historical competition data; never silently fabricate a fully observed past.

The game remains within the bezel. Design for the 76×20 playable picture at 80×24 and expand from reported dimensions. Use focused screens, scrolling, search, comparisons and drill-downs; color is supplementary. Expose Squad, Tactics, Recruitment, Analysis, Staff, Club and Calendar through stable navigation. Separate urgent decisions from informational digests.

The engine and rich reports need measured performance budgets. Profile a match, replay, daily world update and long-career save before expanding scale. Bound retained raw positional traces through documented archive/retention rules while preserving important statistics, provenance and career history. Do not silently discard evidence still referenced by a report.

## 11. Research basis and boundaries

Sources below inform mechanisms; proposed implementation details are our design decisions. Reviewed 24 September 2026. Official feature descriptions establish advertised behavior, not proof of private engine internals or comparative quality.

- [FM26 tactical evolution](https://www.footballmanager.com/fm26/features/possession-out-possession-fm26s-new-tactical-evolution): phase-specific formations, roles and tactical visualisation. Our editable rule/routine language extends the design ambition.
- [UEFA analysis of man-marking and solutions](https://www.uefa.com/uefachampionsleague/news/02a1-1fceb8b0716e-5ad137580ad0-1000--champions-league-perform/): evidence for testing assignments and opponent escape mechanisms together.
- [FIFA analysis of solutions against high pressing](https://www.fifatrainingcentre.com/en/game/tournaments/fcwc/2025/team-analyses/tsg-roundtable-analysing-solutions-against-teams-that-press-high.php): dribbling, width and longer distribution as alternative solutions.
- [Hudl Statsbomb integrating data and video](https://www.hudl.com/blog/hudl-statsbomb-video-wyscout): recruitment filters linked to underlying sequences. Our terminal equivalent is inspectable available match evidence.
- [FIFA talent identification framework, Module 3](https://www.fifatrainingcentre.com/en/environment/guide/high-performance/find/talent-identification-guide-module-3.php): scouting environments, observation, reporting and analytics as an organised process.
- [Tom Bergkamp on scouting assessment](https://www.fifatrainingcentre.com/en/environment/research-brief/high-performance/find/bergkamp---how-scouts-assess-players.php): assessment reliability and consistency matter; uncertainty must be substantive.
- [Liam Sweeney on maturation selection biases](https://www.fifatrainingcentre.com/en/environment/research-brief/high-performance/talent-pathways/biological-maturation-selection-biases-in-youth-football.php): youth observations require developmental context.
- [OOTP developer explanation of scouting](https://forums.ootpdevelopments.com/showpost.php?p=5188187&postcount=1): distinguish underlying state from scouts' estimates and development projections.
- [FIFA on the head coach](https://www.fifatrainingcentre.com/en/environment/interviews/the-team-behind-the-team/the-role-of-the-head-coach.php): football preparation and match responsibility. Our authority matrix is a configurable game design, not a universal organisational rule.
- [Statsbomb on expected goals](https://www.hudl.com/blog/upgrading-expected-goals): positional context informs chance assessment. A game-generated model still needs independent calibration.
- [FM finance and squad building](https://www.footballmanager.com/features/smarter-transfers-squad-building-and-finance) and [FM26 recruitment](https://www.footballmanager.com/fm26/features/powered-transferroom-fm26s-recruitment-revamp): connected squad needs, recruitment and financial commitments.

No proprietary dataset, licensed video, paid scouting service or real-world roster is required for the foundation. Generated football supplies observations; information access and analysis are simulated club capabilities.
