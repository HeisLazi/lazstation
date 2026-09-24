# Touchline implementation status

## P00 — reproducible baseline and constraints

- Status: `complete`
- Base SHA: `291fef5c52f9538119371d232396a317a83c9bca`
- Intended owned paths: `games/touchline/_baseline.py`, `games/touchline/benchmarks.py`, `games/touchline/fixtures.py`, `games/touchline/ARCHITECTURE.md`, `games/touchline/BASELINE.md`, `games/touchline/STATUS.md`.
- Behavior: provide a read-only, seeded legacy-match benchmark; generate explicit synthetic v2 save fixtures for fresh, live-match, midseason and season-complete states; document the module boundary and observed baseline limitations.
- Acceptance: P00-ARCH (entry point/module exception and shared UI dependency are accurately described); P00-BENCH (explicit CLI, seeded match/season count, environment/version/timing/count JSON, optional explicit output destination, no save or persisted award effects); P00-FIXTURES (all four lifecycle states, provenance, schema/engine labels, serialize/reload equality, refuse to overwrite existing outputs); P00-EVIDENCE (source observations are separated from runtime evidence).
- Required evidence: all P00 gates below executed; narrow-width VT replay limitation retained as a known observation.
- Exclusions: no changes to `main.py` gameplay, shared SDK/platform files, root tools, other games or personal career saves; no new match engine work in P00.

## Work log

- Initial inspection: `main.py` declares save schema v2 and game manifest 0.2.0; Python reports 3.14.7. `main.py` imports `termstation_ui`, which exists only as an untracked shared SDK file in this checkout. The current branch is `main` at the base SHA above; the index had no staged changes. A separate locked worktree exists and is out of scope.
- Legacy regression: `python3 -m unittest games.touchline.test_game` (isolated save/XDG dirs) exited 0: 13 tests in 1.496 s.
- PTY season scenario: `games/touchline/season_scenario.json` ran with separate save directories at 80x24 and 110x30; both exited 0 and completed the season. Inspected `home`, `tactics`, `match-01`, `round-01` and `season-review` frames in `/tmp/touchline-p00-checks.eZPrzx/pty80` and `/tmp/touchline-p00-checks.eZPrzx/pty110`. At 80x24 the VT replay shows stray right-edge fragments (`ss`, `i`, `es`) and some joined match-feed text; at 110x30 the layout/border/text were clean. This is a replay observation, not proof of a physical-terminal defect.
- Isolated `python3 -m termstation doctor` exited 0, discovered 8 games and accepted every manifest, including Touchline and Gladiator. This is manifest evidence only.

- Benchmark evidence: 200 seeded BRP–GLA matches, 0.448246 s simulation time; one complete 60-fixture BRP season, 0.171805 s simulation time. Full counts and environment are in `BASELINE.md`.
- Fixture evidence: seed 1 / BRP generated `fresh`, `live`, `midseason` and `finished` v2 saves; lifecycle, serialize/reload and written-file reload checks passed. Output and hashes are under `/tmp/touchline-p00.iSYRk2/fixtures` and recorded in its manifest.
- Static work completed in this pass: documented the accepted game-local module exception and shared UI dependency; added the P00 headless boundary, match/season benchmark CLI and synthetic v2 fixture generator; recorded source-level integrity observations and remaining evidence gates.

## Completion evidence

P00 acceptance passed: architecture/boundary notes, reproducible benchmark,
synthetic lifecycle fixtures, the existing unit suite, both PTY season sizes
with inspected frames, and isolated doctor. The PTY caveat above remains
recorded; no legacy gameplay repair was included. Benchmark counts and fixture
hashes/sizes are in `BASELINE.md` and the generated `/tmp` manifest.

Next package: P01 shared contracts, time and reproducibility. No P01 code is
claimed by this P00 completion record.

## P01 — shared contracts, time and reproducibility

- Status: `complete`
- Base SHA: `2e493e3959533c02df3531e535ee2526655b15cc`
- Intended owned paths: `games/touchline/esb/__init__.py`, `ids.py`, `time.py`, `model.py`, `randomness.py`, `events.py`, `commands.py`, `schedule.py`, `serialization.py`, `state.py`; `games/touchline/checks/test_contracts.py`, `replay_scenario.py`, `replay_worker.py`; this status file.
- Behavior: add only the standard-library, game-local contract layer. Keep IDs explicit and stable; separate match ticks from calendar dates; name physical/money units; keep immutable capability/identity/club-knowledge records separate from mutable match/career/simulation state; serialize independent named PRNG states; version event and command envelopes; validate and apply commands on an isolated copy with idempotent receipts; represent scheduled work and settlement keys without implementing a calendar or ledger.
- Acceptance: CORE-01 (checkpoint after deterministic synthetic updates and resume in another process; compare events/order/state/future draws against uninterrupted execution, and prove reporting draws do not consume football randomness); CORE-02 (invalid command leaves state and event/receipt ledger unchanged; matching retry replays the prior receipt without duplicate effects/events; reused key with different request is rejected); P01-TIME (tick duration/integer ordering and calendar date remain distinct); P01-IMPORT (domain imports do not import curses/SDK or perform save/award I/O); P01-RECORDS (unit-bound values, immutable snapshots, explicit unknown knowledge, and empty history references validate).
- Verification: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s games/touchline/checks -p 'test_*.py'` (10 tests, exit 0); `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest games.touchline.test_game` (13 tests, exit 0); explicit owned-path whitespace and staged-diff review.
- Exclusions: no spatial football rules, authored player histories, calendar runner, economic ledger, UI, save migration, `main.py` integration, shared SDK/platform changes, or legacy gameplay edits. The synthetic replay exists only to verify contracts, not to claim a working match engine.

### P01 work log

- Started from P00 evidence commit `2e493e3`. Added game-local typed identifiers, explicit match/calendar time and units, separate capability/identity/match/career/knowledge records, named SplitMix64 streams, versioned event and command envelopes, serializable command receipts, scheduled-work/settlement references, and a strict versioned JSON codec.
- CORE-01: seeded from `481516`; run 8 synthetic updates uninterrupted and as 3 updates → JSON checkpoint → 5 updates in a fresh process. Encoded state matched byte-for-byte, including event IDs/order, scores, clock, and all PRNG stream positions/future draws. The test-only scenario queries the reporting stream and samples the world stream separately; this is a determinism contract proof, not match simulation.
- CORE-02: invalid input returned a structured rejection without changing the owned state, events or receipts; a valid reservation applied once and replayed its receipt on retry; reusing the same key for a different payload was rejected without state/ledger mutation. A deliberately mutating validator was confined to its validation copy.
- P01-TIME/RECORDS: verified integer tick duration and same-tick sequence order, distinct world date, metres and m/s labels, integer minor currency units, normalized capability bounds, immutable snapshots, empty history references, and explicit unknown coverage reasons. Versioned round trips passed for simulation, career, identity, snapshot, knowledge and settlement records.
- P01-IMPORT: a fresh subprocess patched common Python file-open APIs before importing every domain module; imports succeeded without loading curses, the TerminalStation SDK or the award/save application boundary. No terminal/save/award writes are implemented in this package.
- Regression: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s games/touchline/checks -p 'test_*.py'` exited 0 (10 tests, 0.173 s); `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest games.touchline.test_game` exited 0 (13 tests, 1.389 s).

### P01 completion evidence

P01 acceptance passed for the contracts implemented here. The command ledger and checkpoint codec are serializable values, not a disk persistence adapter; atomic file replacement, save migration and application to real career/match commands remain P08+ work. Command callbacks must remain deterministic and side-effect-free outside the supplied state. SplitMix64 is versioned for replay, not cryptographic use. No spatial match rules, calibrated distributions, UI integration or legacy-game changes are claimed.

## P02 — distinct players and editable tactical intentions

- Status: `complete`
- Base SHA: `322486f15181a124e6db44bb6a18d7aa34ecc998`
- Intended owned paths: `games/touchline/esb/model.py`; `games/touchline/esb/people/__init__.py`; `games/touchline/esb/tactics/__init__.py`, `models.py`, `validate.py`; `games/touchline/esb/content/__init__.py`, `proof_roster.py`, `proof_tactics.py`; `games/touchline/checks/test_profiles_tactics.py`; this status file.
- Behavior: add distinct, provenanced football profiles with separate capability, physical fact, preference, readiness and action-tendency data; author two balanced 16-player synthetic squads; express the three shared proof-tactic families as component data; return explainable validation errors/warnings for missing references, contradictory assignments and invalid rule fallbacks.
- Acceptance: PLAYER-01 (paired profiles hold execution capability constant while scanning/decision differ; no overall shortcut); P02-ROSTER (two balanced 11v11-capable squads with substitutes, GK depth and distinct player profiles survive versioned round-trip); P02-TAC (positional possession, man-oriented pressing and kickoff trap use shared phase/anchor/relationship/mark/press/rule/routine types, with priority, expiry, abort and fallback); P02-PROV (authored/inferred/measured origins are explicit; unknown history stays empty; profile data never relabels inferred values as historical measurements); P02-VALIDATION (warnings explain conflicts; malformed references are rejected before any engine use).
- Verification: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s games/touchline/checks -p 'test_*.py'` (16 tests, exit 0); `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest games.touchline.test_game` (13 tests, exit 0); explicit P02-owned-path diff and staged review.
- Exclusions: no movement/action resolution, hidden formation bonuses, match outcomes, injury/medical simulation, scouting reports, UI/editor, legacy roster migration, `main.py` integration, shared SDK/platform changes or personal-save changes.

### P02 work log

- Began from P01 commit `322486f`. Added per-value provenance kinds, distinct player preference/readiness/action-tendency records, role-aware profile and squad validation, relative tactical anchors, coordinated duties, pressing/marking assignments, conditional rules, routines and explainable validation issues.
- Authored two wholly fictional 16-player squads with two goalkeepers and cover across the supported roles. Each profile keeps identity facts, authored capability values, physical quantities with units, preferred foot, readiness and tendencies in separate records. No legacy roster is converted and no past biography is generated.
- PLAYER-01 matched pair: Neri Vale and Neri Sela share every authored technical/physical/readiness/preference/tendency value while scanning, anticipation and decision quality differ. The test explicitly asserts execution values stay identical; there is no universal overall score.
- Authored three reusable tactic templates: positional possession with width/inverted full-back/cover, a man-oriented press with support and marking handover, and a kickoff-to-touchline-trap routine. Each is data-only and has trigger/priority/tick expiry/abort/fallback where applicable. Shared validators accept all three without structural errors and surface a warning for deliberately contradictory instructions.
- Regression: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s games/touchline/checks -p 'test_*.py'` exited 0 (16 tests, 0.552 s); `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest games.touchline.test_game` exited 0 (13 tests, 1.911 s).

### P02 completion evidence

P02 acceptance passed for typed profile/tactic data and static validation. All roster values are fictional authored scenario inputs, not calibrated simulation parameters or observed history. The tactics describe intentions only: there is no engine action, movement, legality resolution, tactical bonus or match outcome yet. Unknown player history remains empty; legacy conversion remains unimplemented. Existing Touchline and all unrelated concurrent work stayed outside this package.

## MUD-01 — actionable matchday presentation

- Status: `complete`
- Base SHA: `faaa3b95f3adbfefd868dd5dc5e274a3d35841bd`
- Intended owned paths: `games/touchline/main.py`, `games/touchline/content.py`, `games/touchline/test_game.py`, `games/touchline/manual.md`, `games/touchline/season_scenario.json`, `games/touchline/matchday_scenario.json`, and this status file.
- Behavior: insert a pre-kickoff team-talk decision whose player reactions are explained and bounded; let the manager select the exact outgoing and incoming players before confirming a legal substitution; provide focused Live, Events and Stats match views derived read-only from the existing match state, with incident browsing in Events.
- Acceptance: TALK-01 (talk is recorded once before kickoff, player responses use existing player state and are visible); SUB-01 (selected pairing, eligibility, goalkeeper and limit rules are checked before mutation; rejection leaves lineup/events/substitution count unchanged); VIEW-01 (all views reconcile to the same score, clock, statistics and event ledger, Events can browse older/newer incidents, and viewing does not mutate match state); PTY-01 (the talk, match views, incident browsing and explicit pairing remain usable at 80x24 and 110x30, with save/resume and the full-season replay still passing).
- Exclusions: no spatial match engine, custom/free-placement formation editor or claim that legacy formation presets simulate player coordinates. Free placement is a required editor direction for the spatial-engine/editor slice; the current legacy engine stores no player coordinates for placements to affect.
- Required checks: focused unit tests, `python3 -m unittest games.touchline.test_game`, isolated `matchday_scenario.json` and `season_scenario.json` PTY at 80x24 and 110x30 with frame inspection, isolated doctor, and owned-path diff review.

### MUD-01 work log and acceptance evidence

- Added three pre-kickoff talks with starter-by-starter reception preview from authored personality response data. Delivery applies only a bounded morale change, records the selection/reactions once ahead of kickoff in the match event ledger, and does not modify skills or add a direct performance modifier.
- Replaced automatic player-off selection with a two-list confirmation screen. The manager explicitly chooses who comes off and who comes on; available players are medically cleared, goalkeeper/outfield pairings are enforced, role fit/fitness are shown, and accepted pairings persist in substitution history and match events. Rejected changes leave state untouched.
- Replaced the single match panel with Live, Events and Stats views on one score/time strip. Live shows recorded latest action plus its explanation and current plan/readiness; Events browses a newest-first chronology and shows the selected incident's details; Stats reads the same match statistics and player contributions, with possession correctly labelled as share. Drawing the views is read-only.
- Updated the game help/manual and the full-season PTY script for the new pre-match step and Live view. Added `matchday_scenario.json` covering talk selection, all views, explicit substitution, quick simulation, full time and settlement.
- TALK-01 passed: one-time pre-kickoff delivery, bounded individual morale changes, no capability change, correct timeline ordering, and a refused repeat with no extra effect.
- SUB-01 passed: exact selected pair is applied and recorded; duplicate/invalid and goalkeeper mismatch rejections are atomic; menu confirmation changes precisely the selected players.
- VIEW-01 passed: all three views cycle without changing match state; Events browses older and newer incidents; rendered snapshots agree with current score, clock, events and statistics.
- PTY-01 passed: `matchday_scenario.json` and the updated full-season replay both exited 0 at 80x24 and 110x30. Named snapshots were inspected under `/tmp/touchline-mud-final.3i5sW7/recheck-*`. The old 80x24 VT replay edge-fragment caveat noted in P00 remains visible in a season-review frame; this is not treated as new gameplay failure.
- Regression: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s games/touchline/checks -p 'test_*.py'` exited 0 (16 tests); `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest games.touchline.test_game` exited 0 (19 tests); `python3 -m py_compile games/touchline/main.py games/touchline/content.py games.touchline/test_game.py` exited 0; isolated `python3 -m termstation doctor` exited 0 and recognized all 8 game manifests.

### MUD-01 completion and next slice

Follow-up after adding incident browsing: the focused UI test now also checks older/newer navigation without match-state mutation (20 `test_game.py` tests total); the matchday PTY snapshots additionally assert the team-talk detail, older incident, stats, substitutions and full-time screens.

Final recheck: matchday and full-season PTY scenarios exited 0 at both 80x24 and 110x30, the local game doctor found all 8 manifests, and the 20 game tests plus 16 contract/profile checks passed. Inspected current captures are under `/tmp/touchline-mud-final.zzGvzH/`.

The current managed-match flow has an actionable pre-match talk, player-selected substitution pairings and three read-only match views, verified in unit and PTY paths. No schema-version bump was needed; legacy mid-match saves without the optional talk/history keys still use defaults. Free-placement formation creation remains intentionally unimplemented until custom coordinates can affect the spatial match engine instead of serving as a decorative legacy diagram. Next: P03 movement, ball flight and receiving, then integrate the requested free-placement editor with that spatial state.

## UI-01 — clearer navigation and compact terminal layout

- Status: `complete`
- Owned paths: `games/touchline/main.py`, `games/touchline/test_game.py`, `games/touchline/manual.md`, `games/touchline/season_scenario.json`, `games/touchline/matchday_scenario.json`, and this status file.
- Behavior: replace the clipped shortcut footer with a focused section bar; browse sections with Left/Right and open with Enter while retaining 1–7, Tab and M shortcuts; add matchday/help breadcrumbs; shorten the header to fit the active terminal width; reclaim one body row; remove inner panel borders below 88 columns; focus the managed club in the Home standings; clarify tactical +/- adjustment keys.
- Acceptance: NAV-01 (arrow focus is independent of the active page, Enter opens the focused section or starts Matchday, shortcuts stay synchronized); UI-80 (80-column header/footer and section bar are visible, narrow pages flatten their internal boxes); UI-110 (roomier layout remains framed and readable); REG-01 (matchday and full-season flows remain operable).
- Verification: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest games.touchline.test_game` (24 tests); `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s games/touchline/checks -p 'test_*.py'` (16 tests); `season_scenario.json` and `matchday_scenario.json` PTY runs at 80x24 and 110x30 (all exit 0 and assertions pass); layout snapshots inspected under `/tmp/touchline-ui-pass.OgmlG1/`; `git diff --check`.
- Exclusions: the game cannot resize the host terminal font or resolution, and no shared TerminalStation bezel/SDK changes were made. Use the terminal emulator's zoom or maximize controls for physically larger text. Free-placement formations remain dependent on the later spatial-engine slice.

### UI-01 work log

- Added a compact, focused navigation strip whose current section and keyboard focus are distinct. Left/Right browse the seven desk pages plus Matchday; Enter opens the focused destination; 1–7 and Tab remain fast paths. Help now handles direct jumps and matches its displayed controls. Unit tests cover browse/open routing; PTY runs cover layout, shortcuts and matchday/season flows.
- Replaced the narrow-width nested boxes with headings and separators, shortened the responsive game header, and moved the footer to the final available row. Wider terminals retain the framed panel treatment. The Home table now highlights the player's club rather than the league leader.
- Tactical instruction letters still cycle their setting; `-`/`+` adjust the focused setting so Left/Right can consistently browse the section bar. Updated the manual, in-game guide and screen assertions.
- At both terminal sizes the full season and live matchday replay passed, including talk, report views, selected substitutions and round settlement. The UI change does not touch shared bezel code or alter the game simulation.
