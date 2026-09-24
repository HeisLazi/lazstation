# Touchline implementation status

## P00 — reproducible baseline and constraints

- Status: `in_progress`
- Base SHA: `291fef5c52f9538119371d232396a317a83c9bca`
- Intended owned paths: `games/touchline/_baseline.py`, `games/touchline/benchmarks.py`, `games/touchline/fixtures.py`, `games/touchline/ARCHITECTURE.md`, `games/touchline/BASELINE.md`, `games/touchline/STATUS.md`.
- Behavior: provide a read-only, seeded legacy-match benchmark; generate explicit synthetic v2 save fixtures for fresh, live-match, midseason and season-complete states; document the module boundary and observed baseline limitations.
- Acceptance: P00-ARCH (entry point/module exception and shared UI dependency are accurately described); P00-BENCH (explicit CLI, seeded match/season count, environment/version/timing/count JSON, optional explicit output destination, no save or persisted award effects); P00-FIXTURES (all four lifecycle states, provenance, schema/engine labels, serialize/reload equality, refuse to overwrite existing outputs); P00-EVIDENCE (source observations are separated from runtime evidence).
- Required evidence still outstanding: `python3 -m unittest games.touchline.test_game`; `season_scenario.json` at 80x24 and 110x30 with isolated save directories and inspected frames; isolated `python3 -m termstation doctor`.
- Exclusions: no changes to `main.py` gameplay, shared SDK/platform files, root tools, other games or personal career saves; no new match engine work in P00.

## Work log

- Initial inspection: `main.py` declares save schema v2 and game manifest 0.2.0; Python reports 3.14.7. `main.py` imports `termstation_ui`, which exists only as an untracked shared SDK file in this checkout. The current branch is `main` at the base SHA above; the index had no staged changes. A separate locked worktree exists and is out of scope.
- No unit test, PTY scenario or doctor command has been run in this pass. No visual/gameplay acceptance result is claimed.

- Benchmark evidence: 200 seeded BRP–GLA matches, 0.448246 s simulation time; one complete 60-fixture BRP season, 0.171805 s simulation time. Full counts and environment are in `BASELINE.md`.
- Fixture evidence: seed 1 / BRP generated `fresh`, `live`, `midseason` and `finished` v2 saves; lifecycle, serialize/reload and written-file reload checks passed. Output and hashes are under `/tmp/touchline-p00.iSYRk2/fixtures` and recorded in its manifest.
- Static work completed in this pass: documented the accepted game-local module exception and shared UI dependency; added the P00 headless boundary, match/season benchmark CLI and synthetic v2 fixture generator; recorded source-level integrity observations and remaining evidence gates.

## Completion evidence

Pending. P00 remains incomplete until required evidence is recorded and reviewed.
