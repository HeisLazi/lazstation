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
