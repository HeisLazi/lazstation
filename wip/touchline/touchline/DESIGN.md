# Touchline — research and design brief

**Status: planning only. Research refreshed 23 September 2026.** This records the proposed direction before gameplay code is written. Planning and seed files currently live under `wip/touchline/touchline/`; no registered game exists under `games/touchline/`. The existing `content.py`, `game.toml`, and `cover.txt` are seed material, not a finished game.

## Product promise

Touchline is a keyboard-first football management career in an original football world. The player should remember a late winner, an academy player earned through patient minutes, a tactical gamble that exposed the back line, or a board meeting after overspending. The save should create those stories from systems interacting, rather than rely on a stream of unrelated scripted events.

**Depth rule:** a system earns complexity by changing decisions in at least two other systems. Tactics affect match patterns, role suitability, training, and recruitment. Training affects skill growth, tactical familiarity, readiness, fatigue, and injury exposure. Results affect the table, player form, morale, board confidence, attendance, and money. Features that only add a number or menu are candidates to cut.

## Research and design lessons

FM26 is the latest released Football Manager feature set at the time of this research. Sports Interactive has confirmed FM27 will launch in November 2026, but has not yet published its launch date or feature set. Recheck official FM27 material before implementation rather than guessing what it will add.

| Reference | Observed system | Touchline adaptation |
|---|---|---|
| [FM26 tactics](https://www.footballmanager.com/fm26/features/possession-out-possession-fm26s-new-tactical-evolution) and [matchday](https://www.footballmanager.com/fm26/features/where-storytelling-evolves-fm26s-match-day-experience) | Separate phase shapes and roles, a 3-by-3 pitch visualiser, revised pass-risk decisions, contextual xG/xA advice, and highlight frequency that responds to match drama. | Show how a tactic changes occupation and action options by phase/zone. Feed the same event history into concise causal highlights, a match report, and player stats. |
| [FM26 recruitment](https://www.footballmanager.com/fm26/features/powered-transferroom-fm26s-recruitment-revamp) | Recruitment links squad depth, board expectations, contracts, role, age, deal type, and expected playing time; clubs can publish incoming needs and view other clubs' needs. | Start from a squad-planner need. Let clubs advertise a role/age/playing-time requirement, match it to available players, and explain tactical fit, cost, role, and likely playing time before an offer. AI clubs use the same market. |
| [EA FC 26 career](https://www.ea.com/es/games/ea-sports-fc/fc-26/news/pitch-notes-fc26-career-mode-deep-dive) | A manager market where managers can be sacked, poached, or move; selectable leagues to simulate; scout reports consider potential; board dismissal logic includes warnings; youth minutes and form influence growth. | Simulate a connected manager market and whole playable pyramid. Give scouts uncertain potential ranges. Warn on deteriorating board confidence, and make youth minutes, form, and development connect visibly. |
| [FM26 Mobile](https://www.footballmanager.com/fm26/features/football-manager-26-mobile-new-features-showcase) | Training readiness, staff feedback, finances, budgets, penalties, and player happiness interact. | Make weekly preparation a trade-off; repeated financial trouble affects recruitment, happiness, and club status. |
| [Madden NFL 26 Franchise](https://www.ea.com/games/madden-nfl/madden-nfl-26/news/madden-26-gridiron-notes-franchise-deep-dive) | Weekly staff/playbook loadouts are paired with opponent scouting cards for injuries, positional matchups, key players, and staff tendencies; approval is tracked across stakeholder groups. | Produce a one-screen opponent briefing and a small number of weekly staff assignments. Track board, squad, staff, and supporter trust separately, with reasons and trends. |
| [NBA 2K27 MyNBA](https://newsroom.2k.com/news/nbar-2k27-mynba-answers-the-community-with-a-back-to-basics-franchise-overhaul-and-modern-cba-rules) | Teammate friendships, rivalries, and shared history feed team dynamics; GM trust changes how believable promises are and affects morale. Contracts express incentives with confidence categories; league history can span 100 years. | Keep a small relationship graph from shared minutes, leadership, mentorship, broken promises, and recurring competition. Track manager credibility; promises must be explicit, inspectable, and resolved. Use incentive clauses and career archives only where the UI can explain them. |
| [OOTP 26 development](https://www.ootpdevelopments.com/out-of-the-park-baseball-26/) and [developer scouting notes](https://forums.ootpdevelopments.com/showthread.php?p=5215803) | Scouting has report accuracy, budget, scout specialties, and uncertainty about player development paths; development-lab progress is tracked over time. | Hide exact potential from the player. Scouts can disagree for understandable reasons; repeated observation narrows uncertainty. Report development trajectory and the evidence behind it. |
| [F1 Manager 24](https://corp.formula1.com/f1-manager-2024-to-launch-23-july-including-new-create-a-team-mode/) | Staff mentality and ambitions shape team culture; an affiliates program gives young drivers a development pathway; sponsorship funds the operation. | Give staff personalities and career motives, a loan/academy pathway for prospects, and meaningful short-term versus long-term investment choices. |
| [Football tactics research](https://arxiv.org/abs/2003.10294) | Models pre-match decisions under uncertainty separately from in-match decisions that respond to changing score and game state. | Give each AI club a tactical identity and imperfect opponent read; let managers adapt to score, fatigue, cards, and observed patterns rather than run one static bonus all match. |
| [Dixon–Coles score model](https://rss.onlinelibrary.wiley.com/doi/abs/10.1111/1467-9876.00065) | Models team attack and defence strength over time, with special treatment for low-scoring results. | Use score models as a league-level calibration check, not as the match engine. Generate scores from chances and action sequences. |
| [Soccer expected-possession-value research](https://pmc.ncbi.nlm.nih.gov/articles/PMC8570314/) and [2026 xT model-quality study](https://arxiv.org/abs/2604.21087) | Values possession as a changing sequence using location, pressure, team shape, action choice, and likely outcomes; model quality must be quantified before using the values to rank players. | Track a lightweight, interpretable threat value through each possession. Use it to explain progression and defensive disruption, then validate it before using it to rate players. |

Reviews expose the main risks. FM26 reviewers praised its tactical feedback while reporting that familiar information became harder to find in the redesigned UI ([PC Gamer](https://www.pcgamer.com/games/sports/football-manager-26-review/), [The Guardian](https://www.theguardian.com/games/2025/nov/04/football-manager-26-review-sports-interactive-sega)). FC 26's review criticized off-pitch management as slow and transfer bargaining as guesswork ([PC Gamer](https://www.pcgamer.com/games/sports/ea-sports-fc-26-review/)). SEGA's own report says FM25's UI/graphics overhaul took longer than expected to meet its quality bar ([SEGA report, p. 15](https://www.segasammy.co.jp/cms/wp-content/uploads/pdf/en/ir/20250207_q3_presentation_e.pdf)). Touchline should prioritize predictable keyboard navigation, explainable market decisions, and proof gates before adding breadth.

## Proposed high-depth world

- **World:** 40 original clubs in four 10-club divisions, with home-and-away fixtures, promotion/relegation, a national cup, and a multi-season career. Each division has 18 league rounds. The whole pyramid simulates together so transfers, loans, prospect development, manager movement, and club finances remain connected.
- **Squads:** roughly 18–22 individually defined senior players per club, academy prospects, and free agents. Existing six clubs and named players remain candidate canon; the wider world expands around them. Data-driven templates may generate supporting players, but every generated player receives a persistent identity, history, and coherent attributes.
- **Career:** the manager can improve a club, face board expectations, be dismissed, and pursue realistic jobs elsewhere. AI clubs obey the same finance, squad, tactic, and match rules.
- **Originality:** clubs, players, staff, league identity, prose, and art remain original. Borrow system patterns, not protected names, rosters, or assets.

This is a scope recommendation, not a requirement to author 800-plus player rows before testing the engine. Early proof datasets can be smaller, but the finished career should grow beyond the seed six-team league rather than make the seed league its ceiling. The 40-club pyramid gives manager movement and a genuine prospect-to-first-team route somewhere to go while remaining small enough to simulate every match cheaply.

Each 10-club division has 18 home-and-away rounds, or 90 league fixtures; the four divisions therefore produce 360 league matches per season. A 40-club single-elimination cup adds 39 fixtures, with byes in the opening draw. That scale is modest for a seeded event engine, so every club can use the same match rules and world simulation without asking the player to toggle leagues on and off. Competition rules, calendar, schedule templates, and opening-season fixture data belong in editable data modules. Later pairings are generated deterministically from promoted/relegated clubs, stored in the career save, and validated so every league opponent is met home and away exactly once.

## System design

### Match and tactics

Represent the pitch internally with 15 coarse cells (five depth bands by three lanes), while the terminal visualiser groups those into nine readable zones. A match advances through possession sequences: regain or kickoff → build-up → progression → final-third entry → chance, set piece, or turnover. Each sequence creates an event and causal explanation. Formation and roles affect occupation, pressure, passing lanes, and available actions; they are not hidden attack/defence bonuses.

A tactic contains separate in-possession and out-of-possession shapes, player roles, and a small set of high-impact instructions: press intensity/triggers, defensive line, width, build-up/directness, tempo, and transition choice. Each instruction has an observable upside and cost. Examples:

- A high press creates dangerous turnovers but drains work rate and leaves space behind the press.
- A high line compresses the pitch but risks direct balls into space.
- Short build-up improves controlled progression but is vulnerable to a coordinated press.
- A deep block protects central space but cedes territory and invites crosses.
- Wide overloads create crossing lanes but may expose the far side.

Players contribute through relevant skills, position/role familiarity, fitness, sharpness, morale, form, and tactical familiarity. Chance quality is recorded as an xG-like probability from location, angle, pressure, pass type, and defensive context. Finishing/composure and goalkeeper positioning/reflexes resolve the shot. Reports distinguish chance creation from conversion so a good performance can lose without the simulation claiming the team played badly.

**Matchday recommendation:** use the same event engine in two modes: quick sim for speed, or an interactive broadcast divided into six 15-minute periods. In interactive mode, the manager can change instructions, make substitutions, or hold the plan between periods; key highlights explain what happened. Half-time is a full decision point. This avoids a real-time player-animation system while preserving tactical agency.

Each match event should preserve its cause: period, phase, zone, actors, action, tactical context, result, and change in possession threat. A highlight is selected from those events, not written separately. A late equaliser can therefore become the same event in the timeline, final statistics, player rating, post-match report, and career news. Match importance and closeness can control how many events are expanded, following FM26's dynamic-highlight idea without making routine fixtures verbose.

Roles and shapes set each team's occupation and likely options in the internal cells. A possession sequence chooses build, carry, pass, press, switch, cross, shot, set piece, or turnover according to tactical intent and feasible player actions. Attributes, familiarity, pressure, fatigue, scoreline, and opposition shape modify action choice and execution. xG-like shot quality records the chance before the random outcome; a lightweight expected-threat value records how preceding actions improved or worsened the possession. The engine stays deterministic from a match seed and logs enough inputs for a bug report to replay it.

Resolve a shot from its location, angle, body part, pressure, service, and defensive context; then resolve the keeper using positioning and reflexes. Track the expected value before the outcome so finishing variance remains visible. The same event stream feeds possession and chance statistics, ratings, highlights, and the full-time review. Use one engine for quick sim and interactive management; quick sim only automates the manager's interval choices.

The player model should start with enough individual attributes for roles to feel distinct: first touch, passing range, crossing, dribbling, finishing, heading, tackling, technique, decisions, vision, anticipation, composure, defensive positioning, off-ball movement, teamwork, work rate, leadership, acceleration, pace, agility, strength, stamina, jumping, plus keeper-specific handling, reflexes, command, one-on-ones, and distribution. Keep the existing seed data's 0–100 scale unless a playtest shows it reads poorly. Each role definition in data describes its attribute weights and positional familiarity needs; reports show a role-fit summary plus the main reasons, not a single opaque overall score.

The possession-value measure is an explanatory heuristic, not a scouting truth. Academic EPV work uses richer tracking data than this terminal game will have, and published research stresses validation of expected-threat model quality. Use a simple transparent model first; compare its predictions and player rankings across generated seasons before allowing it to drive recruitment advice or awards.

Opponent AI begins with an uncertain scouting read, then updates during the match. A club has a stable style and coach identity, but can change its risk, press, line, or shape when the score, time, cards, fatigue, or matchup changes. Tactical memory comes from prior meetings and scouting reports, with error and delay; the AI should not know hidden player condition or the manager's unannounced instruction. Research models football tactics as a pre-match decision under incomplete opponent information followed by stochastic in-match decisions as state changes. The practical Touchline inference is to use this separation for believable AI, without importing a research model that needs licensed tracking data.

### Players, development, and staff

Group visible skills into technical, mental, physical, and goalkeeper attributes. Keep the exact list driven by match events and role requirements. Add position/role familiarity, preferred foot, personality, leadership, potential range, age curve, contract, wage, status, injury record, and competition statistics. Current players have precise reports; scouted targets have confidence bands that improve with observation.

Potential is a report about an uncertain development path, not a guaranteed cap exposed as a number. Growth depends on age, underlying growth profile, training quality, coaching, facilities, minutes, match form, role/tactical learning, injuries, and player wellbeing. Attribute-specific aging means pace and stamina can decline on a different curve from positioning or decisions. Scouting uncertainty and scout specialty influence the estimate, while observed match/training evidence gradually improves it.

Weekly training combines a team microcycle, match-specific preparation, recovery, and optional individual focus. Coaches and facilities affect quality. Workload trades development and tactical familiarity against sharpness, recovery, and injury exposure. Minutes and match events also affect development, confidence, fatigue, form, and morale. Rotation is a sporting decision, not a checkbox. A training report should say what changed, what it cost, and what evidence remains noisy.

People systems should create consequences the player can understand. Track each player's trust in the manager from minutes, role, promised status, contract talks, and how the manager handles bad form or transfer requests. Track a sparse relationship network between teammates: shared minutes and mentorship can build bonds; role competition, repeated exclusion, and broken promises can create friction. Relationships influence communication, morale, and willingness to stay, not implausible direct attribute bonuses. A promise has a deadline and a visible success condition; the game reports the cost before the manager commits.

Staff have coaching/scouting/medical abilities, cost, and working relationships. Their quality changes reports and outcomes, while wages and contracts compete with the player budget. Later career progression can add staff poaching and succession if the base loop proves they matter.

### Recruitment, finances, and board

The squad planner identifies gaps from the active tactic, injuries, rotation needs, and expiring contracts. Scouting a target has time/cost and yields a report with uncertainty, role fit, likely fee, wage demand, personality risks, and expected playing time. Negotiation exposes known ranges and constraints; the other club responds to value, need, contract time, and the player's wishes, not a mystery bid grade.

Track cash, transfer budget, wage budget, committed wages, installments, match income, prize money, sponsorship, and operating costs. The board sets sporting and financial objectives with a patience level. Results, style expectations, overspending, promises kept, and player issues affect confidence. Serious repeated financial breaches can restrict registration, cause an embargo, or cost points, but the game must warn before a decision crosses a threshold.

### Career stories and the world

News/events are caused by state: a player losing promised minutes, a contract nearing expiry, repeated late goals from a high line, a financial shortfall, a derby result, or a prospect outperforming the senior squad. Responses change persistent variables and create follow-ups if the cause continues. Random events may perturb a season but must not replace the simulation's own stories.

AI clubs use tactics, squad planners, and transfer constraints. A manager appointment changes a club’s tactical vision; its roster needs then change. Player sales, loans, expiring deals, wage pressure, and promotions create movement across the world. Archive results, table positions, awards, and player statistics by season so the world remembers past outcomes.

Manager changes need visible causes and a warning period: board objectives, trend, finances, promises, and dressing-room trust feed job security. This draws on FC 26's evolving manager market, while its revised formal-warning behavior is a useful guard against abrupt, arbitrary punishment. The player should be able to inspect the board's confidence trend and remaining patience before a decision becomes terminal.

### Weekly operating loop and decision quality

1. **Inbox and calendar:** show only decisions due now, meaningful news, the next fixture, and a short schedule window. Everything else enters a readable digest.
2. **Opponent and squad preparation:** review threats, injuries, likely shape, and matchups; confirm the XI, roles, set pieces, training focus, and recovery balance.
3. **Matchday:** read a pre-match forecast, manage the same event engine in quick or interactive mode, and receive a short tactical debrief that separates process from result.
4. **Consequences:** update table/cup, player minutes and form, fatigue and injury risk, morale, development, finances, board trust, and other clubs' state.
5. **Long-term planning:** scout, negotiate, renew, loan, promote, or invest. Offers expose known ranges and uncertainties; accept/reject logic reports the deciding constraints.

Every recommendation should answer: what is being recommended, what evidence supports it, what it costs, and what uncertainty remains. A pre-match card might say that the opponent's left winger is dangerous in transition because the selected scout observed several fast carries; a transfer card might say a target fits the role but has only a low-confidence report. This brings Madden's matchup briefing and OOTP's scout uncertainty into a football-manager workflow without turning every week into a modal-event queue.

### Walkthroughs that prove the design connects

**Press, adapt, and trust:** Brineport Rovers face Glasswind Athletic after a short rest. The weekly plan shows that another high-intensity press session could improve tactical familiarity but leave two starters tired. A scout report flags Glasswind's wide transition threat with medium confidence. Brineport starts aggressively, wins the ball high, and creates a strong chance; the same high line also gives Glasswind a through-ball chance. The event feed explains both from role occupation and line height. At the interval, the manager can lower the line, switch to a mid-block, or stay aggressive, then make a substitution. The full-time report explains chance quality separately from the score, and minutes, fatigue, form, development, morale, and the table update from the match. A generated news item may note the tactical adjustment or academy cameo only if the event history supports it. The result is not predetermined; the test is whether the causal chain is visible whichever team wins.

**Promise, contract, and market:** a starter has less than a year on their deal, wants a larger role, and has been scouted by another club seeking that exact role. The squad planner shows the replacement gap and estimated wage cost. The manager can renew with a playing-time promise, negotiate a sale, or keep the player and risk the contract running down. Each option shows known ranges and unknowns. Later selection, offers, and results update the player's trust and morale; the board sees the financial and squad-planning consequences. These walkthroughs should become integration-test scenarios after implementation, not scripted cutscenes.

### System interaction contract

| Decision/state | Immediate consequence | Downstream consequences |
|---|---|---|
| Shape, roles, and instructions | Occupation, available actions, pressing and transition behavior change. | Chance profile, fatigue, player-role fit, training priorities, and future recruitment needs change. |
| Match minutes and performance | Match stats, workload, form, and confidence update. | Development, status promises, teammate relationships, morale, and selection choices change. |
| Training and recovery | Skill practice, tactical familiarity, and readiness change. | Match execution, injury exposure, growth trajectory, staff value, and rotation pressure change. |
| Scouting and recruitment | Reports narrow uncertainty; offers consume time and budget. | Squad depth, role fit, player trust, wage commitments, rival plans, and future resale value change. |
| Results and club objectives | Table, cup, and board confidence update. | Manager job security, player trust, attendance, income, reputation, and rival-manager movement change. |
| Injury and medical decisions | Availability and recovery timelines change. | Training load, selection, tactical shape, recruitment urgency, player trust, and budget change. |

This is the feature test for depth. If a proposed feature cannot change at least two other rows in a meaningful, explainable way, it needs a stronger purpose or should wait. The sim should not secretly apply cross-system penalties that the interface cannot show.

## Terminal experience and architecture

- A task-first home screen shows the next fixture, urgent decisions, form, table position, board mood, budget pressure, and recent news.
- Stable keyboard navigation keeps Squad, Tactics, Training, Recruitment, Matchday, Club, and History close. Common tasks are shortcuts; deeper lists and player reports are explicit drill-down screens.
- Each screen shows a compact recommendation/forecast and a clear reason; the user can inspect the underlying numbers. Help and a manual teach controls.
- Layout starts at the 80×24 terminal's 76×20 picture and expands at 110×30. Color never carries meaning by itself.
- A pure deterministic simulation supports headless tests. Data modules hold editable clubs, players, staff, tactics, events, and competition formats. `main.py` receives keyboard input, calls the game rules, and renders their state. Saves are versioned and slot-aware, with a useful console summary and declared awards.
- Shared SDK/console files remain untouched by this game task. The current GAME-BRIEF does not describe every new dashboard hook, so the renderer must be checked against the settled contract before it is built.

At the minimum 76×20 picture, reserve rows 0–1 for the club/date header and rule, rows 2–17 for page content, row 18 for messages, and row 19 for controls. Lists scroll; a player dossier and a full table are separate screens rather than tiny unreadable columns. At 110×30, use the extra six inner rows for more fixtures, history, and match events. Build every layout from the dimensions returned by `ts.tv_curses`, then recalculate after `KEY_RESIZE`.

The page map is Home → Match Prep → Match, with independent Squad, Tactics, Training, Recruitment, Table/Calendar, Club/Staff/Finance, and History pages. Important tasks should be reachable in one navigation step from Home. Match Prep uses a readable 3×3 zone sketch, likely matchup notes, fitness, and role-fit flags; Match uses an event feed plus score, tactical changes, and a short phase recap. Keyboard hints remain visible on every page, and the in-game `manual.md` explains the same controls.

The live console supports game manifests with descriptions, tags, minimum picture dimensions, and `[[awards]]`; it automatically exposes `manual.md` from the carousel. The SDK supplies the active save directory/slot, version-tolerant load/save, game data path, and award unlock/drain hooks. The game should declare career awards and keep a concise `_summary` such as `S2 4th / CUP` so Continue communicates useful state; the console currently truncates summaries to 15 characters.

When implementation is approved, keep the code boundaries explicit: data-only modules own all authored names, descriptions, club identities, player seeds/archetypes, role and formation definitions, fixture rules, and narrative templates, with a comment explaining how to edit each module. `main.py` owns and orchestrates the game rules, as the current GAME-BRIEF requires; keep its systems separated into clear functions and data structures rather than moving rules into the content tables. The simulation accepts explicit state and random seeds and returns updated state plus structured events, so scenarios can be tested without a terminal or save file.

The career save stores a schema version, world seed, current calendar, club/player/staff state, unresolved decisions, competition results, manager history, and a compact `_summary` for the console. The event log can be archived by season so a long career does not grow saves without limit. Awards should recognize career milestones and emergent stories, such as surviving a relegation fight, developing an academy graduate into a regular starter, winning a cup with an underdog, or building a club over several seasons.

## Build and proof gates

1. **Model proof:** build a seeded match engine before a large world. Prove determinism, action/stat consistency, chance-quality monotonicity, and understandable tactical trade-offs over fixed matchup matrices. Compare season distributions against calibrated scoring and low-score targets; no tactic may dominate every matchup. Test counterfactuals: changing only the defensive line should change ball-in-behind frequency; changing only finishing should change conversion more than chance creation.
2. **Weekly vertical slice:** choose a club, inspect the squad, select an XI, set both shapes and instructions, prepare training, manage an interactive match, and reconcile the result into player statistics and the table.
3. **Management loop:** add contracts, scouting, offers/counteroffers, budgets, training progression, injuries, morale, board confidence, and explainable rival AI. Each gets headless invariants and scenario tests.
4. **Career world:** expand to four divisions and the cup; prove every team has a balanced schedule, promotions/relegations are correct, fixtures resolve once, finances and contracts roll forward, and save/reload retains history.
5. **Terminal fit:** update against the current game-facing contract, then test complete play paths, borders, and layouts at 80×24 and 110×30, seeded season simulation, and lazstation doctor.

### Headless proof matrix

- **Match engine:** identical state + seed reproduces the same score, event log, and statistics; a seed bank produces outcome variation without changing the team's plan. Event-derived totals must equal the match summary. Better chance locations and less pressure must raise xG, while keeper skill changes conversion rather than xG. Attribute and tactic effects are tested across many matched seeds and reported as distributions, not demanded in every individual match.
- **Tactics and AI:** high press changes regain location and workload; direct play is more likely to exploit a high line; width changes lane use; player role/familiarity changes action selection. Rival managers use only observed/scouted information, adapt to score/time/cards, and remain within budget and squad rules. No one setup should win every style matchup.
- **Player life cycle:** controlled cohorts verify that training, minutes, coaching, facilities, injury interruptions, and age affect development in the intended directions. Workload and recovery affect readiness and injury exposure without guaranteeing an injury. Minutes, goals, assists, keeper stats, bookings, and availability reconcile exactly across player, fixture, and season records.
- **Recruitment and people:** scouting reports remain uncertain, improve with evidence, and differ by scout specialty; offers/counteroffers obey budgets, contracts, squad need, and expected playing time. Promise deadlines resolve once. Trust, morale, relationships, and board confidence remain bounded and explainable, and AI clubs face the same constraints as the player.
- **Competition and career:** for every season, each division has the expected home/away pairings and no club has two fixtures in one round; each cup entrant is eliminated at most once and exactly one champion remains. Tables use a documented stable tiebreak order. Promotion, relegation, job changes, contract rollover, finance settlement, and generated players preserve IDs and history across multiple seasons.
- **Persistence and console hooks:** save/load roundtrips preserve state and random-seed continuity; older versioned saves merge/migrate safely. `_summary` stays within the console's 15-character display, awards unlock once, the manifest passes `lazstation doctor`, and `manual.md` renders in the carousel manual screen.
- **Terminal path:** scripted PTY play completes a season and at least one managed match at both required sizes. Inspect rendered frames for intact bezel, no writes outside the 76×20 minimum picture, readable controls, resize handling, and no traceback; verify the current outer console with `lazstation doctor`.

For model calibration, keep scoreline realism, tactical responsiveness, and explainability as separate acceptance checks. A realistic league table alone can hide a tactically inert engine; tactical effects alone can produce implausible goals. Run fixed-seed matchup matrices and larger seeded league simulations, inspect average goals/shots/chances/cards/injuries and draw/low-score rates, and retain regression baselines whenever formulas change.

Do not add a feature because a competing game has it. Add it only when it changes decisions, is explained by the UI, and passes a test that can fail.

## Decisions to lock before gameplay implementation

These are recommendations to review, not decisions treated as already approved. Keep gameplay implementation paused until the direction is accepted.

| Decision | Recommended default | Why it fits Touchline | Alternative cost |
|---|---|---|---|
| Match pacing | Six 15-minute control windows, with quick sim using the identical engine. | Gives real tactical intervention without a real-time animation system; every mode produces the same statistics and stories. | A full 90-minute action-by-action interface gives more control but makes the terminal session slower and denser. |
| World scale | 40 clubs in four 10-team tiers, 18 league rounds per tier, plus the 40-club cup. | Provides a multi-step managerial climb and 400-ish fixture decisions per season, still modest for a complete seeded sim. | Fewer clubs reduce career movement, player pathways, and market options; many more clubs add authoring and UI burden without automatically improving depth. |
| Manager career | The manager can resign, be dismissed after visible warnings, and apply for other jobs; dismissal never silently deletes the save. | Makes board trust and the manager market meaningful while preserving player control over the career. | One-club-only mode removes most of the point of rival manager movement and makes dismissal an abrupt end state. |

Once these defaults are accepted, still settle one implementation detail: whether lower-tier promotion is two automatic places or two automatic plus a playoff. The league rules and UI should make the consequences clear before the save begins.
