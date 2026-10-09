# Touchline handoff

**Updated:** 5 October 2026

**Project:** Ekse Slaan Ball (game slug: `touchline`)

**Repository:** `/home/lazi/Projects/personal/heisprojects/termstation`

## Where the project stands

The current branch is `main` at `b595759` (`feat(touchline): add deterministic match physics`). The project has a playable legacy football-management career plus a separate, developing match-simulation foundation.

Completed work recorded in `STATUS.md`:

- P00: reproducible baseline, benchmark and synthetic-save fixtures.
- P01: deterministic domain contracts, time, records and serialization.
- P02: fictional player profiles, squads and validated tactical-intention data.
- MUD-01: pre-match team talks, explicit outgoing/incoming substitution selection, and Live/Events/Stats match views.
- UI-01: cleaner keyboard navigation and a responsive layout for compact and wider terminals.
- P03: deterministic player movement, ball flight, passing, receiving and interception primitives.

Recorded checks for P03 include 18 focused physics tests, 34 game-local checks, 24 legacy game tests, a fixed-step probe and a compile check. Earlier status entries document UI PTY coverage at 80×24 and 110×30. These are historical results; they have not been rerun as part of this handoff.

## Important gap

The new `games/touchline/esb` simulation is not yet a complete match engine and is not connected to the legacy career flow. The career still uses its old match resolution. Continuous possession, scoring/rules, custom formation play, career integration and save migration are not complete. Do not describe the physics primitives or tactical data as a playable new-engine match.

The user specifically chose **free placement** for formation creation, and also asked for clearer, more spacious-feeling menus and a better matchday experience. Team talks, manual substitutions, match views and responsive navigation have already been added to the legacy game. Free-placement formations have not. A formation editor should affect actual player positions and tactical behavior in the new engine, not just draw a pitch diagram.

## Suggested next slice

The implementation plan’s next package is **P04: continuous possession and player decisions**. It builds on P03 with perception, feasible actions, player choice and execution; contested open play; and continuations after regains, deflections and rebounds. Preserve chronological event and assist lineage, and test that player capabilities affect the appropriate decision/action stage without unexplained bonuses.

The planned route after that is P05 match rules and restarts, P06 coordinated tactics and counterplay, P07 a user-facing Tactical Laboratory, then P08 career integration and migration. This makes free placement a later, functional editor rather than a decorative early screen. Read `IMPLEMENTATION.md` and `ENGINEERING_CONTRACTS.md` for exact package requirements and acceptance scenarios before coding.

## Files to read

Start with this handoff and `STATUS.md`, then read:

- `DESIGN.md` for the intended player experience.
- `IMPLEMENTATION.md` for package boundaries and dependencies.
- `ROADMAP.md` for broader milestones.
- `ENGINEERING_CONTRACTS.md` for domain rules and testable acceptance cases.
- `LUNA_HANDOFF.md` for the original workflow and safety guidance; its P00 starting instructions are historical.

There are existing uncommitted changes across the shared repository, including planning edits in the Touchline design/implementation/roadmap and work in other games, tools and the shared SDK. Preserve them. Check `git status`, the index and worktrees before editing; do not use broad staging, reset, clean or stash. In particular, the planning edits about autonomous friendships, mentorship and reunions are plans, not implemented gameplay.
