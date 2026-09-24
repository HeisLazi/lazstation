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
- Individual player personalities, preferences, relationships and changing emotional states, with media and public attention as supporting influences on football and career decisions.
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

### 3.6 Broader tactical coverage

The initial proof cases favour possession and pressing. Extend the validation suite so alternative football works through equally concrete mechanisms:

| Family | Required behavior |
|---|---|
| Compact mid-block | Collective shifting, central denial, selective pressure and deliberate passing concessions. |
| Deep defending and counters | Box protection, meaningful clearances, preserved outlets and timed supporting runs. |
| Direct play and second balls | Targeted delivery, aerial contests, controlled knockdowns and organised support around the landing area. |
| Fluid combinations | Players combine around the ball, exchange positions and preserve selected structural responsibilities. |
| Vertical combinations | A receiver, layoff and third-player run exploit orientation and timing. |
| Wide isolation and crossing | Create a favourable duel, select a delivery and coordinate distinct box arrivals. |
| Spare-defender/sweeper systems | Cover behind stepping defenders or tracking markers; compensate for exposed space. |
| Set-piece-led attack | Seek useful territory and restarts, execute varied routines and protect against counters. |

These families share the tactical language. Smaller clubs are not required to imitate elite possession football. Opponent rotations, dribbles and direct passes must test the costs of strict man-marking; well-executed blocks must test the patience and movement of possession teams.

### 3.7 Objectives, autonomy and tactical memory

Match objectives include pursuing a win, protecting a draw or aggregate lead, chasing a required margin and conserving selected players for another fixture. Risk preferences respond to the competition situation and available personnel. Protecting a lead can mean retaining possession or preserving an attacking outlet; it does not automatically mean retreating.

Distinguish individual understanding, unit coordination, team organisation and rehearsed alternatives. Instruction familiarity is specific enough that learning one system does not instantly master every variant. Opposing staff learn from available match evidence and can counter a recurring routine; there is no arbitrary penalty for using a successful tactic repeatedly.

Players retain bounded autonomy. They may identify an opportunity, abandon an impossible assignment or improvise within their judgment, habits and granted freedom. A sensible decision can fail. Analysis distinguishes instruction quality, execution and improvisation rather than treating obedience or a successful outcome as proof of a good decision.

## 4. Match engine and matchday

### 4.1 Simulation model

Maintain player/ball positions, orientation, movement, acceleration, ball travel, pressure, interception opportunities, offside state, assignments and restart state. Internal granularity must be chosen by prototype profiling; a coarse presentation grid must not dictate the physics model.

Add ball height, flight and bounce to the two-dimensional player model. Distinguish driven/floated/chipped delivery, receiving to feet or into a path, controlled knockdowns, deflections and second balls. A full three-dimensional renderer is unnecessary. The flight model must support consistent interception, aerial, goalkeeper and restart rules.

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

### 5.5 Individual identity, preferences and relationships

Players are persistent people with partially known preferences and histories. Avoid a handful of personality labels that determine every reaction. Use several interacting tendencies, revealed gradually through conversations, conduct and working relationships.

| Layer | Examples | Timescale and effect |
|---|---|---|
| Values and ambitions | Trophies, financial security, belonging, leadership, playing time, family stability, legacy. | Usually persistent but can evolve; shape competing career choices. |
| Working preferences | Direct feedback, private reassurance, clear assignments, creative freedom, predictable routines. | Inform coaching and communication; no universally correct tone. |
| Social tendencies | Comfort with attention, willingness to speak, trust, competitiveness, need for belonging. | Affect how situations are interpreted, without diagnosing a person. |
| Environment preferences | Warm/cool weather, familiar language, a preferred living environment or routine. | Affect comfort and settlement when relevant; adaptation and support matter. |
| Football identity | Favoured roles, play habits, trusted combinations, strengths and weaknesses. | Influences choices, role satisfaction and what the player can execute. |
| Current emotional state | Confidence, frustration, motivation, perceived pressure, belonging and trust. | Changes with events and recovery at different rates; not one global morale meter. |

Preferences are not universal attribute modifiers. Enjoying warm weather does not make a player immune to heat load or less capable whenever it rains. Separate preference, acclimatisation and physical demands; never infer them from nationality or ancestry. A disliked condition may matter for relocation or comfort more than the next shot.

Relationships are directed and contextual. Two players can respect each other's football while competing for minutes; friendship need not imply tactical coordination. Track trust, affinity, respect and unresolved conflict only where they affect decisions. Shared work, support, leadership, competition and broken promises create memories. Memories have salience, context and decay rather than accumulating permanent penalties indefinitely.

Players can like particular teammates, coaches and clubs, dislike a communication style or feel let down by a specific decision. Moving a trusted teammate can affect settlement, but it does not automatically trigger a dressing-room revolt. People retain agency: request a discussion, explain a preference, seek a move, accept a difficult role or rally a teammate.

Positive everyday experiences belong alongside conflict: an academy welcome, a captain's encouragement, shared humour, an earned responsibility or a coach recognising progress. Use concise state-based moments, not an endless stream of private-life interruptions.

### 5.6 State changes and bounded football effects

Use a traceable chain: event → what the player actually learns → personal appraisal → emotional response → coping/support → bounded behavior change → later reassessment. Personality influences possible reactions without prescribing one outcome. State updates are deterministic for the same save inputs and seed; uncertainty in presentation reflects what the manager can know.

Praise might build confidence, raise expectations, feel embarrassing or have little effect. Criticism might create doubt, determination, frustration or disengagement. A competitive response is not permanent immunity to distress. Ambition is not equivalent to disloyalty, public confidence is not proof of wellbeing, and a quiet player is not automatically fragile.

Emotional state can influence action selection, hesitation, communication, willingness to attempt risk, training engagement or recovery routines where the model supports those effects. It must not rewrite established technical ability after a headline. Show uncertainty in explanations of form; tactical fit, opposition, health and random variation remain substantial causes.

Define a shared effect budget before tuning: avoid applying the same pressure through confidence, form, morale and composure multipliers four times. Bound feedback, allow habituation/decay and prevent a bad game → criticism → worse game loop from becoming inevitable. Even excellent support cannot guarantee the next performance, and success does not automatically resolve every concern.

Support includes private conversations, clear role expectations, reasonable workload, trusted teammates, player-care staff, qualified professional support and reduced media commitments. Offer choices with the player's preferences in mind. Sensitive concerns are not public scouting attributes; the manager receives relevant disclosures and advice, not omniscient access to private thoughts.

Do not assign clinical diagnoses through hidden personality scores or reproduce speculative explanations of real players' lives. Fictional careers can produce recovery, setbacks, ambition, injury disruption and resilience without asserting a single cause for a real person's form. Deliberate humiliation or abuse must not become an optimal training shortcut.

### 5.7 Shared time and squad compatibility

Use one calendar for training, recovery, travel, rehabilitation, staff assignments, media duties, negotiations and competition deadlines. Small clubs may have part-time players, combined staff jobs and limited sessions/facilities. Elite clubs have more resources but also congestion and absences. Complexity requires preparation and continuity, not a universal penalty on lower-tier tactical intelligence.

Recruitment evaluates the change to the whole squad: complementary traits, shared receiving spaces, covering relationships, adaptation time and dependence on other signings. Show whether a tactic remains viable when a key player is absent. A useful backup or versatile player can be more valuable than a higher-rated specialist who leaves the squad structurally fragile.

### 5.8 Places, lifestyle and settlement

Players can have preferences for particular leagues, clubs, countries, cities and towns, as well as features of a place: pace of life, privacy, entertainment, climate, language, proximity to important people, commuting and family circumstances. A familiar league or a childhood aspiration can matter independently of its sporting strength.

Represent both destination-specific attachments and underlying preferences. Locations have editable characteristics; avoid treating an entire country as one lifestyle. A player can enjoy city amenities while choosing a quiet home, or value a small-town community while wanting elite competition. Nationality does not prescribe preferences. Preferences can change with experience and life stage.

Before a transfer, the player has an imperfect expectation of the destination. Settlement after arrival depends on the actual situation: housing, travel, language learning, role clarity, relationships, routine and practical support. A club's player-care service can help with introductions, relocation and suitable arrangements. It cannot erase every incompatibility or guarantee happiness.

Separate football adaptation, social belonging and practical settlement. Someone can learn the tactic quickly but feel isolated, or love the town while struggling with the pace of the league. Each progresses through its own evidence and events. A move, loan return or change of coach does not reset personality, injury history or relationship memories.

Recruitment reports show known destination preferences and uncertainty. Players and agents can explain concerns in negotiations and request relevant support. A preferred location can make a smaller offer attractive; an unfavourable location can be outweighed by minutes, ambition or family circumstances. No single preference mechanically decides every offer.

### 5.9 Personal milestones and ordinary life

Include occasional authored event families for parenthood, family visits, relocation, personal achievements, a satisfying purchase such as a new car, celebrations and other everyday changes. Events belong to persistent people and arise at credible frequencies; they are not a weekly requirement or a private-life management game.

Record the event, who knows about it, practical consequences, the player's interpretation, any request and its follow-up. Public disclosure is distinct from the manager learning something privately. Do not send every event into the media system automatically.

A new purchase might bring enjoyment, mean little after a few days or create a practical distraction. Parenthood could bring pride, changing priorities, fatigue, a wish for stability, requests for time away, renewed motivation or a mixture. Different players and circumstances produce different responses. Do not encode a universal parenthood performance bonus or imply that players without children are less motivated.

Leave requests can involve dates, travel, expected availability and flexible return arrangements. Duration follows the individual situation and authored employment rules, not a fixed absence for every birth or family event. The manager's choices operate within their authority; required leave and medical restrictions cannot be overridden through a discipline setting. The player-care team can coordinate practical support and keep the football staff informed about availability without disclosing irrelevant private details.

Responses might include approving discretionary time, agreeing a later return, changing a training schedule, arranging support or discussing a workable alternative. The player can disagree and remember how the conversation was handled. A supportive decision may build trust without producing immediate better football; a denied request may disappoint someone without making them deliberately play badly.

Personal events feed the existing state model through specific paths such as motivation, rest, attention, belonging and availability. They never directly add finishing or passing points. Effects decay or become a lasting change in priorities where justified. Prevent reward farming through repeated purchases, gifts, conversations or leave approvals. Most ordinary life resolves quietly, with a digest or no interruption unless a meaningful decision is needed.

### 5.10 Individual injury susceptibility and rehabilitation

Individual susceptibility must be substantive but probabilistic. Keep a persistent medical history with affected area, injury type, onset, severity, exposure, treatment/recovery stages, recurrence and time missed. Model relevant predispositions separately from current load and an accidental contact injury; avoid a single visible label that predicts every future injury.

Risk depends on the relevant exposure: match/training minutes, sprinting, changes of direction, challenges, current conditioning, accumulated fatigue, recovery and prior injury where supported by the calibrated model. A repeatedly injured player can have a healthy spell; a usually durable player can suffer a serious incident. Do not draw a second independent injury simply because the UI displays another performance period.

Distinguish acute contact events, non-contact events, developing complaints and recurrence. A medical report estimates risk and a recovery range from available information. Clubs with better medical/science capacity can assess and manage more effectively, without knowing the future or eliminating injury risk.

Use staged rehabilitation: unavailable, individual work, partial training, full training, medically cleared and match-readiness rebuilding, with appropriate transitions for the injury. Setbacks update the forecast and plan. Return-to-play eligibility and expected performance are different; being cleared does not instantly restore conditioning or confidence in an affected movement. The coach can select workload within medical constraints and discuss plans with staff and player.

Medical history affects recruitment due diligence, backup requirements, expected availability, workload plans and contract discussions. Compare injuries relative to exposure rather than treating a high appearance count plus several injuries as automatically worse than a short, sparsely observed career. Uncertain or incomplete records stay uncertain. Availability forecasts inform decisions without declaring a player's career doomed.

Injury interruption can change opportunities, relationships, motivation, finances and development. Long-term physical changes require specific recovery/development mechanics rather than a blanket ability reduction for every absence. Personal preference, public pressure and medical state remain distinguishable causes in staff reports.

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
| Communications / press officer | Briefings, media scheduling, accurate transcripts, corrections, monitoring and agreed public responses. |

Functions can be combined in small clubs; the model must not require an elite-sized staff to field a team. People have skills, availability, workload, wages, contracts, relationships and working preferences. Hiring ten analysts cannot generate ten independent observations from one match recording.

Tasks consume capacity and time, produce attributable outputs and compete for resources. Delegation specifies objectives, limits, exceptions and escalation. Staff explain proposals and decisions; users can inspect a decision log. Conflicts between a coach and sporting director arise from incompatible priorities or evidence, not arbitrary mood rolls.

### 7.4 Media, pundits and social attention

Model a fictional football information ecosystem: local reporters, national outlets, specialist analysts, pundits, club channels, supporter accounts and high-reach sports accounts. Each has reach, interests, reliability, editorial tendencies, relationships and a history. They observe public events and attributed information; they cannot read private save state.

| Participant | Typical focus | Possible football connections |
|---|---|---|
| Local reporter / community outlet | Selection, local identity, club finances and familiar people. | Supporter relationships and intense personal visibility despite limited reach. |
| National broadcaster / pundit | Major results, tactics, selection debates, standout players. | Reputation, expectation, recruitment attention and manager scrutiny. |
| Specialist analyst | Patterns, statistics and supported tactical interpretations. | Public football debate, with coverage limits and possible analytical mistakes. |
| Supporter accounts / groups | Loyalty, belonging, grievances, celebrations and rivalries. | Different fan constituencies respond differently; fans are not one mood value. |
| Sports / transfer accounts | Breaking developments, negotiations and shareable stories. | Rumours, demand, agent strategies and pressure to clarify a position. |
| Club and player channels | Official announcements, player voice and community contact. | Communication, identity and relationships within agreed responsibilities. |

Stories originate from matches, interviews, public actions, actual rumours or explicit leak events. A leak requires a plausible knowledgeable source and an event record; private promises cannot simply appear online. Keep facts, quotations, opinion, speculation and fabricated claims distinct in the underlying model and appropriately labelled in the interface.

The player sees a filtered digest with provenance, reach, trend and relevant decisions. Pundits can be wrong, accounts can repeat one another, and large engagement need not represent most supporters. Positive attention, humour, community pride and ordinary reporting should be more than background decoration around crises.

### 7.5 Exposure, response and scale

Exposure depends on club/competition visibility, personal fame, the event's importance, national-team attention and the player's media habits. Elite careers generally face more continuous scrutiny. Lower-level careers have less coverage and fewer formal obligations, but local relationships can be personally important and a cup upset or viral moment can cause a temporary spike. Promotion changes exposure gradually alongside the club's support capacity.

Publication does not mean every player reads every post. Model whether information reaches someone directly, through teammates, agents or staff, and whether they consider the source credible. A wave of reposts is one developing story, not hundreds of independent morale hits. Apply bounded amplification, deduplication, decay and recovery opportunities. No platform APIs or live social accounts are required.

Responses can differ within a squad. Public praise of a prospect may encourage them while increasing their sense of expectation; a teammate may be supportive, indifferent or concerned about their own role. Team effects travel through explicit conversations, leadership and relationships, not an automatic identical penalty to every player.

Media can affect reputation, supporter expectations, sponsorship interest and negotiating leverage. It must not directly alter true ability or turn popularity into scouting evidence. Clubs with good analysis can disagree with a fashionable public narrative. Agents and executives may care about attention for different reasons from coaches.

Abusive coverage is a distinct category from football criticism. If represented, summarise its nature and consequences rather than generating slur-filled feeds. Provide club support and reporting/protection responses; stronger coping can coexist with harm and must not make abuse a source of automatic improvement. FIFPRO's work informs the need for support, not a numerical formula for individual performance.

### 7.6 Press conferences and public/private communication

Questions refer to actual events and the journalist's knowledge. A response is structured around subject, stance, tone, attribution, commitment and disclosure. The interface previews the literal statement and any promise before confirmation. Start with authored composable responses rather than requiring a language model to judge arbitrary text.

Allow the manager to defend a player, accept responsibility, explain a tactical choice, praise an effort, challenge a premise, correct a claim, defer a private matter or delegate within their role. Repeated canned praise is not a universal solution: credibility depends on wording, evidence, relationship and subsequent actions.

Store the exact transcript. Headlines may select a provocative part or omit context, with source reliability and incentives influencing framing. A purported direct quote must use the recorded words unless an explicitly modelled false-report event is flagged as such. The simulation cannot invent a promise and punish the manager for making it.

Players react to the statement they encounter, their trust in the speaker and later clarification. A private explanation can matter even when a headline remains unhelpful. Offering support publicly and repeatedly breaking private commitments erodes credibility. Correcting a story may help, attract further attention or have little effect; disagreement is not always solved through a press conference.

Press staff provide briefings, handle routine corrections and recommend responses. The player can delegate most routine appearances and set communication preferences. Preserve decisions with meaningful stakes; avoid mandatory repetitive questions after every fixture. Head-coach and manager authority still limits what they can promise about transfers, contracts or club policy.

### 7.7 Illustrative connected story and guardrails

A young winger attracts attention after a cup performance. Their own staff see limited minutes and uncertain consistency; a pundit calls them the club's next star. An agent asks about a new contract, the player receives more attention, and an established teammate worries about selection. The manager can set a clear development plan, discuss expectations privately, share credit publicly and arrange support. Subsequent training, selection and communication matter more than finding one perfect press-conference answer.

Alternative players in that situation might enjoy the spotlight, prefer privacy or remain mostly focused on training. None is guaranteed to flourish or decline. The same event links scouting uncertainty, role promises, negotiation, squad relationships and match decisions without dictating the result.

Acceptance requires quiet weeks, positive stories, recovery from setbacks and successful careers with delegated media. This layer adds texture and consequential choices; it must not become the primary determinant of football outcomes or overwhelm tactics, health and squad quality.

### 7.8 Coaching philosophy, club policies and reputation

The manager can establish a working environment through distinct policies rather than one strict/lenient slider. Options include punctuality, match-eve curfews, rest-day flexibility, discretionary holidays, nutrition support and agreed food rules, meeting/training routines, media obligations, feedback style and how exceptions are handled. Tactical freedom and off-field discipline are separate dimensions.

Each policy has a purpose, scope, timing, responsible staff member, communication record, exception process and proportionate response to a breach. Club/board employment rules, protected leave and medical decisions remain constraints. A head coach may control football routines while requiring executive approval for broader employment policies. Explain those limits in the appointment agreement.

Players judge both the rules and their application. Some value structure; others value flexibility. Clear reasons, respectful treatment, consistency, private discussion and practical accommodation affect acceptance. A strict coach can be trusted and supportive; a relaxed coach can maintain high standards. Preferential treatment of a star or an unexplained midseason rule change can matter more than the policy's nominal severity.

Examples: a blanket fast-food ban may be unwelcome, while a player accepts a personalised nutrition plan; a match-eve curfew may suit someone who dislikes restrictions on every free evening. Do not equate one meal with an immediate fitness penalty or liberal policies with inevitable poor preparation. Model actual adherence, rest and sustained habits only to the extent needed for meaningful football decisions, with staff handling routine details.

Requests and breaches should create contextual conversations, not punishment farming. Record known facts and the player's account; avoid omniscient surveillance of private life. A refusal, warning, agreed exception or disciplinary response has consequences through trust, practical preparation and reputation. Disliking a policy need not mean disobeying it or intentionally underperforming.

Coaching reputation grows from repeated conduct, player/staff testimony and public reporting. It travels with the manager but has source confidence and can change. Prospective signings consider known routines and authority arrangements alongside playing time, finances, place and tactical role. Some players decline a club because of a credible lifestyle mismatch; others actively seek that environment. Policy commitments made during recruitment are inspectable promises.

Changing clubs or inheriting another manager's staff creates a transition: explain what will change, negotiate the remit and allow adaptation. The simulation supports demanding, flexible and mixed approaches with different squads; no policy preset is universally optimal or a permanent team-wide buff/debuff.

## 8. Recruitment, contracts, loans and finance

Maintain squad plans for tactical requirements, depth, succession, eligibility and development. AI clubs run the same processes under their own authority and information limits.

Transfers progress through enquiry, interest, negotiation, personal terms, medical and registration. Rival interest, deadlines, replacement needs and failed related sales can change the situation. Valuation, asking price, estimated total cost and agreed fee are distinct.

Players and persistent agents have separate interests, reputations, relationships and alternatives. Agent portfolios create connections without conferring omniscience. Rumours, provisional interest and actual offers remain distinguishable. No club fee is charged for a free agent; signing and agent fees have explicit recipients.

Contracts track start/end dates, wages, scheduled increases, bonuses, options, release conditions, promotion/relegation adjustments and explicit promises. Expiry and renewal affect employment, registration, payroll and market availability. Clauses and payments settle once and remain auditable.

Loans distinguish parent ownership/contract from borrowing registration and match eligibility. Record duration, fees, wage contribution, playing-time/role expectations, recall terms and purchase options/obligations. Track development and actual use. A manager change at the borrowing club can change the loan's value and trigger a review.

Finances distinguish cash, operating results, authorised budgets and future commitments. Use a ledger and scheduled payments for payroll, transfers, bonuses, revenues, facilities and debt. Forecast sporting scenarios without inventing precision. Instalments, conditional obligations and relegation risks must appear before approval. Apply income and costs consistently to human and AI clubs.

Facility investment has time, capacity and recurring costs. Sponsors, matchday income and competition distributions have schedules and terms. Financial trouble produces explainable warnings and remedies under authored rules. Board control and executive action must follow the same authority model as ordinary operations.

### 8.1 A transfer changes a player's situation

Treat a signing as the beginning of a transition. Track expected versus actual role, minutes, tactical demands, destination fit, squad relationships, coaching environment and public expectations. Preserve pre-transfer histories so a new club can provide different opportunities without magically curing every existing problem.

Transfer-related pressure reflects the fee relative to the club's means and records, wage/status, promised role, publicity, the player being replaced and existing reputation. Different audiences can expect different things. A record signing at a modest club can face substantial pressure, and a free academy graduate can face enormous expectations. A lower fee does not automatically mean a lower-pressure destination.

Route the expectation through the existing exposure/appraisal/state model. Some players embrace the challenge, some feel burdened and some barely react. The same person can respond differently with clearer duties, trusted teammates, better health or a different coach. Technical ability is not directly reduced by the fee, and changing the fee alone cannot guarantee a transformation.

Provide a first-months integration plan: practical settlement, tactical onboarding, agreed role, introductions, workload and communication. Staff report separate progress and uncertainties rather than one adaptation percentage. A quiet start does not prove a transfer failed; strong early form does not remove future risks.

Scouts and directors evaluate football fit, likely adaptation, known working preferences, expected availability and total commitment together. A player thriving after a move can result from role fit, opportunities, preparation, relationships, changing expectations and variance. The game should let those stories emerge without copying or claiming a definitive explanation for any real player's career.

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
- [FIFPRO on supporting players facing online abuse](https://www.fifpro.org/en/articles/2023/07/how-fifpro-is-combatting-social-media-abuse-of-footballers): attention can involve harmful exposure and requires support. It does not establish a deterministic relationship between criticism and a particular player's form.
- [FIFA mid-block analysis](https://www.fifatrainingcentre.com/en/fwc2022/technical-and-tactical-analysis/controlling-the-game-without-the-ball--the-mid-block-and-compactness.php) and [goalkeeper distribution analysis](https://www.fifatrainingcentre.com/en/game/individual-qualities/goalkeeping/distribution-opportunities-from-a-long-goal-kick.php): compact defending and varied distribution deserve explicit tactical coverage.
- [FIFPRO, Playing with Cultures](https://fifpro.org/media/n3odzjwi/fifpro-playing-with-cultures.pdf): relocation and cultural adjustment deserve support and individual context; specific settlement mechanics here are design proposals.
- [UEFA Elite Club Injury Study](https://www.uefa.com/news-media/news/021e-0e8f3044e06d-e05490549c2c-1000--2013-14-elite-club-injury-study/) and [survey of team medical officers](https://pubmed.ncbi.nlm.nih.gov/26795611/): exposure, history and workload inform injury assessment. The survey records perceived risks, not a validated individual prediction formula; injury probabilities require separate calibration.

No proprietary dataset, licensed video, paid scouting service or real-world roster is required for the foundation. Generated football supplies observations; information access and analysis are simulated club capabilities.
