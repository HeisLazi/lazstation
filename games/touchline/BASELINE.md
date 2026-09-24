# Touchline baseline

**Snapshot date:** 24 September 2026. **Evidence class:** source/workspace
inspection, benchmark and fixture runs, unit tests, PTY captures and an
isolated doctor run. The 80x24 VT replay has a recorded rendering limitation;
it is not treated as evidence of a physical-terminal defect.

## Snapshot

- Repository HEAD at inspection: `291fef5c52f9538119371d232396a317a83c9bca`.
- Game manifest: Ekse Slaan Ball, slug `touchline`, version `0.2.0`, entry
  `main.py`.
- Save wrapper and career schema: version 2 (`SAVE_DEFAULTS` and
  `new_career` in `main.py`).
- Runtime reported by `python3 --version`: Python 3.14.7.
- Current rules are in the legacy `main.py`; the match progresses in six
  15-minute periods. Each side's period workload depends on its tempo. A match
  is a seeded event/stat simulation, not a spatial player-and-ball engine.
- The current checkout includes uncommitted shared changes and a locked
  second worktree. `sdk/termstation_ui.py`, `tests/` and `.claude/` are
  untracked. These are not part of P00's owned changes. In particular,
  committed `main.py` imports the currently untracked `termstation_ui` module.

## Static integrity observations

These are code observations, not reproduced runtime failures:

| Area | Source evidence | Observed behavior / remaining work |
|---|---|---|
| Unavailable-player fallback | `main.py`, `lineup_for` | The initial selection and best-lineup replacement filter availability, but a final roster fallback can append a player without checking injury availability. P05 must define reduced-team and goalkeeper behavior without silently fielding an unavailable player. |
| Contract expiry | `main.py`, `begin_next_season` and `resolve_offer` | Season rollover decrements `contract_years` to zero, but this path does not release the player, update market availability, or create a renewal/expiry settlement. Define expiry semantics before building contracts. |
| Season prize symmetry | `main.py`, `finish_season` | Season-end prize and transfer-budget uplift are applied to `career["club_id"]`; other clubs receive no comparable place-based season prize here. Decide and record competition-wide prize rules in the economy package. |
| Long-term match history | `main.py`, `apply_match_result` | The detailed `results` list is truncated to its last 200 entries. Season summaries keep tables and movement, not the complete match event archive. Define retention and historical-migration behavior before long careers. |
| Terminal output ownership | `main.py`, `_restore_bezel_bottom_right` and `_run` | Curses drawing is mixed with direct ANSI writes to `sys.stdout` for the bezel. This is a boundary to inspect in PTY captures; no visual defect is claimed without those captures. |
| Domain imports | `main.py` module imports and UI handlers | Rule functions share a module with curses/SDK/UI imports. The new engine needs the game-local module exception and a headless import path before domain work. |

## Executed benchmark and fixture evidence

Both benchmark commands ran on the environment listed above with no career
save writes. The match run rejected award calls; the season run captured and
discarded the expected `season-finished` award call.

| Workload | Command | Measured result |
|---|---|---|
| Individual matches | `python3 -m games.touchline.benchmarks --workload match --count 200 --seed 1 --home BRP --away GLA` | 200 matches / 1,200 periods / 10,077 full-match events; 318 goals, 2,372 shots, 945 on target; 4,263,205 serialized match-state bytes; 0.448246 s simulation, 0.505635 s wall time (446.1837 matches/s in simulation time). |
| Complete season | `python3 -m games.touchline.benchmarks --workload season --count 1 --seed 1 --club BRP` | 60 fixtures / 360 periods; 105 goals, 621 shots, 267 on target, 658 stored result highlights; 278,078 serialized result-row/summary bytes; 0.171805 s simulation, 0.181190 s wall time (349.2324 fixtures/s in simulation time). |

These are single-run throughput samples, not calibrated football outcomes or
performance guarantees. The season byte count measures the result rows and
summary, not a full save. The match byte count measures full in-memory match
states. `processor` was unavailable from Python; the captured environment
reported 12 logical CPUs.

The fixture generator ran as
`python3 -m games.touchline.fixtures --output-dir /tmp/touchline-p00.iSYRk2/fixtures --seed 1 --club BRP`
and exited 0. Its generator-level lifecycle checks and JSON serialize/reload
checks passed, including reloading the written files. The manifest reports:

| Fixture | Round | Complete | Live match | Results | File size |
|---|---:|---:|---:|---:|---:|
| `fresh.json` | 0/10 | no | no | 0 | 180,403 bytes |
| `live.json` | 0/10 | no | yes | 0 | 191,735 bytes |
| `midseason.json` | 5/10 | no | no | 30 | 451,096 bytes |
| `finished.json` | 10/10 | yes | no | 60 | 680,702 bytes |

`manifest.json` records generator/engine/save versions, seed, lifecycle and
SHA-256 hashes. The fixtures remain in `/tmp` and are not repository assets.

## P00 runtime evidence

The legacy unit suite ran in an isolated save/XDG environment:
`python3 -m unittest games.touchline.test_game` exited 0 (13 tests, 1.496 s).

The full `season_scenario.json` ran under PTY at both required sizes, using
separate temporary save directories. Both exited 0 and the `home`, `tactics`,
`match-01`, `round-01` and `season-review` frames were inspected:

| Size | Result | Inspection |
|---|---|---|
| 80x24 | Exit 0; complete season reached review. | Replay has a few stray `ss`, `i` and `es` fragments near the right edge and some joined match-feed text. The outer border is mostly drawn. This is recorded as a narrow-width VT replay limitation, not a verified physical-terminal rendering defect. |
| 110x30 | Exit 0; complete season reached review. | Layout, border and text were clean/readable in the inspected frames. |

The isolated `python3 -m termstation doctor` exited 0 and found eight games;
all manifests, including Touchline and Gladiator, were accepted. This verifies
manifest discovery only, not simulation correctness.

Artifacts were kept outside the repository under `/tmp/touchline-p00-checks.eZPrzx/`
(`pty80`, `pty110`; isolated doctor directories) and are not game assets. The
exact commands and package-level acceptance state are recorded in
`STATUS.md`.

The P00 benchmark measures seeded unsettled matches or completed seasons
against authored current content and reports Python/platform/CPU metadata,
workload counts, simulation time and serialized result size. It intentionally
does not write saves. This is a legacy baseline, not a claim that current
outcomes are calibrated or tactically realistic.
