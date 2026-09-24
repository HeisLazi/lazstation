# Touchline architecture boundary

**Recorded:** 24 September 2026. **Applies to:** the legacy 0.2.0 game and the
planned replacement engine.

## Current legacy boundary

- `main.py` is both the launcher and the current rules/UI module. It imports
  `curses`, `termstation_sdk` and `termstation_ui` at module load. Match rules
  such as `new_match`, `simulate_period`, `simulate_match` and
  `apply_match_result` are mixed with terminal screens and input handling.
- `content.py` and `tideway.py` hold editable authored players, clubs, tactics,
  prose and fixtures. Keep authored content separate from rules.
- Saves use wrapper and career schema version 2. The manifest reports game
  version 0.2.0; the legacy simulation has no distinct engine-version field.
- `sdk/termstation_ui.py` is currently an untracked shared file in this
  checkout. `main.py` imports it, but P00 does not own or stage it. The
  headless P00 tools install an inert `termstation_ui` import shim and reject
  accidental rendering. This permits rule-only benchmarking from a checkout
  whose shared UI helper is not committed.
- P00 blocks `termstation_sdk.save`; match benchmarks reject award calls, while
  season benchmarks and fixture generation capture and discard them. The tools
  never use a personal career save directory.

## Accepted module exception

The console brief says to put rules in `main.py`. Touchline's accepted scope
requires distinct match, tactics, people, knowledge, club, economy, world,
persistence and presentation domains. Therefore:

1. `main.py` remains the registered entry point and legacy adapter until
   parity, migration and integration gates pass.
2. New simulation rules belong in a uniquely named game-local package such as
   `games/touchline/esb/`; do not create generic top-level modules that collide
   with other games.
3. Authored data remains editable in game-local data modules. Introduce only
   the records and modules needed by the active package; do not scaffold every
   future domain at once.
4. Domain modules introduced by P01 onward must not initialize curses, read or
   write saves, issue awards, or import the terminal UI. Pass data and explicit
   commands across those boundaries.
5. Keep all other console contracts: the manifest slug remains `touchline`,
   saves remain recoverable/versioned, content is original, and game work
   stays under `games/touchline/`.

P00 records this exception only. It does not change `main.py`, migrate saves,
or claim the planned domains exist.
